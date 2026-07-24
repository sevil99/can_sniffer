from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, TypeAlias


def import_pandas():
    try:
        import pandas as pandas_module
    except ModuleNotFoundError as error:
        if error.name != "pandas":
            raise

        command = f'"{sys.executable}" -m pip install pandas openpyxl'
        raise SystemExit(
            "Не найден pandas для Python, которым запущен дешифровщик.\n"
            f"Сейчас используется: {sys.executable}\n\n"
            "Установите зависимости именно в этот Python:\n"
            f"{command}\n\n"
            "Важно: команда `pip install pandas` может ставить пакет в другой Python."
        ) from error

    try:
        import openpyxl  # noqa: F401
    except ModuleNotFoundError as error:
        command = f'"{sys.executable}" -m pip install openpyxl'
        raise SystemExit(
            "Не найден openpyxl, он нужен для записи Excel-файла.\n"
            f"Сейчас используется: {sys.executable}\n\n"
            "Установите зависимость именно в этот Python:\n"
            f"{command}"
        ) from error

    return pandas_module


pd = import_pandas()


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from can_signal import ProjectTemplate, parse_can_id, parse_message_signals  # noqa: E402
from template_registry import get_mid_cylinders, get_mid_metrics, list_template_infos, load_template_definition  # noqa: E402


ProgressCallback = Callable[[str, float | None], None]
PandasDataFrame: TypeAlias = Any
PandasSeries: TypeAlias = Any


TIME_MODE_RELATIVE = "relative"
TIME_MODE_ABSOLUTE = "absolute"
TIME_MODE_CHOICES = (TIME_MODE_RELATIVE, TIME_MODE_ABSOLUTE)
TIMESEC_DECIMALS = 3
EXCEL_MAX_ROWS = 1_048_576
EXCEL_DATA_ROWS_PER_SHEET = EXCEL_MAX_ROWS - 1
EXCEL_MAX_COLUMNS = 16_384


ID_COL_CANDIDATES = (
    "CAN_ID_Hex",
    "CAN_ID_Dec",
    "CAN ID",
    "CAN_ID",
    "Message_ID",
    "Arbitration_ID",
    "ID",
)
DATA_COL_CANDIDATES = ("Data_Hex", "DATA_HEX", "Data", "DATA", "Bytes", "Payload")
CHANNEL_COL_CANDIDATES = ("Channel", "CH", "Can_Channel")
TS_COL_CANDIDATES = ("Wall_Time", "Timestamp", "TIME", "Time", "DateTime", "Datetime", "TimeStamp")
ELAPSED_COL_CANDIDATES = ("Session_Elapsed_s", "TimeSec", "Time_s", "Elapsed", "Elapsed_s")
RAW_LOG_RE = re.compile(
    r"\b(?:SFF|EFF)\s+0X(?P<id>[0-9A-Fa-f]+)\s+(?P<length>\d+)\s+HEX\s+(?P<data>(?:[0-9A-Fa-f]{2}\s*){1,8})",
    re.IGNORECASE,
)


def console_status(message: str) -> None:
    print(f"[decoder] {message}", flush=True)


def report_progress(progress: ProgressCallback | None, message: str, fraction: float | None = None) -> None:
    if progress is not None:
        progress(message, fraction)


def bring_to_front(window: tk.Misc) -> None:
    window.update_idletasks()
    try:
        window.deiconify()
    except tk.TclError:
        pass
    try:
        window.lift()
        window.attributes("-topmost", True)
        window.after(600, lambda: window.attributes("-topmost", False))
        window.focus_force()
    except tk.TclError:
        pass
    window.update()


def set_status(root: tk.Tk, message: str) -> None:
    status_var = getattr(root, "status_var", None)
    if status_var is not None:
        status_var.set(message)
        root.update_idletasks()
    console_status(message)


def create_root() -> tk.Tk:
    root = tk.Tk()
    root.title("CAN log decoder")
    root.geometry("520x110")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text="CAN log decoder", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    root.status_var = tk.StringVar(value="Запуск...")
    ttk.Label(frame, textvariable=root.status_var, wraplength=480).pack(anchor="w", pady=(8, 0))

    bring_to_front(root)
    return root


@dataclass(frozen=True)
class LoggedCanMessage:
    id: int
    data: bytes
    length: int
    receive_time: datetime | None = None
    timestamp: Any = ""

    def get_id_string(self) -> str:
        return f"0x{self.id:03X}" if self.id <= 0x7FF else f"0x{self.id:08X}"

    def get_data_hex(self) -> str:
        return " ".join(f"{byte:02X}" for byte in self.data)


@dataclass(frozen=True)
class TableColumns:
    message_id: str | None
    data: str | None
    channel: str | None
    timestamp: str | None
    elapsed: str | None
    byte_columns: tuple[str | None, ...]


def normalize_column_name(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", str(value).strip().lower())


def find_column(df: PandasDataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        column = normalized.get(normalize_column_name(candidate))
        if column is not None:
            return column
    return None


def find_byte_columns(df: PandasDataFrame) -> tuple[str | None, ...]:
    normalized = {normalize_column_name(column): column for column in df.columns}
    return tuple(normalized.get(normalize_column_name(f"Byte_{index}")) for index in range(8))


def discover_columns(df: PandasDataFrame) -> TableColumns:
    return TableColumns(
        message_id=find_column(df, ID_COL_CANDIDATES),
        data=find_column(df, DATA_COL_CANDIDATES),
        channel=find_column(df, CHANNEL_COL_CANDIDATES),
        timestamp=find_column(df, TS_COL_CANDIDATES),
        elapsed=find_column(df, ELAPSED_COL_CANDIDATES),
        byte_columns=find_byte_columns(df),
    )


def expand_rotated_can_logs(paths: list[str | Path]) -> list[Path]:
    expanded: list[Path] = []
    seen: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path)
        candidates = [path]
        if path.is_file() and re.fullmatch(r"can_messages(?:_\d{3})?\.csv", path.name, flags=re.IGNORECASE):
            candidates = sorted(path.parent.glob("can_messages*.csv"))

        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            expanded.append(candidate)

    return expanded


def read_input_files(paths: list[str | Path], progress: ProgressCallback | None = None) -> PandasDataFrame:
    frames: list[PandasDataFrame] = []
    input_paths = expand_rotated_can_logs(paths)
    total_files = len(input_paths)
    if total_files != len(paths):
        report_progress(progress, f"Найдены части CSV-сессии: {total_files} файлов", None)

    for file_index, path in enumerate(input_paths, start=1):
        report_progress(progress, f"Читаю файл {file_index}/{total_files}: {path.name}", None)
        if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
            sheets = pd.read_excel(path, sheet_name=None)
            for sheet_name, sheet_df in sheets.items():
                if sheet_df.empty:
                    continue
                sheet_df = sheet_df.copy()
                sheet_df["Source_File"] = path.name
                sheet_df["Source_Sheet"] = sheet_name
                frames.append(sheet_df)
        else:
            frame = read_csv_file(path)
            frame["Source_File"] = path.name
            frame["Source_Sheet"] = ""
            frames.append(frame)

    if not frames:
        raise ValueError("Не найдено строк для расшифровки.")
    result = pd.concat(frames, ignore_index=True)
    report_progress(progress, f"Прочитано строк: {len(result)}", None)
    return result


def read_csv_file(path: Path) -> PandasDataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return pd.read_csv(path, encoding=encoding, sep=None, engine="python")
        except Exception as error:
            last_error = error
    raise ValueError(f"Не удалось прочитать CSV {path}: {last_error}")


def is_empty(value: Any) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def parse_int_cell(value: Any, assume_hex: bool = False) -> int | None:
    if is_empty(value):
        return None

    if isinstance(value, int):
        return int(str(value), 16) if assume_hex else value
    if isinstance(value, float) and value.is_integer():
        int_value = int(value)
        return int(str(int_value), 16) if assume_hex else int_value

    text = str(value).strip()
    if not text:
        return None

    text = re.sub(r"\.0$", "", text)
    if text.lower().startswith("0x"):
        return int(text, 16)

    if assume_hex or re.search(r"[a-fA-F]", text):
        return int(text, 16)

    return int(float(text))


def parse_message_id(value: Any, column_name: str | None) -> int | None:
    if is_empty(value):
        return None

    column_text = str(column_name or "").lower()
    if "dec" in column_text:
        return parse_int_cell(value, assume_hex=False)

    if isinstance(value, int):
        return int(str(value), 16)
    if isinstance(value, float) and value.is_integer():
        return int(str(int(value)), 16)

    text = str(value).strip()
    if text.lower().startswith("0x") or re.search(r"[a-fA-F]", text):
        return parse_can_id(text)

    return parse_int_cell(text, assume_hex=True)


def parse_channel(value: Any, default: int) -> int:
    if is_empty(value):
        return default
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else default


def parse_timestamp(value: Any) -> datetime | None:
    if is_empty(value):
        return None
    text = str(value).strip()
    dayfirst = not bool(re.match(r"\d{4}-\d{2}-\d{2}", text))
    parsed = pd.to_datetime(value, dayfirst=dayfirst, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def parse_elapsed(value: Any) -> float | None:
    if is_empty(value):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def parse_hex_bytes_text(value: Any) -> list[int]:
    if is_empty(value):
        return []

    text = str(value).strip()
    if not text:
        return []

    tokens = re.findall(r"(?:0x)?[0-9a-fA-F]+", text)
    if len(tokens) == 1:
        token = tokens[0].removeprefix("0x").removeprefix("0X")
        if len(token) > 2 and len(token) % 2 == 0:
            return [int(token[index : index + 2], 16) for index in range(0, len(token), 2)]

    result: list[int] = []
    for token in tokens:
        token = token.removeprefix("0x").removeprefix("0X")
        if len(token) > 2:
            continue
        result.append(int(token, 16))
    return result


def parse_raw_log_line(value: Any) -> tuple[int, list[int]] | None:
    if is_empty(value):
        return None

    match = RAW_LOG_RE.search(str(value))
    if not match:
        return None

    message_id = int(match.group("id"), 16)
    length = int(match.group("length"))
    data = parse_hex_bytes_text(match.group("data"))[:length]
    return message_id, data


def parse_byte_columns(row: PandasSeries, columns: tuple[str | None, ...]) -> list[int]:
    result: list[int] = []
    for column in columns:
        if column is None or is_empty(row.get(column)):
            continue
        value = parse_int_cell(row.get(column), assume_hex=True)
        if value is None:
            continue
        result.append(value & 0xFF)
    return result


def row_to_messages(
    row: PandasSeries,
    columns: TableColumns,
    template: ProjectTemplate,
    channel: int,
    signals: list[Any],
) -> list[LoggedCanMessage]:
    message_id = parse_message_id(row.get(columns.message_id), columns.message_id) if columns.message_id else None
    data = parse_byte_columns(row, columns.byte_columns)
    if not data and columns.data:
        raw_message = parse_raw_log_line(row.get(columns.data))
        if raw_message is not None and message_id is None:
            message_id, data = raw_message
        else:
            data = parse_hex_bytes_text(row.get(columns.data))

    if message_id is not None and data:
        return [LoggedCanMessage(message_id, bytes(data), len(data))]

    if not data:
        return []

    inferred = infer_legacy_message(data, template, channel, signals)
    return [inferred] if inferred is not None else []


def infer_legacy_message(
    data: list[int],
    template: ProjectTemplate,
    channel: int,
    signals: list[Any],
) -> LoggedCanMessage | None:
    message_ids = {parse_can_id(signal.message_id) for signal in template.signals}
    if len(message_ids) != 1:
        return None

    message_id = next(iter(message_ids))
    full_message = LoggedCanMessage(message_id, bytes(data), len(data))
    if parse_message_signals(full_message, channel, signals):
        return full_message

    for signal in signals:
        if not signal.match_bytes:
            continue

        match = bytes.fromhex(signal.match_bytes)
        value_length = int(signal.length)
        value_start = int(signal.start_byte)
        match_offset = int(signal.match_offset)
        value_bytes: bytes | None = None

        if data[: len(match)] == list(match) and len(data) >= len(match) + value_length:
            value_bytes = bytes(data[len(match) : len(match) + value_length])
        elif len(match) == 2 and len(data) >= 1 + value_length and data[0] == match[0]:
            value_bytes = bytes(data[-value_length:])

        if value_bytes is None:
            continue

        payload_length = max(8, value_start + value_length, match_offset + len(match))
        payload = bytearray(payload_length)
        payload[match_offset : match_offset + len(match)] = match
        payload[value_start : value_start + value_length] = value_bytes
        return LoggedCanMessage(message_id, bytes(payload), len(payload))

    return None


def signals_for_channel(template: ProjectTemplate, channel: int, cache: dict[int, list[Any]]) -> list[Any]:
    if channel not in cache:
        cache[channel] = [replace(signal, channel=channel) for signal in template.signals]
    return cache[channel]


def signal_choice_label(signal: Any, compact: bool = False) -> str:
    if compact:
        return signal.name
    return re.sub(r"^CH\d+:\s*", "", signal.label, flags=re.IGNORECASE)


def filter_template_signals(template: ProjectTemplate, selected_names: set[str] | None) -> ProjectTemplate:
    if selected_names is None:
        return template

    selected = {name.strip() for name in selected_names if name.strip()}
    signals = [
        signal
        for signal in template.signals
        if signal.name in selected or signal.key in selected or signal.label in selected or signal_choice_label(signal) in selected
    ]
    if not signals:
        raise ValueError("Не выбран ни один сигнал для расшифровки.")

    return ProjectTemplate(
        name=template.name,
        channel=template.channel,
        baud_rate=template.baud_rate,
        history_seconds=template.history_seconds,
        signals=signals,
    )


def parse_signal_filter(value: str | None) -> set[str] | None:
    if value is None:
        return None
    selected = {part.strip() for part in value.split(",") if part.strip()}
    if not selected:
        raise ValueError("Список --signals пуст.")
    return selected


def parse_time_mode(value: str | None) -> str:
    if value is None:
        return TIME_MODE_RELATIVE

    normalized = value.strip().lower()
    aliases = {
        "rel": TIME_MODE_RELATIVE,
        "relative": TIME_MODE_RELATIVE,
        "относительно": TIME_MODE_RELATIVE,
        "абсолютно": TIME_MODE_ABSOLUTE,
        "abs": TIME_MODE_ABSOLUTE,
        "absolute": TIME_MODE_ABSOLUTE,
    }
    time_mode = aliases.get(normalized)
    if time_mode is None:
        raise ValueError("Режим времени должен быть relative или absolute.")
    return time_mode


def default_time_mode_for_template(template_path: str | Path, template: ProjectTemplate) -> str:
    path_key = Path(template_path).stem.lower()
    name_key = template.name.strip().lower()
    if path_key == "mid" or name_key == "мид":
        return TIME_MODE_ABSOLUTE
    return TIME_MODE_RELATIVE


def is_mid_template(template_path: str | Path, template: ProjectTemplate) -> bool:
    try:
        definition = load_template_definition(template_path)
    except Exception:
        definition = {}

    template_key = str(definition.get("template_key") or "").strip().lower()
    path_key = Path(template_path).stem.lower()
    name_key = template.name.strip().lower()
    return template_key == "mid" or path_key == "mid" or name_key == "мид"


def is_gas_regulator_template(template_path: str | Path, template: ProjectTemplate) -> bool:
    try:
        definition = load_template_definition(template_path)
    except Exception:
        definition = {}

    template_key = str(definition.get("template_key") or "").strip().lower()
    path_key = Path(template_path).stem.lower()
    name_key = template.name.strip().lower()
    return template_key == "gas_regulator" or path_key == "gas_regulator" or name_key == "регулятор газа"


def time_mode_label(time_mode: str) -> str:
    return "время сообщения HH:MM:SS.mmm" if time_mode == TIME_MODE_ABSOLUTE else "относительно 0.000"


def signal_names_in_template_order(template: ProjectTemplate) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for signal in template.signals:
        if signal.name in seen:
            continue
        names.append(signal.name)
        seen.add(signal.name)
    return names


def mid_signal_cells(template_path: str | Path, template: ProjectTemplate) -> tuple[
    tuple[tuple[str, int], ...],
    tuple[dict[str, Any], ...],
    dict[tuple[str, str], str],
]:
    definition = load_template_definition(template_path)
    cylinders = get_mid_cylinders(definition)
    metrics = get_mid_metrics(definition)
    available_names = {signal.name for signal in template.signals}

    cells: dict[tuple[str, str], str] = {}
    for cylinder, _base_id in cylinders:
        for metric in metrics:
            metric_key = str(metric["key"])
            signal_name = f"{cylinder} {metric['label']}"
            if signal_name in available_names:
                cells[(cylinder, metric_key)] = signal_name

    return cylinders, metrics, cells


def decode_dataframe(
    df: PandasDataFrame,
    template: ProjectTemplate,
    time_mode: str = TIME_MODE_RELATIVE,
    progress: ProgressCallback | None = None,
) -> PandasDataFrame:
    time_mode = parse_time_mode(time_mode)
    columns = discover_columns(df)
    if not columns.message_id and not columns.data and not any(columns.byte_columns):
        raise ValueError(f"Не найдены колонки с CAN ID/данными. Колонки файла: {list(df.columns)}")

    signal_cache: dict[int, list[Any]] = {}
    rows: list[dict[str, Any]] = []
    total_rows = len(df)
    report_progress(progress, f"Расшифровка строки: 0/{total_rows}", 0.0 if total_rows else None)

    for row_index, row in df.iterrows():
        if row_index and row_index % 5000 == 0:
            report_progress(
                progress,
                f"Расшифровка строки: {row_index}/{total_rows}",
                row_index / total_rows if total_rows else None,
            )

        channel = parse_channel(row.get(columns.channel), template.channel) if columns.channel else template.channel
        signals = signals_for_channel(template, channel, signal_cache)
        signal_by_key = {signal.key: signal for signal in signals}
        timestamp = parse_timestamp(row.get(columns.timestamp)) if columns.timestamp else None
        elapsed = parse_elapsed(row.get(columns.elapsed)) if columns.elapsed else None

        for message in row_to_messages(row, columns, template, channel, signals):
            parsed = parse_message_signals(message, channel, signals)
            for signal_key, value in parsed.items():
                signal = signal_by_key.get(signal_key)
                rows.append(
                    {
                        "Timestamp": timestamp,
                        "Elapsed": elapsed,
                        "Source_Row": int(row_index) + 2,
                        "Source_File": row.get("Source_File", ""),
                        "Source_Sheet": row.get("Source_Sheet", ""),
                        "Channel": channel,
                        "CAN_ID": message.get_id_string(),
                        "Data_Hex": message.get_data_hex(),
                        "Signal": signal.name if signal else signal_key,
                        "Value": value,
                    }
                )

    decoded = pd.DataFrame(rows)
    if decoded.empty:
        raise ValueError("В выбранных файлах не найдено сообщений, подходящих под выбранный шаблон.")

    report_progress(progress, f"Формирую таблицы Excel: найдено значений {len(decoded)}", 0.95)
    decoded, time_column = add_time_column(decoded, time_mode)
    signal_order = signal_names_in_template_order(template)
    wide = (
        decoded.pivot_table(index=time_column, columns="Signal", values="Value", aggfunc="last")
        .sort_index()
        .ffill()
        .reset_index()
    )
    ordered_columns = [name for name in signal_order if name in wide.columns]
    extra_columns = [name for name in wide.columns if name != time_column and name not in ordered_columns]
    wide = wide.reindex(columns=[time_column, *ordered_columns, *extra_columns])
    wide.columns.name = None

    report_progress(progress, "Расшифровка завершена", 1.0)
    return wide


def add_time_column(decoded: PandasDataFrame, time_mode: str) -> tuple[PandasDataFrame, str]:
    time_mode = parse_time_mode(time_mode)
    if time_mode == TIME_MODE_ABSOLUTE:
        with_absolute_time = add_absolute_time_column(decoded)
        if with_absolute_time is not None:
            return with_absolute_time, "Time"
    return add_relative_time_column(decoded), "TimeSec"


def add_absolute_time_column(decoded: PandasDataFrame) -> PandasDataFrame | None:
    decoded = decoded.copy()
    timestamps = pd.to_datetime(decoded["Timestamp"], errors="coerce")
    if not timestamps.notna().any():
        return None

    decoded["Time"] = timestamps.dt.round("ms")
    decoded = decoded.dropna(subset=["Time"])
    if decoded.empty:
        return None
    return decoded


def add_relative_time_column(decoded: PandasDataFrame) -> PandasDataFrame:
    decoded = decoded.copy()
    timestamps = pd.to_datetime(decoded["Timestamp"], errors="coerce")
    if timestamps.notna().any():
        first_timestamp = timestamps.dropna().min()
        decoded["TimeSec"] = (timestamps - first_timestamp).dt.total_seconds()
        decoded.loc[decoded["TimeSec"].isna(), "TimeSec"] = decoded["Source_Row"]
        decoded["TimeSec"] = decoded["TimeSec"].round(TIMESEC_DECIMALS)
        return decoded

    elapsed = pd.to_numeric(decoded["Elapsed"], errors="coerce")
    if elapsed.notna().any():
        first_elapsed = elapsed.dropna().min()
        decoded["TimeSec"] = elapsed - first_elapsed
        decoded.loc[decoded["TimeSec"].isna(), "TimeSec"] = decoded["Source_Row"]
        decoded["TimeSec"] = decoded["TimeSec"].round(TIMESEC_DECIMALS)
        return decoded

    decoded["TimeSec"] = decoded["Source_Row"].astype(float)
    return decoded


def excel_file_count(row_count: int) -> int:
    return max(1, (row_count + EXCEL_DATA_ROWS_PER_SHEET - 1) // EXCEL_DATA_ROWS_PER_SHEET)


def format_excel_time_column(worksheet: Any, time_column: str) -> None:
    if time_column == "TimeSec":
        number_format = "0.000"
    elif time_column == "Time":
        number_format = "hh:mm:ss.000"
    else:
        return

    for column_cells in worksheet.iter_cols(min_col=1, max_col=1, min_row=2):
        for cell in column_cells:
            cell.number_format = number_format


def excel_output_path_for_index(output_path: str | Path, file_index: int) -> Path:
    path = Path(output_path)
    if file_index <= 1:
        return path
    suffix = path.suffix or ".xlsx"
    return path.with_name(f"{path.stem}_{file_index:03d}{suffix}")


def write_dataframe_to_excel(output_path: str | Path, df: PandasDataFrame, progress: ProgressCallback | None = None) -> list[Path]:
    if len(df.columns) > EXCEL_MAX_COLUMNS:
        raise ValueError(
            f"Excel поддерживает не больше {EXCEL_MAX_COLUMNS} столбцов на лист, "
            f"а в таблице получилось {len(df.columns)}."
        )

    time_column = str(df.columns[0]) if len(df.columns) else ""
    file_count = excel_file_count(len(df))
    output_paths: list[Path] = []
    for file_index in range(file_count):
        start = file_index * EXCEL_DATA_ROWS_PER_SHEET
        end = min(start + EXCEL_DATA_ROWS_PER_SHEET, len(df))
        part_path = excel_output_path_for_index(output_path, file_index + 1)
        chunk = df.iloc[start:end] if len(df) else df
        if file_count == 1:
            report_progress(progress, f"Запись файла {part_path.name}: строк {len(chunk)}", None)
        else:
            report_progress(progress, f"Запись файла {file_index + 1}/{file_count}: {part_path.name}, строки {start + 1}-{end} из {len(df)}", None)
        with pd.ExcelWriter(part_path, engine="openpyxl") as writer:
            chunk.to_excel(writer, sheet_name="data", index=False)
            format_excel_time_column(writer.sheets["data"], time_column)
        output_paths.append(part_path)
    return output_paths


def convert_files_to_excel(
    input_paths: list[str | Path],
    template_path: str | Path,
    output_path: str | Path,
    selected_signals: set[str] | None = None,
    time_mode: str | None = None,
    progress: ProgressCallback | None = None,
) -> list[Path]:
    report_progress(progress, "Загрузка шаблона", None)
    template = ProjectTemplate.load(template_path)
    if time_mode is None:
        time_mode = default_time_mode_for_template(template_path, template)
    time_mode = parse_time_mode(time_mode)
    template = filter_template_signals(template, selected_signals)
    source = read_input_files(input_paths, progress=progress)
    wide = decode_dataframe(source, template, time_mode=time_mode, progress=progress)

    report_progress(progress, f"Запись Excel: {output_path}", None)
    output_paths = write_dataframe_to_excel(output_path, wide, progress=progress)
    if len(output_paths) == 1:
        report_progress(progress, f"Excel сохранен: {output_paths[0]}", 1.0)
    else:
        report_progress(progress, f"Excel сохранен: {len(output_paths)} файлов", 1.0)
    return output_paths


def run_cli(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Decode CAN logs to Excel.")
    parser.add_argument("files", nargs="*", help="CSV/Excel CAN log files")
    parser.add_argument(
        "-t",
        "--template",
        default=str(PROJECT_ROOT / "templates" / "gas_regulator.json"),
        help="JSON template path. Default: templates/gas_regulator.json",
    )
    parser.add_argument("-o", "--output", help="Output .xlsx path")
    parser.add_argument(
        "-s",
        "--signals",
        help="Comma-separated signal names to decode, for example: PV,SP,CV",
    )
    parser.add_argument(
        "--time-mode",
        choices=TIME_MODE_CHOICES,
        help="Time column mode: relative = seconds from 0 with milliseconds, absolute = message time as HH:MM:SS.mmm.",
    )
    parser.add_argument("--list-signals", action="store_true", help="Print signals from template and exit")
    args = parser.parse_args(argv)

    template_path = Path(args.template)
    output_path = Path(args.output) if args.output else Path(f"{template_path.stem}_decoded.xlsx")
    template = ProjectTemplate.load(template_path)

    if args.list_signals:
        for signal in template.signals:
            print(signal.name)
        return

    if not args.files:
        parser.error("files are required unless --list-signals is used")

    selected_signals = parse_signal_filter(args.signals)
    time_mode = parse_time_mode(args.time_mode) if args.time_mode else default_time_mode_for_template(template_path, template)

    last_percent = -1

    def cli_progress(message: str, fraction: float | None) -> None:
        nonlocal last_percent
        if fraction is None:
            console_status(message)
            return

        percent = int(max(0.0, min(1.0, fraction)) * 100)
        if percent == 100 or percent >= last_percent + 5:
            last_percent = percent
            console_status(f"{message} ({percent}%)")

    console_status(f"Python: {sys.executable}")
    console_status(f"Файлов: {len(args.files)}")
    console_status(f"Шаблон: {template_path}")
    if selected_signals is not None:
        console_status(f"Сигналы: {', '.join(sorted(selected_signals))}")
    console_status(f"Время: {time_mode_label(time_mode)}")
    console_status(f"Выходной файл: {output_path}")
    output_paths = convert_files_to_excel(
        args.files,
        template_path,
        output_path,
        selected_signals=selected_signals,
        time_mode=time_mode,
        progress=cli_progress,
    )
    if len(output_paths) == 1:
        console_status("Готово")
    else:
        console_status(f"Готово, создано файлов: {len(output_paths)}")
        for path in output_paths:
            console_status(str(path))


def choose_template(root: tk.Tk) -> Path | None:
    infos = list_template_infos()
    result: dict[str, Path | None] = {"path": None}

    dialog = tk.Toplevel(root)
    dialog.title("Выберите шаблон")
    dialog.transient(root)
    dialog.resizable(False, False)

    frame = ttk.Frame(dialog, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="Шаблон расшифровки", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

    listbox = tk.Listbox(frame, height=max(3, min(8, len(infos))), width=72, exportselection=False)
    listbox.grid(row=1, column=0, sticky="ew", pady=(8, 8))
    for info in infos:
        listbox.insert(tk.END, f"{info.title} - {info.description}")
    if infos:
        default_index = next((index for index, info in enumerate(infos) if info.key == "gas_regulator"), 0)
        listbox.selection_set(default_index)
        listbox.activate(default_index)

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, sticky="ew")
    buttons.columnconfigure((0, 1, 2), weight=1)

    def use_selected() -> None:
        selection = listbox.curselection()
        if not selection:
            return
        result["path"] = infos[selection[0]].path
        dialog.destroy()

    def choose_file() -> None:
        path = filedialog.askopenfilename(
            parent=dialog,
            title="Выберите JSON-шаблон",
            initialdir=str(PROJECT_ROOT / "templates"),
            filetypes=[("CAN template JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            result["path"] = Path(path)
            dialog.destroy()

    ttk.Button(buttons, text="Открыть", command=use_selected).grid(row=0, column=0, sticky="ew", padx=(0, 4))
    ttk.Button(buttons, text="Из файла...", command=choose_file).grid(row=0, column=1, sticky="ew", padx=4)
    ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=2, sticky="ew", padx=(4, 0))

    dialog.bind("<Return>", lambda _event: use_selected())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    bring_to_front(dialog)
    dialog.grab_set()
    dialog.focus_force()
    root.wait_window(dialog)
    return result["path"]


def choose_signals(root: tk.Tk, template: ProjectTemplate, template_path: str | Path) -> set[str] | None:
    if is_mid_template(template_path, template):
        return choose_mid_signals(root, template, template_path)
    return choose_generic_signals(root, template, compact_labels=is_gas_regulator_template(template_path, template))


def choose_generic_signals(root: tk.Tk, template: ProjectTemplate, compact_labels: bool = False) -> set[str] | None:
    result: dict[str, set[str] | None] = {"signals": None}

    dialog = tk.Toplevel(root)
    dialog.title("Выберите сигналы")
    dialog.transient(root)
    dialog.geometry("540x620")
    dialog.minsize(440, 420)

    root_frame = ttk.Frame(dialog, padding=12)
    root_frame.pack(fill=tk.BOTH, expand=True)
    root_frame.columnconfigure(0, weight=1)
    root_frame.rowconfigure(2, weight=1)

    title_var = tk.StringVar(value=f"Сигналы шаблона: {template.name}")
    count_var = tk.StringVar()

    ttk.Label(root_frame, textvariable=title_var, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(root_frame, textvariable=count_var, foreground="#64748b").grid(row=1, column=0, sticky="w", pady=(2, 8))

    shell = ttk.Frame(root_frame)
    shell.grid(row=2, column=0, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(0, weight=1)

    canvas = tk.Canvas(shell, highlightthickness=0)
    scrollbar = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    list_frame = ttk.Frame(canvas, padding=(0, 0, 8, 0))
    list_window = canvas.create_window((0, 0), window=list_frame, anchor="nw")
    list_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(list_window, width=event.width))

    variables: dict[str, tk.BooleanVar] = {}
    for row, signal in enumerate(template.signals):
        var = tk.BooleanVar(value=False)
        variables[signal.name] = var
        ttk.Checkbutton(list_frame, text=signal_choice_label(signal, compact=compact_labels), variable=var, command=lambda: update_count()).grid(
            row=row,
            column=0,
            sticky="w",
            pady=2,
        )

    buttons = ttk.Frame(root_frame)
    buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))
    buttons.columnconfigure((0, 1, 2, 3), weight=1)

    def update_count() -> None:
        selected_count = sum(1 for var in variables.values() if var.get())
        count_var.set(f"Выбрано: {selected_count} из {len(variables)}")

    def set_all(value: bool) -> None:
        for var in variables.values():
            var.set(value)
        update_count()

    def apply_selection() -> None:
        selected = {name for name, var in variables.items() if var.get()}
        if not selected:
            messagebox.showwarning("Сигналы", "Выберите хотя бы один сигнал.", parent=dialog)
            return
        result["signals"] = selected
        dialog.destroy()

    ttk.Button(buttons, text="Все", command=lambda: set_all(True)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
    ttk.Button(buttons, text="Снять", command=lambda: set_all(False)).grid(row=0, column=1, sticky="ew", padx=4)
    ttk.Button(buttons, text="Продолжить", command=apply_selection).grid(row=0, column=2, sticky="ew", padx=4)
    ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    update_count()
    dialog.bind("<Return>", lambda _event: apply_selection())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    bring_to_front(dialog)
    dialog.grab_set()
    dialog.focus_force()
    root.wait_window(dialog)
    return result["signals"]


def choose_mid_signals(root: tk.Tk, template: ProjectTemplate, template_path: str | Path) -> set[str] | None:
    result: dict[str, set[str] | None] = {"signals": None}
    try:
        cylinders, metrics, cells = mid_signal_cells(template_path, template)
    except Exception:
        return choose_generic_signals(root, template)

    if not cells:
        return choose_generic_signals(root, template)

    dialog = tk.Toplevel(root)
    dialog.title("Выберите сигналы МИД")
    dialog.transient(root)
    dialog.geometry("620x720")
    dialog.minsize(560, 520)

    root_frame = ttk.Frame(dialog, padding=12)
    root_frame.pack(fill=tk.BOTH, expand=True)
    root_frame.columnconfigure(0, weight=1)
    root_frame.rowconfigure(2, weight=1)

    count_var = tk.StringVar()

    ttk.Label(root_frame, text="Проект МИД", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(
        root_frame,
        text="Выберите цилиндры и значения, которые нужно добавить в Excel.",
        foreground="#64748b",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))

    table_shell = ttk.Frame(root_frame)
    table_shell.grid(row=2, column=0, sticky="nsew")
    table_shell.columnconfigure(0, weight=1)
    table_shell.rowconfigure(0, weight=1)

    canvas = tk.Canvas(table_shell, highlightthickness=0)
    scrollbar = ttk.Scrollbar(table_shell, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    table = ttk.Frame(canvas, padding=(0, 0, 8, 0))
    table_window = canvas.create_window((0, 0), window=table, anchor="nw")
    table.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(table_window, width=event.width))

    ttk.Label(table, text="Цилиндр", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
    for column, metric in enumerate(metrics, start=1):
        ttk.Label(table, text=str(metric["label"]), font=("Segoe UI", 9, "bold")).grid(row=0, column=column, padx=8)

    variables: dict[tuple[str, str], tk.BooleanVar] = {}
    for row, (cylinder, _base_id) in enumerate(cylinders, start=1):
        ttk.Label(table, text=cylinder).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 12))
        for column, metric in enumerate(metrics, start=1):
            metric_key = str(metric["key"])
            signal_name = cells.get((cylinder, metric_key))
            if signal_name is None:
                ttk.Label(table, text="-", foreground="#94a3b8").grid(row=row, column=column, padx=8, pady=2)
                continue

            var = tk.BooleanVar(value=False)
            variables[(cylinder, metric_key)] = var
            ttk.Checkbutton(table, variable=var, command=lambda: update_count()).grid(
                row=row,
                column=column,
                padx=8,
                pady=2,
            )

    ttk.Label(root_frame, textvariable=count_var, foreground="#64748b").grid(row=3, column=0, sticky="w", pady=(10, 0))

    buttons = ttk.Frame(root_frame)
    buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
    buttons.columnconfigure((0, 1, 2, 3), weight=1)

    def update_count() -> None:
        selected_count = sum(1 for var in variables.values() if var.get())
        count_var.set(f"Выбрано: {selected_count} из {len(variables)}")

    def set_all(value: bool) -> None:
        for var in variables.values():
            var.set(value)
        update_count()

    def apply_selection() -> None:
        selected: set[str] = set()
        for (cylinder, metric_key), var in variables.items():
            if var.get():
                selected.add(cells[(cylinder, metric_key)])

        if not selected:
            messagebox.showwarning("МИД", "Выберите хотя бы один сигнал.", parent=dialog)
            return

        result["signals"] = selected
        dialog.destroy()

    ttk.Button(buttons, text="Все", command=lambda: set_all(True)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
    ttk.Button(buttons, text="Снять", command=lambda: set_all(False)).grid(row=0, column=1, sticky="ew", padx=4)
    ttk.Button(buttons, text="Продолжить", command=apply_selection).grid(row=0, column=2, sticky="ew", padx=4)
    ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    update_count()
    dialog.bind("<Return>", lambda _event: apply_selection())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    bring_to_front(dialog)
    dialog.grab_set()
    dialog.focus_force()
    root.wait_window(dialog)
    return result["signals"]


def choose_time_mode(root: tk.Tk, template: ProjectTemplate, template_path: str | Path) -> str | None:
    default_mode = default_time_mode_for_template(template_path, template)
    result: dict[str, str | None] = {"time_mode": None}

    dialog = tk.Toplevel(root)
    dialog.title("Выберите время")
    dialog.transient(root)
    dialog.resizable(False, False)

    frame = ttk.Frame(dialog, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)

    mode_var = tk.StringVar(value=default_mode)

    ttk.Label(frame, text="Как записывать время в Excel", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text=f"По умолчанию для `{template.name}`: {time_mode_label(default_mode)}.", foreground="#64748b").grid(
        row=1,
        column=0,
        sticky="w",
        pady=(2, 8),
    )
    ttk.Radiobutton(
        frame,
        text="Относительно 0: первый столбец TimeSec, секунды от начала с миллисекундами",
        variable=mode_var,
        value=TIME_MODE_RELATIVE,
    ).grid(row=2, column=0, sticky="w", pady=3)
    ttk.Radiobutton(
        frame,
        text="Абсолютное: первый столбец Time, время сообщения в формате HH:MM:SS.mmm",
        variable=mode_var,
        value=TIME_MODE_ABSOLUTE,
    ).grid(row=3, column=0, sticky="w", pady=3)

    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
    buttons.columnconfigure((0, 1), weight=1)

    def apply_selection() -> None:
        result["time_mode"] = mode_var.get()
        dialog.destroy()

    ttk.Button(buttons, text="Продолжить", command=apply_selection).grid(row=0, column=0, sticky="ew", padx=(0, 4))
    ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

    dialog.bind("<Return>", lambda _event: apply_selection())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    bring_to_front(dialog)
    dialog.grab_set()
    dialog.focus_force()
    root.wait_window(dialog)
    return result["time_mode"]


def main() -> None:
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
        return

    console_status(f"Python: {sys.executable}")
    root = create_root()

    try:
        set_status(root, "Открытие окна выбора CSV/Excel файлов...")
        bring_to_front(root)
        files = filedialog.askopenfilenames(
            parent=root,
            title="Выберите CSV или Excel файлы CAN-лога",
            filetypes=[
                ("CAN logs", "*.csv *.xlsx *.xls *.xlsm"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx *.xls *.xlsm"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            set_status(root, "Файлы не выбраны, выход.")
            return

        set_status(root, f"Выбрано файлов: {len(files)}. Открытие выбор шаблона...")
        template_path = choose_template(root)
        if template_path is None:
            set_status(root, "Шаблон не выбран, выход.")
            return

        template = ProjectTemplate.load(template_path)
        set_status(root, "Открытие выбора сигналов...")
        selected_signals = choose_signals(root, template, template_path)
        if selected_signals is None:
            set_status(root, "Сигналы не выбраны, выхожу.")
            return

        set_status(root, "Открытие выбора режима времени...")
        time_mode = choose_time_mode(root, template, template_path)
        if time_mode is None:
            set_status(root, "Режим времени не выбран, выхожу.")
            return

        set_status(root, "Открытие окна сохранения Excel...")
        bring_to_front(root)
        save_path = filedialog.asksaveasfilename(
            parent=root,
            title="Сохранить расшифрованный Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"{Path(template_path).stem}_decoded.xlsx",
        )
        if not save_path:
            set_status(root, "Путь сохранения не выбран, выход.")
            return

        def gui_progress(message: str, fraction: float | None) -> None:
            if fraction is None:
                set_status(root, message)
            else:
                set_status(root, f"{message} ({int(fraction * 100)}%)")

        set_status(root, "Расшифровка сообщения и запись Excel...")
        output_paths = convert_files_to_excel(
            sorted(files),
            template_path,
            save_path,
            selected_signals=selected_signals,
            time_mode=time_mode,
            progress=gui_progress,
        )
        if len(output_paths) == 1:
            set_status(root, f"Готово: {output_paths[0]}")
            messagebox.showinfo("Готово", f"Файл создан:\n{output_paths[0]}", parent=root)
        else:
            files_text = "\n".join(str(path) for path in output_paths)
            set_status(root, f"Готово: создано файлов {len(output_paths)}")
            messagebox.showinfo("Готово", f"Создано файлов: {len(output_paths)}\n\n{files_text}", parent=root)

    except Exception as error:
        set_status(root, f"Ошибка: {error}")
        messagebox.showerror("Ошибка", str(error), parent=root)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()

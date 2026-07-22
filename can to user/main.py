from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


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
from template_registry import list_template_infos  # noqa: E402


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


def find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        column = normalized.get(normalize_column_name(candidate))
        if column is not None:
            return column
    return None


def find_byte_columns(df: pd.DataFrame) -> tuple[str | None, ...]:
    normalized = {normalize_column_name(column): column for column in df.columns}
    return tuple(normalized.get(normalize_column_name(f"Byte_{index}")) for index in range(8))


def discover_columns(df: pd.DataFrame) -> TableColumns:
    return TableColumns(
        message_id=find_column(df, ID_COL_CANDIDATES),
        data=find_column(df, DATA_COL_CANDIDATES),
        channel=find_column(df, CHANNEL_COL_CANDIDATES),
        timestamp=find_column(df, TS_COL_CANDIDATES),
        elapsed=find_column(df, ELAPSED_COL_CANDIDATES),
        byte_columns=find_byte_columns(df),
    )


def read_input_files(paths: list[str | Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for raw_path in paths:
        path = Path(raw_path)
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
    return pd.concat(frames, ignore_index=True)


def read_csv_file(path: Path) -> pd.DataFrame:
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
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)

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


def parse_byte_columns(row: pd.Series, columns: tuple[str | None, ...]) -> list[int]:
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
    row: pd.Series,
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


def decode_dataframe(df: pd.DataFrame, template: ProjectTemplate) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = discover_columns(df)
    if not columns.message_id and not columns.data and not any(columns.byte_columns):
        raise ValueError(f"Не найдены колонки с CAN ID/данными. Колонки файла: {list(df.columns)}")

    signal_cache: dict[int, list[Any]] = {}
    rows: list[dict[str, Any]] = []

    for row_index, row in df.iterrows():
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

    decoded = add_time_seconds(decoded)
    wide = (
        decoded.pivot_table(index="TimeSec", columns="Signal", values="Value", aggfunc="last")
        .sort_index()
        .ffill()
        .reset_index()
    )
    wide.columns.name = None
    return wide, decoded.sort_values(["TimeSec", "Signal"]).reset_index(drop=True)


def add_time_seconds(decoded: pd.DataFrame) -> pd.DataFrame:
    decoded = decoded.copy()
    timestamps = pd.to_datetime(decoded["Timestamp"], errors="coerce")
    if timestamps.notna().any():
        first_timestamp = timestamps.dropna().min()
        decoded["TimeSec"] = (timestamps - first_timestamp).dt.total_seconds()
        decoded.loc[decoded["TimeSec"].isna(), "TimeSec"] = decoded["Source_Row"]
        return decoded

    elapsed = pd.to_numeric(decoded["Elapsed"], errors="coerce")
    if elapsed.notna().any():
        first_elapsed = elapsed.dropna().min()
        decoded["TimeSec"] = elapsed - first_elapsed
        decoded.loc[decoded["TimeSec"].isna(), "TimeSec"] = decoded["Source_Row"]
        return decoded

    decoded["TimeSec"] = decoded["Source_Row"].astype(float)
    return decoded


def convert_files_to_excel(input_paths: list[str | Path], template_path: str | Path, output_path: str | Path) -> None:
    template = ProjectTemplate.load(template_path)
    source = read_input_files(input_paths)
    wide, decoded = decode_dataframe(source, template)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        wide.to_excel(writer, sheet_name="data", index=False)
        decoded.to_excel(writer, sheet_name="decoded_long", index=False)


def run_cli(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Decode CAN logs to Excel.")
    parser.add_argument("files", nargs="+", help="CSV/Excel CAN log files")
    parser.add_argument(
        "-t",
        "--template",
        default=str(PROJECT_ROOT / "templates" / "gas_regulator.json"),
        help="JSON template path. Default: templates/gas_regulator.json",
    )
    parser.add_argument("-o", "--output", help="Output .xlsx path")
    args = parser.parse_args(argv)

    template_path = Path(args.template)
    output_path = Path(args.output) if args.output else Path(f"{template_path.stem}_decoded.xlsx")

    console_status(f"Python: {sys.executable}")
    console_status(f"Файлов: {len(args.files)}")
    console_status(f"Шаблон: {template_path}")
    console_status(f"Выходной файл: {output_path}")
    convert_files_to_excel(args.files, template_path, output_path)
    console_status("Готово")


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


def main() -> None:
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
        return

    console_status(f"Python: {sys.executable}")
    root = create_root()

    try:
        set_status(root, "Открываю окно выбора CSV/Excel файлов...")
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
            set_status(root, "Файлы не выбраны, выхожу.")
            return

        set_status(root, f"Выбрано файлов: {len(files)}. Открываю выбор шаблона...")
        template_path = choose_template(root)
        if template_path is None:
            set_status(root, "Шаблон не выбран, выхожу.")
            return

        set_status(root, "Открываю окно сохранения Excel...")
        bring_to_front(root)
        save_path = filedialog.asksaveasfilename(
            parent=root,
            title="Сохранить расшифрованный Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"{Path(template_path).stem}_decoded.xlsx",
        )
        if not save_path:
            set_status(root, "Путь сохранения не выбран, выхожу.")
            return

        set_status(root, "Расшифровываю сообщения и записываю Excel...")
        convert_files_to_excel(sorted(files), template_path, save_path)
        set_status(root, f"Готово: {save_path}")
        messagebox.showinfo("Готово", f"Файл создан:\n{save_path}", parent=root)

    except Exception as error:
        set_status(root, f"Ошибка: {error}")
        messagebox.showerror("Ошибка", str(error), parent=root)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from built_in_templates import (
    BUILT_IN_TEMPLATES,
    GAS_REGULATOR_BAUD_RATE_DEFAULT,
    GAS_REGULATOR_DEVICE_ID_DEFAULT,
    GAS_REGULATOR_HISTORY_SECONDS_DEFAULT,
    MID_BAUD_RATE_DEFAULT,
    MID_CYLINDERS,
    MID_HISTORY_SECONDS_DEFAULT,
    MID_METRIC_LABELS,
    PID_IDS,
    build_gas_regulator_template,
    build_mid_template,
    default_mid_selection,
)
from can_receiver import create_receiver
from can_signal import (
    ProjectTemplate,
    SUPPORTED_BYTE_ORDERS,
    SUPPORTED_TYPES,
    SignalDefinition,
    get_message_id_string,
    normalize_can_id,
    parse_can_id,
    parse_message_signals,
)
from session_logger import CsvSessionLogger


BAUD_RATES = (
    "10000",
    "20000",
    "50000",
    "100000",
    "125000",
    "250000",
    "500000",
    "800000",
    "1000000",
)

CHART_COLORS = (
    "#0f766e",
    "#b91c1c",
    "#2563eb",
    "#a16207",
    "#7c3aed",
    "#15803d",
    "#be185d",
    "#0891b2",
)


class CanReader(threading.Thread):
    def __init__(
        self,
        output_queue: queue.Queue[tuple[Any, int]],
        event_queue: queue.Queue[tuple[str, str]],
        channel: int,
        baud_rate: int,
    ):
        super().__init__(daemon=True)
        self.output_queue = output_queue
        self.event_queue = event_queue
        self.channel = channel
        self.baud_rate = baud_rate
        self.stop_event = threading.Event()
        self.receiver = None
        self.dropped_messages = 0

    def run(self) -> None:
        try:
            self.receiver = create_receiver()
            connected = self.receiver.connect(channel=self.channel, baud_rate=self.baud_rate)
            if not connected:
                self.event_queue.put(("error", "Не удалось подключиться к CAN-каналу"))
                return

            self.event_queue.put(("connected", f"Подключено: CH{self.channel}, {self.baud_rate} bit/s"))

            while not self.stop_event.is_set():
                message = self._read_message()
                if message is None:
                    continue

                try:
                    self.output_queue.put_nowait((message, self.channel))
                except queue.Full:
                    self.dropped_messages += 1
                    if self.dropped_messages % 1000 == 1:
                        self.event_queue.put(
                            ("warning", f"Очередь CAN переполнена, пропущено {self.dropped_messages} сообщений")
                        )

        except Exception as error:
            details = "".join(traceback.format_exception_only(type(error), error)).strip()
            self.event_queue.put(("error", details))
        finally:
            if self.receiver is not None:
                try:
                    self.receiver.disconnect()
                except Exception:
                    pass
            self.event_queue.put(("disconnected", "CAN отключен"))

    def stop(self) -> None:
        self.stop_event.set()
        if self.receiver is not None and hasattr(self.receiver, "stop_event"):
            try:
                self.receiver.stop_event.set()
            except Exception:
                pass

    def _read_message(self) -> Any | None:
        if self.receiver is None:
            time.sleep(0.05)
            return None

        try:
            if hasattr(self.receiver, "get_message"):
                return self.receiver.get_message(timeout=0.05)

            if hasattr(self.receiver, "message_queue"):
                return self.receiver.message_queue.get(timeout=0.05)

        except queue.Empty:
            return None
        except Exception as error:
            self.event_queue.put(("warning", f"Ошибка чтения CAN: {error}"))
            time.sleep(0.05)

        return None


class SignalChart(ttk.Frame):
    def __init__(self, parent: tk.Widget, signal: SignalDefinition, color: str):
        super().__init__(parent, padding=(8, 6))
        self.signal = signal
        self.color = color
        self.points: deque[tuple[float, float]] = deque(maxlen=50000)

        self.title_var = tk.StringVar(value=signal.label)
        self.value_var = tk.StringVar(value="нет данных")

        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self.title_var, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.value_var).pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self, height=170, background="#ffffff", highlightthickness=1, highlightbackground="#d6dbe1")
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda _event: self.draw(time.time(), 600, []))

    def append(self, timestamp: float, value: float) -> None:
        self.points.append((timestamp, value))
        self.value_var.set(f"{value:.6g}")

    def clear(self) -> None:
        self.points.clear()
        self.value_var.set("нет данных")
        self.canvas.delete("all")

    def draw(self, now: float, history_seconds: int, markers: list[float]) -> None:
        canvas = self.canvas
        canvas.delete("all")

        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 160)
        left = 54
        right = width - 14
        top = 12
        bottom = height - 28
        start_time = now - history_seconds
        span = max(history_seconds, 1)

        canvas.create_rectangle(0, 0, width, height, fill="#ffffff", outline="")
        for index in range(5):
            y = top + (bottom - top) * index / 4
            canvas.create_line(left, y, right, y, fill="#edf0f3")

        recent = [
            (timestamp, value)
            for timestamp, value in self.points
            if now - timestamp <= history_seconds
        ]

        if not recent:
            canvas.create_text(width / 2, height / 2, text="Нет данных", fill="#6b7280", font=("Segoe UI", 10))
            canvas.create_line(left, bottom, right, bottom, fill="#9ca3af")
            canvas.create_line(left, top, left, bottom, fill="#9ca3af")
            self._draw_markers(canvas, markers, start_time, span, left, right, top, bottom)
            return

        if len(recent) > 1200:
            step = max(1, len(recent) // 1200)
            recent = recent[::step]

        values = [value for _, value in recent]
        min_value = min(values)
        max_value = max(values)
        if min_value == max_value:
            padding = 1.0 if min_value == 0 else abs(min_value) * 0.05
            min_value -= padding
            max_value += padding
        else:
            padding = (max_value - min_value) * 0.08
            min_value -= padding
            max_value += padding

        value_span = max(max_value - min_value, 1e-9)

        coords: list[float] = []
        for timestamp, value in recent:
            x = left + (timestamp - start_time) / span * (right - left)
            y = bottom - (value - min_value) / value_span * (bottom - top)
            coords.extend((max(left, min(right, x)), max(top, min(bottom, y))))

        canvas.create_line(left, bottom, right, bottom, fill="#9ca3af")
        canvas.create_line(left, top, left, bottom, fill="#9ca3af")
        canvas.create_text(8, top + 2, anchor="nw", text=f"{max_value:.4g}", fill="#475569", font=("Segoe UI", 8))
        canvas.create_text(8, bottom - 12, anchor="nw", text=f"{min_value:.4g}", fill="#475569", font=("Segoe UI", 8))
        canvas.create_text(left, height - 18, anchor="nw", text=f"-{history_seconds}s", fill="#64748b", font=("Segoe UI", 8))
        canvas.create_text(right, height - 18, anchor="ne", text="сейчас", fill="#64748b", font=("Segoe UI", 8))
        self._draw_markers(canvas, markers, start_time, span, left, right, top, bottom)

        if len(coords) >= 4:
            canvas.create_line(*coords, fill=self.color, width=2, smooth=False)
        else:
            x, y = coords
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=self.color, outline=self.color)

    def _draw_markers(
        self,
        canvas: tk.Canvas,
        markers: list[float],
        start_time: float,
        span: float,
        left: int,
        right: int,
        top: int,
        bottom: int,
    ) -> None:
        for marker in markers:
            if marker < start_time or marker > start_time + span:
                continue
            x = left + (marker - start_time) / span * (right - left)
            canvas.create_line(x, top, x, bottom, fill="#f97316", dash=(4, 3), width=1)
            label = datetime.fromtimestamp(marker).strftime("%H:%M:%S")
            canvas.create_text(x + 4, top + 4, anchor="nw", text=label, fill="#c2410c", font=("Segoe UI", 8))


class CanMonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CAN Monitor Desktop")
        self.root.geometry("1280x820")
        self.root.minsize(980, 640)

        self.message_queue: queue.Queue[tuple[Any, int]] = queue.Queue(maxsize=50000)
        self.event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.reader: CanReader | None = None
        self.logger: CsvSessionLogger | None = None

        self.signals: list[SignalDefinition] = []
        self.signal_by_key: dict[str, SignalDefinition] = {}
        self.charts: dict[str, SignalChart] = {}
        self.discovered_ids: set[str] = set()
        self.recent_rows: deque[tuple[Any, ...]] = deque(maxlen=200)

        self.session_messages = 0
        self.parsed_points = 0
        self.is_connected = False
        self._message_table_dirty = False
        self._stats_table_dirty = False
        self._closing = False
        self.graph_paused = False
        self.graph_pause_time: float | None = None
        self.time_markers: list[float] = []
        self.can_id_stats: dict[str, dict[str, Any]] = {}

        self.channel_var = tk.StringVar(value="1")
        self.baud_var = tk.StringVar(value="500000")
        self.history_var = tk.IntVar(value=600)
        self.graph_state_var = tk.StringVar(value="Live")
        self.status_var = tk.StringVar(value="Выберите папку для сессий")
        self.session_var = tk.StringVar(value="Сессия: не выбрана")
        self.count_var = tk.StringVar(value="Сообщений: 0")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.root.after(100, self._select_initial_session_root)
        self.root.after(30, self._poll_queues)
        self.root.after(120, self._redraw_charts)
        self.root.after(250, self._refresh_message_table)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(14, weight=1)

        ttk.Label(toolbar, text="Канал").grid(row=0, column=0, padx=(0, 4))
        self.channel_combo = ttk.Combobox(toolbar, textvariable=self.channel_var, width=5, values=("0", "1"), state="readonly")
        self.channel_combo.grid(row=0, column=1, padx=(0, 10))

        ttk.Label(toolbar, text="Скорость").grid(row=0, column=2, padx=(0, 4))
        self.baud_combo = ttk.Combobox(toolbar, textvariable=self.baud_var, width=10, values=BAUD_RATES, state="readonly")
        self.baud_combo.grid(row=0, column=3, padx=(0, 10))

        ttk.Label(toolbar, text="История, сек").grid(row=0, column=4, padx=(0, 4))
        ttk.Spinbox(toolbar, from_=10, to=3600, increment=10, textvariable=self.history_var, width=7).grid(
            row=0,
            column=5,
            padx=(0, 10),
        )

        self.connect_button = ttk.Button(toolbar, text="Подключить", command=self.connect)
        self.connect_button.grid(row=0, column=6, padx=3)
        self.disconnect_button = ttk.Button(toolbar, text="Отключить", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_button.grid(row=0, column=7, padx=3)
        self.new_session_button = ttk.Button(toolbar, text="Новая сессия", command=self.new_session, state=tk.DISABLED)
        self.new_session_button.grid(row=0, column=8, padx=3)
        ttk.Button(toolbar, text="Папка...", command=self.choose_session_root).grid(row=0, column=9, padx=3)
        ttk.Button(toolbar, text="Открыть шаблон", command=self.open_template).grid(row=0, column=10, padx=3)
        ttk.Button(toolbar, text="Сохранить шаблон", command=self.save_template).grid(row=0, column=11, padx=3)

        ttk.Label(toolbar, textvariable=self.count_var).grid(row=0, column=14, sticky="e")
        ttk.Label(toolbar, textvariable=self.status_var).grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))
        ttk.Label(toolbar, textvariable=self.session_var).grid(row=1, column=8, columnspan=7, sticky="e", pady=(6, 0))

        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned, padding=10)
        right = ttk.Frame(paned, padding=(0, 10, 10, 10))
        paned.add(left, weight=1)
        paned.add(right, weight=4)

        self._build_signal_panel(left)
        self._build_main_tabs(right)

    def _build_signal_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(5, weight=1)

        ttk.Label(parent, text="Сигналы", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        columns = ("id", "name", "ch", "type", "bytes")
        self.signals_tree = ttk.Treeview(parent, columns=columns, show="headings", height=10, selectmode="extended")
        for column, title, width in (
            ("id", "CAN ID", 76),
            ("name", "Имя", 110),
            ("ch", "CH", 36),
            ("type", "Тип", 76),
            ("bytes", "Байты", 64),
        ):
            self.signals_tree.heading(column, text=title)
            self.signals_tree.column(column, width=width, anchor=tk.W, stretch=column == "name")
        self.signals_tree.grid(row=1, column=0, sticky="nsew", pady=(6, 8))

        signal_buttons = ttk.Frame(parent)
        signal_buttons.grid(row=2, column=0, sticky="ew")
        signal_buttons.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(signal_buttons, text="Добавить", command=self.show_signal_dialog).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(signal_buttons, text="Из ID", command=self.add_signal_from_selected_id).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(signal_buttons, text="Удалить", command=self.remove_selected_signals).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        ttk.Separator(parent).grid(row=3, column=0, sticky="ew", pady=12)
        ttk.Label(parent, text="Найденные ID", font=("Segoe UI", 11, "bold")).grid(row=4, column=0, sticky="w")

        self.ids_list = tk.Listbox(parent, height=10, exportselection=False)
        self.ids_list.grid(row=5, column=0, sticky="nsew", pady=(6, 0))
        self.ids_list.bind("<Double-Button-1>", lambda _event: self.add_signal_from_selected_id())

    def _build_main_tabs(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")

        graphs_tab = ttk.Frame(notebook)
        messages_tab = ttk.Frame(notebook)
        stats_tab = ttk.Frame(notebook)
        notebook.add(graphs_tab, text="Графики")
        notebook.add(messages_tab, text="Сообщения")
        notebook.add(stats_tab, text="Статистика ID")

        self._build_graphs_tab(graphs_tab)
        self._build_messages_tab(messages_tab)
        self._build_stats_tab(stats_tab)

    def _build_graphs_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        graph_toolbar = ttk.Frame(parent, padding=(0, 0, 0, 8))
        graph_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        graph_toolbar.columnconfigure(9, weight=1)

        self.pause_graph_button = ttk.Button(graph_toolbar, text="Пауза", command=self.toggle_graph_pause)
        self.pause_graph_button.grid(row=0, column=0, padx=(0, 4))
        ttk.Button(graph_toolbar, text="Очистить графики", command=self.clear_graphs).grid(row=0, column=1, padx=4)
        ttk.Button(graph_toolbar, text="Автомасштаб", command=self.autoscale_graphs).grid(row=0, column=2, padx=4)
        ttk.Button(graph_toolbar, text="Масштаб +", command=lambda: self.zoom_time_window(0.5)).grid(row=0, column=3, padx=4)
        ttk.Button(graph_toolbar, text="Масштаб -", command=lambda: self.zoom_time_window(2.0)).grid(row=0, column=4, padx=4)
        ttk.Button(graph_toolbar, text="Вернуться к live", command=self.return_to_live).grid(row=0, column=5, padx=4)
        ttk.Button(graph_toolbar, text="Маркер", command=self.add_time_marker).grid(row=0, column=6, padx=4)
        ttk.Button(graph_toolbar, text="Стереть маркеры", command=self.clear_time_markers).grid(row=0, column=7, padx=4)
        ttk.Label(graph_toolbar, textvariable=self.graph_state_var).grid(row=0, column=9, sticky="e")

        self.charts_canvas = tk.Canvas(parent, background="#f8fafc", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.charts_canvas.yview)
        self.charts_canvas.configure(yscrollcommand=scrollbar.set)

        self.charts_canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        self.charts_frame = ttk.Frame(self.charts_canvas, padding=8)
        self.charts_window = self.charts_canvas.create_window((0, 0), window=self.charts_frame, anchor="nw")
        self.charts_frame.bind(
            "<Configure>",
            lambda _event: self.charts_canvas.configure(scrollregion=self.charts_canvas.bbox("all")),
        )
        self.charts_canvas.bind(
            "<Configure>",
            lambda event: self.charts_canvas.itemconfigure(self.charts_window, width=event.width),
        )

        self.empty_charts_label = ttk.Label(
            self.charts_frame,
            text="Добавьте сигнал или откройте шаблон проекта, чтобы увидеть графики.",
            foreground="#64748b",
        )
        self.empty_charts_label.pack(anchor="w", padx=8, pady=8)

    def _build_messages_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        columns = ("n", "time", "ch", "id", "length", "data", "parsed")
        self.messages_tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, title, width in (
            ("n", "#", 60),
            ("time", "Время", 150),
            ("ch", "CH", 45),
            ("id", "CAN ID", 90),
            ("length", "Len", 55),
            ("data", "Данные", 220),
            ("parsed", "Сигналы", 360),
        ):
            self.messages_tree.heading(column, text=title)
            self.messages_tree.column(column, width=width, anchor=tk.W, stretch=column in ("data", "parsed"))

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.messages_tree.yview)
        self.messages_tree.configure(yscrollcommand=scrollbar.set)
        self.messages_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_stats_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        columns = ("id", "ch", "count", "hz", "last", "length", "sample")
        self.stats_tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, title, width in (
            ("id", "CAN ID", 90),
            ("ch", "CH", 45),
            ("count", "Кол-во", 90),
            ("hz", "Hz", 80),
            ("last", "Последнее", 150),
            ("length", "Len", 55),
            ("sample", "Пример данных", 280),
        ):
            self.stats_tree.heading(column, text=title)
            self.stats_tree.column(column, width=width, anchor=tk.W, stretch=column == "sample")

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=scrollbar.set)
        self.stats_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _select_initial_session_root(self) -> None:
        folder = filedialog.askdirectory(title="Выберите папку, где хранить папки сессий")
        if not folder:
            folder = str(Path.cwd() / "sessions")
        self._create_logger(folder)

    def _create_logger(self, folder: str | Path) -> None:
        try:
            if self.logger is None:
                self.logger = CsvSessionLogger(folder)
            else:
                self.logger.set_root_dir(folder)
            self.new_session_button.configure(state=tk.NORMAL)
            self._clear_session_views()
            self._update_session_label()
            self.status_var.set("CSV-сессия готова")
        except Exception as error:
            messagebox.showerror("Ошибка сессии", str(error))
            self.status_var.set(f"Ошибка сессии: {error}")

    def choose_session_root(self) -> None:
        folder = filedialog.askdirectory(title="Выберите новую корневую папку для сессий")
        if folder:
            self._create_logger(folder)

    def new_session(self) -> None:
        if self.logger is None:
            self.choose_session_root()
            return

        try:
            self.logger.start_new_session()
            self._clear_session_views()
            self._update_session_label()
            self.status_var.set("Открыта новая CSV-сессия")
        except Exception as error:
            messagebox.showerror("Ошибка новой сессии", str(error))

    def connect(self) -> None:
        if self.reader is not None and self.reader.is_alive():
            return

        if self.logger is None:
            self._select_initial_session_root()
            if self.logger is None:
                return

        channel = int(self.channel_var.get())
        baud_rate = int(self.baud_var.get())
        self._set_signal_channels(channel)
        self.reader = CanReader(self.message_queue, self.event_queue, channel, baud_rate)
        self.reader.start()
        self.status_var.set("Подключение к CAN...")
        self.connect_button.configure(state=tk.DISABLED)

    def disconnect(self) -> None:
        if self.reader is not None:
            self.reader.stop()
        self.status_var.set("Отключение CAN...")
        self.disconnect_button.configure(state=tk.DISABLED)

    def open_template(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Открыть шаблон")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text="Источник шаблона", font=("Segoe UI", 11, "bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 10),
        )

        ttk.Button(
            body,
            text="Выбрать JSON-файл...",
            command=lambda: self._open_template_from_file(parent=dialog),
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(body, text="Встроенные").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))

        for row, template_info in enumerate(BUILT_IN_TEMPLATES, start=3):
            card = ttk.Frame(body, padding=(0, 4))
            card.grid(row=row, column=0, columnspan=2, sticky="ew")
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=template_info.title, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=template_info.description, foreground="#64748b", wraplength=420).grid(
                row=1,
                column=0,
                sticky="w",
                pady=(2, 0),
            )
            ttk.Button(
                card,
                text="Открыть",
                command=lambda key=template_info.key: self._open_builtin_template(key, parent=dialog),
            ).grid(row=0, column=1, rowspan=2, padx=(12, 0))

        ttk.Button(body, text="Отмена", command=dialog.destroy).grid(row=99, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.focus()

    def _open_template_from_file(self, parent: tk.Toplevel | None = None) -> None:
        path = filedialog.askopenfilename(
            title="Открыть шаблон проекта",
            filetypes=(("CAN project JSON", "*.json"), ("All files", "*.*")),
            parent=parent,
        )
        if not path:
            return

        try:
            template = ProjectTemplate.load(path)
            self._apply_template(template)
            self.status_var.set(f"Шаблон открыт: {Path(path).name}")
            if parent is not None:
                parent.destroy()
        except Exception as error:
            messagebox.showerror("Ошибка шаблона", str(error), parent=parent)

    def _open_builtin_template(self, key: str, parent: tk.Toplevel) -> None:
        if key == "mid":
            parent.destroy()
            self._show_mid_template_dialog()
            return
        if key == "gas_regulator":
            parent.destroy()
            self._show_gas_regulator_template_dialog()
            return

        messagebox.showerror("Шаблон", f"Неизвестный встроенный шаблон: {key}", parent=parent)

    def _apply_template(self, template: ProjectTemplate) -> None:
        self.signals = list(template.signals)
        self.channel_var.set(str(template.channel))
        self.baud_var.set(str(template.baud_rate))
        self.history_var.set(template.history_seconds)
        self._rebuild_signal_views()

    def _set_signal_channels(self, channel: int) -> None:
        changed = False
        for signal in self.signals:
            if int(signal.channel) != int(channel):
                signal.channel = int(channel)
                changed = True

        if changed:
            self._rebuild_signal_views()
            self.status_var.set(f"Сигналы шаблона переключены на CH{channel}")

    def _show_mid_template_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Встроенный шаблон: МИД")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("620x720")
        dialog.minsize(560, 520)

        selection = default_mid_selection()
        variables: dict[tuple[str, str], tk.BooleanVar] = {}
        channel_var = tk.StringVar(value=self.channel_var.get())
        baud_var = tk.StringVar(value=str(MID_BAUD_RATE_DEFAULT))
        history_var = tk.IntVar(value=MID_HISTORY_SECONDS_DEFAULT)

        root_frame = ttk.Frame(dialog, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(2, weight=1)

        ttk.Label(root_frame, text="Проект МИД", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root_frame,
            text="Выберите цилиндры и значения, которые нужно вывести на графики.",
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
        metric_keys = ("knock", "offset", "sync_errors")
        for column, metric_key in enumerate(metric_keys, start=1):
            ttk.Label(table, text=MID_METRIC_LABELS[metric_key], font=("Segoe UI", 9, "bold")).grid(
                row=0,
                column=column,
                padx=8,
            )

        for row, (cylinder, _base_id) in enumerate(MID_CYLINDERS, start=1):
            ttk.Label(table, text=cylinder).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 12))
            for column, metric_key in enumerate(metric_keys, start=1):
                var = tk.BooleanVar(value=metric_key in selection[cylinder])
                variables[(cylinder, metric_key)] = var
                ttk.Checkbutton(table, variable=var).grid(row=row, column=column, padx=8, pady=2)

        controls = ttk.Frame(root_frame)
        controls.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        controls.columnconfigure(7, weight=1)

        ttk.Label(controls, text="Канал").grid(row=0, column=0, padx=(0, 4))
        ttk.Combobox(controls, textvariable=channel_var, values=("0", "1"), state="readonly", width=5).grid(
            row=0,
            column=1,
            padx=(0, 10),
        )
        ttk.Label(controls, text="Скорость").grid(row=0, column=2, padx=(0, 4))
        ttk.Combobox(controls, textvariable=baud_var, values=BAUD_RATES, state="readonly", width=10).grid(
            row=0,
            column=3,
            padx=(0, 10),
        )
        ttk.Label(controls, text="История, сек").grid(row=0, column=4, padx=(0, 4))
        ttk.Spinbox(controls, from_=10, to=3600, increment=10, textvariable=history_var, width=7).grid(
            row=0,
            column=5,
        )

        buttons = ttk.Frame(root_frame)
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1, 2, 3), weight=1)

        def set_all(value: bool) -> None:
            for var in variables.values():
                var.set(value)

        def apply_mid() -> None:
            selected: dict[str, set[str]] = {}
            for cylinder, _base_id in MID_CYLINDERS:
                selected_metrics = {
                    metric_key
                    for metric_key in metric_keys
                    if variables[(cylinder, metric_key)].get()
                }
                if selected_metrics:
                    selected[cylinder] = selected_metrics

            if not selected:
                messagebox.showwarning("МИД", "Выберите хотя бы один сигнал.", parent=dialog)
                return

            template = build_mid_template(
                selected=selected,
                channel=int(channel_var.get()),
                baud_rate=int(baud_var.get()),
                history_seconds=int(history_var.get()),
            )
            self._apply_template(template)
            self.status_var.set(f"Открыт встроенный шаблон МИД: {len(template.signals)} сигналов")
            dialog.destroy()

        ttk.Button(buttons, text="Все", command=lambda: set_all(True)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Снять", command=lambda: set_all(False)).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(buttons, text="Открыть", command=apply_mid).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.focus()

    def _show_gas_regulator_template_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Встроенный шаблон: Регулятор газа")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        variables: dict[int, tk.BooleanVar] = {}
        device_id_var = tk.StringVar(value=f"0x{GAS_REGULATOR_DEVICE_ID_DEFAULT:03X}")
        channel_var = tk.StringVar(value=self.channel_var.get())
        baud_var = tk.StringVar(value=str(GAS_REGULATOR_BAUD_RATE_DEFAULT))
        history_var = tk.IntVar(value=GAS_REGULATOR_HISTORY_SECONDS_DEFAULT)

        root_frame = ttk.Frame(dialog, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)
        root_frame.columnconfigure(0, weight=1)

        ttk.Label(root_frame, text="Регулятор газа", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root_frame,
            text="Выберите PID-параметры, которые нужно вывести на графики.",
            foreground="#64748b",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        params = ttk.Frame(root_frame)
        params.grid(row=2, column=0, sticky="ew")
        params.columnconfigure(1, weight=1)
        params.columnconfigure(3, weight=1)

        ttk.Label(params, text="CAN ID устройства").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=3)
        ttk.Entry(params, textvariable=device_id_var, width=12).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(params, text="Канал").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=3)
        ttk.Combobox(params, textvariable=channel_var, values=("0", "1"), state="readonly", width=5).grid(
            row=0,
            column=3,
            sticky="w",
            pady=3,
        )
        ttk.Label(params, text="Скорость").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=3)
        ttk.Combobox(params, textvariable=baud_var, values=BAUD_RATES, state="readonly", width=10).grid(
            row=1,
            column=1,
            sticky="w",
            padx=(0, 12),
            pady=3,
        )
        ttk.Label(params, text="История, сек").grid(row=1, column=2, sticky="w", padx=(0, 4), pady=3)
        ttk.Spinbox(params, from_=10, to=3600, increment=10, textvariable=history_var, width=7).grid(
            row=1,
            column=3,
            sticky="w",
            pady=3,
        )

        table = ttk.Frame(root_frame)
        table.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for column in range(3):
            table.columnconfigure(column, weight=1)

        for index, (pid_id, name) in enumerate(PID_IDS.items()):
            row = index // 3
            column = index % 3
            var = tk.BooleanVar(value=False)
            variables[pid_id] = var
            ttk.Checkbutton(table, text=f"0x{pid_id:02X} {name}", variable=var).grid(
                row=row,
                column=column,
                sticky="w",
                padx=(0, 12),
                pady=3,
            )

        buttons = ttk.Frame(root_frame)
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1, 2, 3), weight=1)

        def set_all(value: bool) -> None:
            for var in variables.values():
                var.set(value)

        def apply_gas_regulator() -> None:
            selected_pid_ids = {pid_id for pid_id, var in variables.items() if var.get()}
            if not selected_pid_ids:
                messagebox.showwarning("Регулятор газа", "Выберите хотя бы один PID-параметр.", parent=dialog)
                return

            try:
                device_id = parse_can_id(device_id_var.get())
            except ValueError as error:
                messagebox.showerror("Регулятор газа", str(error), parent=dialog)
                return

            template = build_gas_regulator_template(
                selected_pid_ids=selected_pid_ids,
                device_id=device_id,
                channel=int(channel_var.get()),
                baud_rate=int(baud_var.get()),
                history_seconds=int(history_var.get()),
            )
            self._apply_template(template)
            self.status_var.set(f"Открыт шаблон регулятора газа: {len(template.signals)} сигналов")
            dialog.destroy()

        ttk.Button(buttons, text="Все", command=lambda: set_all(True)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Снять", command=lambda: set_all(False)).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(buttons, text="Открыть", command=apply_gas_regulator).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.focus()

    def save_template(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Сохранить шаблон проекта",
            defaultextension=".json",
            filetypes=(("CAN project JSON", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return

        try:
            template = ProjectTemplate(
                name=Path(path).stem,
                channel=int(self.channel_var.get()),
                baud_rate=int(self.baud_var.get()),
                history_seconds=int(self.history_var.get()),
                signals=list(self.signals),
            )
            template.save(path)
            self.status_var.set(f"Шаблон сохранен: {Path(path).name}")
        except Exception as error:
            messagebox.showerror("Ошибка сохранения шаблона", str(error))

    def show_signal_dialog(self, prefill_id: str = "", prefill_channel: str | None = None) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Сигнал")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        values = {
            "message_id": tk.StringVar(value=prefill_id),
            "name": tk.StringVar(value="Value"),
            "channel": tk.StringVar(value=prefill_channel or self.channel_var.get()),
            "type": tk.StringVar(value="float32"),
            "byte_order": tk.StringVar(value="little_endian"),
            "start_byte": tk.StringVar(value="0"),
            "length": tk.StringVar(value="4"),
            "scale": tk.StringVar(value="1.0"),
            "offset": tk.StringVar(value="0.0"),
            "first_bytes": tk.StringVar(value=""),
            "match_offset": tk.StringVar(value="0"),
            "match_bytes": tk.StringVar(value=""),
        }

        fields = (
            ("CAN ID", "message_id"),
            ("Имя", "name"),
            ("Канал", "channel"),
            ("Тип", "type"),
            ("Порядок байт", "byte_order"),
            ("Стартовый байт", "start_byte"),
            ("Длина", "length"),
            ("Масштаб", "scale"),
            ("Смещение", "offset"),
            ("Первые байты HEX", "first_bytes"),
            ("Match offset", "match_offset"),
            ("Match bytes HEX", "match_bytes"),
        )

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill=tk.BOTH, expand=True)

        for row, (title, key) in enumerate(fields):
            ttk.Label(body, text=title).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            if key == "type":
                widget = ttk.Combobox(body, textvariable=values[key], values=SUPPORTED_TYPES, state="readonly", width=24)
            elif key == "byte_order":
                widget = ttk.Combobox(body, textvariable=values[key], values=SUPPORTED_BYTE_ORDERS, state="readonly", width=24)
            elif key == "channel":
                widget = ttk.Combobox(body, textvariable=values[key], values=("0", "1"), state="readonly", width=24)
            else:
                widget = ttk.Entry(body, textvariable=values[key], width=27)
            widget.grid(row=row, column=1, sticky="ew", pady=3)

        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1), weight=1)

        def add_signal() -> None:
            try:
                signal = SignalDefinition.from_mapping(
                    {
                        "message_id": normalize_can_id(values["message_id"].get()),
                        "name": values["name"].get(),
                        "channel": int(values["channel"].get()),
                        "type": values["type"].get(),
                        "byte_order": values["byte_order"].get(),
                        "start_byte": int(values["start_byte"].get()),
                        "length": int(values["length"].get()),
                        "scale": float(values["scale"].get()),
                        "offset": float(values["offset"].get()),
                        "first_bytes": values["first_bytes"].get(),
                        "match_offset": int(values["match_offset"].get()),
                        "match_bytes": values["match_bytes"].get(),
                    }
                )
                self.add_signal(signal)
                dialog.destroy()
            except Exception as error:
                messagebox.showerror("Ошибка сигнала", str(error), parent=dialog)

        ttk.Button(buttons, text="Добавить", command=add_signal).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        dialog.bind("<Return>", lambda _event: add_signal())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.focus()

    def add_signal_from_selected_id(self) -> None:
        selection = self.ids_list.curselection()
        if not selection:
            self.show_signal_dialog()
            return

        value = self.ids_list.get(selection[0])
        if "_CH" in value:
            message_id, channel = value.split("_CH", 1)
            self.show_signal_dialog(prefill_id=message_id, prefill_channel=channel)
        else:
            self.show_signal_dialog(prefill_id=value)

    def add_signal(self, signal: SignalDefinition) -> None:
        existing_index = next((index for index, item in enumerate(self.signals) if item.key == signal.key), None)
        if existing_index is None:
            self.signals.append(signal)
        else:
            self.signals[existing_index] = signal
        self._rebuild_signal_views()
        self.status_var.set(f"Сигнал добавлен: {signal.label}")

    def remove_selected_signals(self) -> None:
        selected_keys = set(self.signals_tree.selection())
        if not selected_keys:
            return
        self.signals = [signal for signal in self.signals if signal.key not in selected_keys]
        self._rebuild_signal_views()
        self.status_var.set("Сигнал удален")

    def _rebuild_signal_views(self) -> None:
        self.signal_by_key = {signal.key: signal for signal in self.signals}

        for item in self.signals_tree.get_children():
            self.signals_tree.delete(item)

        for signal in self.signals:
            self.signals_tree.insert(
                "",
                tk.END,
                iid=signal.key,
                values=(
                    signal.message_id,
                    signal.name,
                    signal.channel,
                    signal.type,
                    f"{signal.start_byte}:{signal.length}",
                ),
            )

        signal_keys = [signal.key for signal in self.signals]
        active_keys = set(signal_keys)
        for chart_key in list(self.charts):
            if chart_key not in active_keys:
                self.charts.pop(chart_key).destroy()

        if not self.signals:
            self.empty_charts_label.pack(anchor="w", padx=8, pady=8)
            return

        self.empty_charts_label.pack_forget()
        ordered_charts: dict[str, SignalChart] = {}
        for index, signal in enumerate(self.signals):
            chart = self.charts.get(signal.key)
            if chart is None:
                chart = SignalChart(self.charts_frame, signal, CHART_COLORS[index % len(CHART_COLORS)])
            else:
                chart.signal = signal
                chart.color = CHART_COLORS[index % len(CHART_COLORS)]
                chart.title_var.set(signal.label)

            chart.pack_forget()
            chart.pack(fill=tk.X, expand=True, pady=(0, 10))
            ordered_charts[signal.key] = chart

        self.charts = ordered_charts

    def toggle_graph_pause(self) -> None:
        if self.graph_paused:
            self.return_to_live()
            return

        self.graph_paused = True
        self.graph_pause_time = time.time()
        self.pause_graph_button.configure(text="Продолжить")
        self._update_graph_state()

    def return_to_live(self) -> None:
        self.graph_paused = False
        self.graph_pause_time = None
        self.pause_graph_button.configure(text="Пауза")
        self._update_graph_state()

    def clear_graphs(self) -> None:
        for chart in self.charts.values():
            chart.clear()
        self.time_markers.clear()
        self.status_var.set("Графики очищены")
        self._update_graph_state()

    def autoscale_graphs(self) -> None:
        self.status_var.set("Автомасштаб применен")
        self._update_graph_state()
        self._redraw_charts_once()

    def zoom_time_window(self, factor: float) -> None:
        current = max(10, int(self.history_var.get() or 600))
        updated = int(max(10, min(3600, current * factor)))
        self.history_var.set(updated)
        self.status_var.set(f"Окно графиков: {updated} сек")
        self._update_graph_state()
        self._redraw_charts_once()

    def add_time_marker(self) -> None:
        marker_time = self.graph_pause_time if self.graph_paused and self.graph_pause_time is not None else time.time()
        self.time_markers.append(marker_time)
        self.status_var.set(f"Маркер добавлен: {datetime.fromtimestamp(marker_time).strftime('%H:%M:%S')}")
        self._update_graph_state()
        self._redraw_charts_once()

    def clear_time_markers(self) -> None:
        self.time_markers.clear()
        self.status_var.set("Маркеры очищены")
        self._update_graph_state()
        self._redraw_charts_once()

    def _update_graph_state(self) -> None:
        mode = "Пауза" if self.graph_paused else "Live"
        self.graph_state_var.set(f"{mode} | окно {max(10, int(self.history_var.get() or 600))} сек | маркеров: {len(self.time_markers)}")

    def _redraw_charts_once(self) -> None:
        history_seconds = max(10, int(self.history_var.get() or 600))
        now = self.graph_pause_time if self.graph_paused and self.graph_pause_time is not None else time.time()
        for chart in self.charts.values():
            chart.draw(now, history_seconds, self.time_markers)

    def _poll_queues(self) -> None:
        if self._closing:
            return

        self._poll_events()

        processed = 0
        while processed < 2000:
            try:
                can_message, channel = self.message_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_message(can_message, channel)
            processed += 1

        if processed:
            self._update_count_label()

        delay = 1 if not self.message_queue.empty() else 30
        if not self._closing:
            self.root.after(delay, self._poll_queues)

    def _poll_events(self) -> None:
        if self._closing:
            return

        while True:
            try:
                kind, message = self.event_queue.get_nowait()
            except queue.Empty:
                break

            self.status_var.set(message)
            if kind == "connected":
                self.is_connected = True
                self.connect_button.configure(state=tk.DISABLED)
                self.disconnect_button.configure(state=tk.NORMAL)
            elif kind == "disconnected":
                self.is_connected = False
                self.connect_button.configure(state=tk.NORMAL)
                self.disconnect_button.configure(state=tk.DISABLED)
                self.reader = None
            elif kind == "error":
                self.is_connected = False
                self.connect_button.configure(state=tk.NORMAL)
                self.disconnect_button.configure(state=tk.DISABLED)
                messagebox.showerror("CAN", message)

    def _handle_message(self, can_message: Any, channel: int) -> None:
        self.session_messages += 1

        received_at = getattr(can_message, "receive_time", None)
        timestamp = received_at.timestamp() if isinstance(received_at, datetime) else time.time()

        parsed = parse_message_signals(can_message, channel, self.signals)
        self.parsed_points += len(parsed)

        if self.logger is not None:
            self.logger.log_message(can_message, channel, parsed)

        self._update_can_id_stats(can_message, channel, timestamp)

        for signal_key, value in parsed.items():
            chart = self.charts.get(signal_key)
            if chart is not None:
                chart.append(timestamp, value)

        self._remember_discovered_id(can_message, channel)
        self._remember_message_row(can_message, channel, parsed)

    def _update_can_id_stats(self, can_message: Any, channel: int, timestamp: float) -> None:
        try:
            can_id = get_message_id_string(can_message)
        except Exception:
            can_id = str(getattr(can_message, "id", ""))

        key = f"{can_id}_CH{channel}"
        data_hex = can_message.get_data_hex() if hasattr(can_message, "get_data_hex") else " ".join(
            f"{byte:02X}" for byte in bytes(getattr(can_message, "data", b""))
        )
        length = getattr(can_message, "length", len(bytes(getattr(can_message, "data", b""))))
        received_at = getattr(can_message, "receive_time", None)
        if not isinstance(received_at, datetime):
            received_at = datetime.fromtimestamp(timestamp)

        stats = self.can_id_stats.get(key)
        if stats is None:
            stats = {
                "can_id": can_id,
                "channel": channel,
                "count": 0,
                "first_timestamp": timestamp,
                "last_timestamp": timestamp,
                "last_wall_time": received_at,
                "length": length,
                "sample": data_hex,
            }
            self.can_id_stats[key] = stats

        stats["count"] += 1
        stats["last_timestamp"] = timestamp
        stats["last_wall_time"] = received_at
        stats["length"] = length
        stats["sample"] = data_hex
        self._stats_table_dirty = True

    def _remember_discovered_id(self, can_message: Any, channel: int) -> None:
        try:
            value = f"{get_message_id_string(can_message)}_CH{channel}"
        except Exception:
            return

        if value in self.discovered_ids:
            return
        self.discovered_ids.add(value)
        self.ids_list.insert(tk.END, value)

    def _remember_message_row(self, can_message: Any, channel: int, parsed: dict[str, float]) -> None:
        received_at = getattr(can_message, "receive_time", None)
        if isinstance(received_at, datetime):
            time_text = received_at.strftime("%H:%M:%S.%f")[:-3]
        else:
            time_text = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        data_hex = can_message.get_data_hex() if hasattr(can_message, "get_data_hex") else ""
        length = getattr(can_message, "length", "")

        try:
            can_id = get_message_id_string(can_message)
        except Exception:
            can_id = getattr(can_message, "id", "")

        parsed_text = ", ".join(
            f"{self.signal_by_key.get(key).name if key in self.signal_by_key else key}={value:.5g}"
            for key, value in parsed.items()
        )

        self.recent_rows.appendleft((self.session_messages, time_text, channel, can_id, length, data_hex, parsed_text))
        self._message_table_dirty = True

    def _refresh_message_table(self) -> None:
        if self._closing:
            return

        if self._message_table_dirty:
            for item in self.messages_tree.get_children():
                self.messages_tree.delete(item)
            for row in self.recent_rows:
                self.messages_tree.insert("", tk.END, values=row)
            self._message_table_dirty = False

        if self._stats_table_dirty:
            self._refresh_stats_table()
            self._stats_table_dirty = False

        if not self._closing:
            self.root.after(250, self._refresh_message_table)

    def _refresh_stats_table(self) -> None:
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)

        rows = []
        for stats in self.can_id_stats.values():
            count = int(stats["count"])
            duration = max(float(stats["last_timestamp"]) - float(stats["first_timestamp"]), 1e-9)
            hz = count / duration if count > 1 else 0.0
            last_wall_time = stats["last_wall_time"]
            if isinstance(last_wall_time, datetime):
                last_text = last_wall_time.strftime("%H:%M:%S.%f")[:-3]
            else:
                last_text = ""
            rows.append(
                (
                    count,
                    (
                        stats["can_id"],
                        stats["channel"],
                        count,
                        f"{hz:.2f}",
                        last_text,
                        stats["length"],
                        stats["sample"],
                    ),
                )
            )

        for _count, values in sorted(rows, key=lambda item: item[0], reverse=True):
            self.stats_tree.insert("", tk.END, values=values)

    def _redraw_charts(self) -> None:
        if self._closing:
            return

        history_seconds = max(10, int(self.history_var.get() or 600))
        now = self.graph_pause_time if self.graph_paused and self.graph_pause_time is not None else time.time()
        for chart in self.charts.values():
            chart.draw(now, history_seconds, self.time_markers)
        self._update_graph_state()
        if not self._closing:
            self.root.after(120, self._redraw_charts)

    def _clear_session_views(self) -> None:
        self.session_messages = 0
        self.parsed_points = 0
        self.recent_rows.clear()
        self.can_id_stats.clear()
        self.time_markers.clear()
        self._message_table_dirty = True
        self._stats_table_dirty = True
        for chart in self.charts.values():
            chart.clear()
        self._update_graph_state()
        self._update_count_label()

    def _update_count_label(self) -> None:
        queue_size = self.message_queue.qsize()
        dropped = self.logger.dropped_rows if self.logger else 0
        self.count_var.set(
            f"Сообщений: {self.session_messages} | точек: {self.parsed_points} | очередь: {queue_size} | CSV drop: {dropped}"
        )

    def _update_session_label(self) -> None:
        if not self.logger or not self.logger.session_dir:
            self.session_var.set("Сессия: не выбрана")
            return
        self.session_var.set(f"Сессия: {self.logger.session_dir}")

    def close(self) -> None:
        if self._closing:
            return

        self._closing = True

        if self.reader is not None:
            self.reader.stop()
            self.reader.join(timeout=2)
            self.reader = None

        if self.logger is not None:
            self.logger.close()
            self.logger = None

        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main() -> None:
    app: CanMonitorApp | None = None
    try:
        root = tk.Tk()
        app = CanMonitorApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        if app is not None:
            try:
                app.close()
            except KeyboardInterrupt:
                pass
    finally:
        if app is not None:
            try:
                app.close()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()

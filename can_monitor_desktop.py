from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import math
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

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
from can_events import DecodedCanEvent, load_can_event_decoder
from can_id_catalog import load_can_id_catalog
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

MAX_RENDERED_CHART_POINTS = 1200


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
    def __init__(
        self,
        parent: tk.Widget,
        signal: SignalDefinition,
        color: str,
        redraw_callback: Callable[[], None] | None = None,
    ):
        super().__init__(parent, padding=(8, 6))
        self.signal = signal
        self.color = color
        self.redraw_callback = redraw_callback
        self.points: deque[tuple[float, float]] = deque(maxlen=50000)
        self.rendered_points: list[tuple[float, float, float, float]] = []
        self.plot_bounds: tuple[int, int, int, int] | None = None
        self.hover_position: tuple[int, int] | None = None

        self.title_var = tk.StringVar(value=signal.label)
        self.value_var = tk.StringVar(value="нет данных")
        self.zero_y_var = tk.BooleanVar(value=False)

        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self.title_var, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.value_var).pack(side=tk.RIGHT)
        ttk.Checkbutton(header, text="Y от 0", variable=self.zero_y_var, command=self._request_redraw).pack(
            side=tk.RIGHT,
            padx=(0, 12),
        )

        self.canvas = tk.Canvas(self, height=170, background="#ffffff", highlightthickness=1, highlightbackground="#d6dbe1")
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda _event: self._request_redraw())
        self.canvas.bind("<Motion>", self._on_cursor_motion)
        self.canvas.bind("<Leave>", self._on_cursor_leave)

    def append(self, timestamp: float, value: float) -> None:
        self.points.append((timestamp, value))
        self.value_var.set(f"{value:.6g}")

    def clear(self) -> None:
        self.points.clear()
        self.rendered_points.clear()
        self.plot_bounds = None
        self.hover_position = None
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
        self.rendered_points = []
        self.plot_bounds = (left, right, top, bottom)

        canvas.create_rectangle(0, 0, width, height, fill="#ffffff", outline="")
        for index in range(5):
            y = top + (bottom - top) * index / 4
            canvas.create_line(left, y, right, y, fill="#edf0f3")

        recent = [
            (timestamp, value)
            for timestamp, value in self.points
            if start_time <= timestamp <= now
        ]

        if not recent:
            canvas.create_text(width / 2, height / 2, text="Нет данных", fill="#6b7280", font=("Segoe UI", 10))
            canvas.create_line(left, bottom, right, bottom, fill="#9ca3af")
            canvas.create_line(left, top, left, bottom, fill="#9ca3af")
            self._draw_markers(canvas, markers, start_time, span, left, right, top, bottom)
            return

        finite_values = [value for _, value in recent if math.isfinite(value)]
        if not finite_values:
            canvas.create_text(width / 2, height / 2, text="Нет числовых данных", fill="#6b7280", font=("Segoe UI", 10))
            canvas.create_line(left, bottom, right, bottom, fill="#9ca3af")
            canvas.create_line(left, top, left, bottom, fill="#9ca3af")
            self._draw_markers(canvas, markers, start_time, span, left, right, top, bottom)
            return

        min_value, max_value = self._value_range(finite_values, zero_based=self.zero_y_var.get())
        recent = [(timestamp, value) for timestamp, value in recent if math.isfinite(value)]
        recent = self._downsample_points(recent, MAX_RENDERED_CHART_POINTS)

        value_span = max(max_value - min_value, 1e-9)

        coords: list[float] = []
        for timestamp, value in recent:
            x = left + (timestamp - start_time) / span * (right - left)
            y = bottom - (value - min_value) / value_span * (bottom - top)
            bounded_x = max(left, min(right, x))
            bounded_y = max(top, min(bottom, y))
            coords.extend((bounded_x, bounded_y))
            self.rendered_points.append((timestamp, value, bounded_x, bounded_y))

        canvas.create_line(left, bottom, right, bottom, fill="#9ca3af")
        canvas.create_line(left, top, left, bottom, fill="#9ca3af")
        canvas.create_text(8, top + 2, anchor="nw", text=f"{max_value:.4g}", fill="#475569", font=("Segoe UI", 8))
        canvas.create_text(8, bottom - 12, anchor="nw", text=f"{min_value:.4g}", fill="#475569", font=("Segoe UI", 8))
        canvas.create_text(left, height - 18, anchor="nw", text=datetime.fromtimestamp(start_time).strftime("%H:%M:%S"), fill="#64748b", font=("Segoe UI", 8))
        canvas.create_text(right, height - 18, anchor="ne", text=datetime.fromtimestamp(now).strftime("%H:%M:%S"), fill="#64748b", font=("Segoe UI", 8))
        self._draw_markers(canvas, markers, start_time, span, left, right, top, bottom)

        if len(coords) >= 4:
            canvas.create_line(*coords, fill=self.color, width=2, smooth=False)
        else:
            x, y = coords
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=self.color, outline=self.color)

        self._draw_cursor()

    def _value_range(self, values: list[float], zero_based: bool = False) -> tuple[float, float]:
        min_value = min(values)
        max_value = max(values)

        if zero_based:
            if min_value >= 0:
                min_value = 0.0
                if max_value == 0:
                    return 0.0, 1.0
                return min_value, max_value + (max_value - min_value) * 0.08

            if max_value <= 0:
                max_value = 0.0
                return min_value - (max_value - min_value) * 0.08, max_value

        if min_value == max_value:
            padding = 1.0 if min_value == 0 else abs(min_value) * 0.05
        else:
            padding = (max_value - min_value) * 0.08

        return min_value - padding, max_value + padding

    def _request_redraw(self) -> None:
        if self.redraw_callback is not None:
            self.redraw_callback()
        else:
            self.draw(time.time(), 600, [])

    def _downsample_points(
        self,
        points: list[tuple[float, float]],
        max_points: int,
    ) -> list[tuple[float, float]]:
        if len(points) <= max_points:
            return points

        bucket_count = max(1, max_points // 2)
        step = max(1, math.ceil(len(points) / bucket_count))
        selected: dict[int, tuple[float, float]] = {}

        for start in range(0, len(points), step):
            bucket = points[start : start + step]
            if not bucket:
                continue
            min_offset, min_point = min(enumerate(bucket), key=lambda item: item[1][1])
            max_offset, max_point = max(enumerate(bucket), key=lambda item: item[1][1])
            selected[start + min_offset] = min_point
            selected[start + max_offset] = max_point

        return [selected[index] for index in sorted(selected)]

    def _on_cursor_motion(self, event: tk.Event) -> None:
        self.hover_position = (int(event.x), int(event.y))
        self._draw_cursor()

    def _on_cursor_leave(self, _event: tk.Event) -> None:
        self.hover_position = None
        self.canvas.delete("cursor")

    def _nearest_cursor_point(self) -> tuple[float, float, float, float] | None:
        if self.hover_position is None or self.plot_bounds is None or not self.rendered_points:
            return None

        hover_x, hover_y = self.hover_position
        left, right, top, bottom = self.plot_bounds
        if hover_x < left or hover_x > right or hover_y < top or hover_y > bottom:
            return None

        return min(self.rendered_points, key=lambda point: abs(point[2] - hover_x))

    def _draw_cursor(self) -> None:
        canvas = self.canvas
        canvas.delete("cursor")

        nearest = self._nearest_cursor_point()
        if nearest is None or self.plot_bounds is None:
            return

        timestamp, value, x, y = nearest
        left, right, top, bottom = self.plot_bounds
        time_text = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]
        label = f"{time_text}\n{value:.6g}"

        canvas.create_line(x, top, x, bottom, fill="#334155", dash=(3, 2), width=1, tags="cursor")
        canvas.create_line(left, y, right, y, fill="#cbd5e1", dash=(2, 2), width=1, tags="cursor")
        canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#ffffff", outline=self.color, width=2, tags="cursor")

        anchor = "nw" if x < (left + right) / 2 else "ne"
        text_x = x + 8 if anchor == "nw" else x - 8
        text_id = canvas.create_text(
            text_x,
            top + 6,
            anchor=anchor,
            text=label,
            fill="#0f172a",
            font=("Segoe UI", 9),
            tags="cursor",
        )
        bbox = canvas.bbox(text_id)
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            background_id = canvas.create_rectangle(
                x1 - 6,
                y1 - 4,
                x2 + 6,
                y2 + 4,
                fill="#f8fafc",
                outline="#94a3b8",
                tags="cursor",
            )
            canvas.tag_lower(background_id, text_id)

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
        self.discovered_id_display_values: dict[str, str] = {}
        self.can_id_catalog = load_can_id_catalog()
        self.can_event_decoder = load_can_event_decoder()
        self.recent_rows: deque[tuple[Any, ...]] = deque(maxlen=200)
        self.event_rows: deque[tuple[tuple[Any, ...], str]] = deque(maxlen=1000)
        self.last_event_values: dict[str, str] = {}

        self.session_messages = 0
        self.parsed_points = 0
        self.decoded_events = 0
        self.is_connected = False
        self._message_table_dirty = False
        self._stats_table_dirty = False
        self._event_table_dirty = False
        self._closing = False
        self.graph_paused = False
        self.graph_pause_time: float | None = None
        self.graph_view_offset_seconds = 0.0
        self.time_markers: list[float] = []
        self.can_id_stats: dict[str, dict[str, Any]] = {}

        self.channel_var = tk.StringVar(value="1")
        self.baud_var = tk.StringVar(value="500000")
        self.history_var = tk.IntVar(value=600)
        self.graph_state_var = tk.StringVar(value="Live")
        self.status_var = tk.StringVar(value="Выберите папку для сессий")
        self.session_var = tk.StringVar(value="Сессия: не выбрана")
        self.count_var = tk.StringVar(value="Сообщений: 0")
        self.event_log_var = tk.StringVar(value="Событий: 0")

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
        events_tab = ttk.Frame(notebook)
        stats_tab = ttk.Frame(notebook)
        notebook.add(graphs_tab, text="Графики")
        notebook.add(messages_tab, text="Сообщения")
        notebook.add(events_tab, text="Журнал/ошибки")
        notebook.add(stats_tab, text="Статистика ID")

        self._build_graphs_tab(graphs_tab)
        self._build_messages_tab(messages_tab)
        self._build_events_tab(events_tab)
        self._build_stats_tab(stats_tab)

    def _build_graphs_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        graph_toolbar = ttk.Frame(parent, padding=(0, 0, 0, 8))
        graph_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        graph_toolbar.columnconfigure(11, weight=1)

        self.pause_graph_button = ttk.Button(graph_toolbar, text="Пауза", command=self.toggle_graph_pause)
        self.pause_graph_button.grid(row=0, column=0, padx=(0, 4))
        ttk.Button(graph_toolbar, text="Очистить графики", command=self.clear_graphs).grid(row=0, column=1, padx=4)
        ttk.Button(graph_toolbar, text="Автомасштаб", command=self.autoscale_graphs).grid(row=0, column=2, padx=4)
        ttk.Button(graph_toolbar, text="Масштаб +", command=lambda: self.zoom_time_window(0.5)).grid(row=0, column=3, padx=4)
        ttk.Button(graph_toolbar, text="Масштаб -", command=lambda: self.zoom_time_window(2.0)).grid(row=0, column=4, padx=4)
        ttk.Button(graph_toolbar, text="< Назад", command=lambda: self.pan_graph_time(-1)).grid(row=0, column=5, padx=4)
        ttk.Button(graph_toolbar, text="Вперед >", command=lambda: self.pan_graph_time(1)).grid(row=0, column=6, padx=4)
        ttk.Button(graph_toolbar, text="Вернуться к live", command=self.return_to_live).grid(row=0, column=7, padx=4)
        ttk.Button(graph_toolbar, text="Маркер", command=self.add_time_marker).grid(row=0, column=8, padx=4)
        ttk.Button(graph_toolbar, text="Стереть маркеры", command=self.clear_time_markers).grid(row=0, column=9, padx=4)
        ttk.Label(graph_toolbar, textvariable=self.graph_state_var).grid(row=0, column=11, sticky="e")

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

    def _build_events_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(parent, padding=(0, 0, 0, 8))
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Button(toolbar, text="Очистить", command=self.clear_event_log).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.event_log_var).grid(row=0, column=1, sticky="e")

        columns = ("time", "level", "device", "event", "details", "ch", "id", "data")
        self.events_tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, title, width in (
            ("time", "Время", 150),
            ("level", "Уровень", 80),
            ("device", "Устройство", 100),
            ("event", "Событие", 170),
            ("details", "Детали", 420),
            ("ch", "CH", 45),
            ("id", "CAN ID", 90),
            ("data", "Данные", 220),
        ):
            self.events_tree.heading(column, text=title)
            self.events_tree.column(column, width=width, anchor=tk.W, stretch=column in ("details", "data"))

        self.events_tree.tag_configure("error", foreground="#b91c1c")
        self.events_tree.tag_configure("warning", foreground="#a16207")
        self.events_tree.tag_configure("info", foreground="#0f172a")

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.events_tree.yview)
        self.events_tree.configure(yscrollcommand=scrollbar.set)
        self.events_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

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
        selected_channel = int(self.channel_var.get())
        for signal in self.signals:
            signal.channel = selected_channel
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
        controls.columnconfigure(4, weight=1)

        ttk.Label(controls, text="Скорость").grid(row=0, column=0, padx=(0, 4))
        ttk.Combobox(controls, textvariable=baud_var, values=BAUD_RATES, state="readonly", width=10).grid(
            row=0,
            column=1,
            padx=(0, 10),
        )
        ttk.Label(controls, text="История, сек").grid(row=0, column=2, padx=(0, 4))
        ttk.Spinbox(controls, from_=10, to=3600, increment=10, textvariable=history_var, width=7).grid(
            row=0,
            column=3,
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
                channel=int(self.channel_var.get()),
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
        ttk.Label(params, text="Скорость").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=3)
        ttk.Combobox(params, textvariable=baud_var, values=BAUD_RATES, state="readonly", width=10).grid(
            row=0,
            column=3,
            sticky="w",
            padx=(0, 12),
            pady=3,
        )
        ttk.Label(params, text="История, сек").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=3)
        ttk.Spinbox(params, from_=10, to=3600, increment=10, textvariable=history_var, width=7).grid(
            row=1,
            column=1,
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
                channel=int(self.channel_var.get()),
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
                baud_rate=int(self.baud_var.get()),
                history_seconds=int(self.history_var.get()),
                signals=list(self.signals),
            )
            template.save(path)
            self.status_var.set(f"Шаблон сохранен: {Path(path).name}")
        except Exception as error:
            messagebox.showerror("Ошибка сохранения шаблона", str(error))

    def show_signal_dialog(self, prefill_id: str = "") -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Сигнал")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        values = {
            "message_id": tk.StringVar(value=prefill_id),
            "name": tk.StringVar(value="Value"),
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
                        "channel": int(self.channel_var.get()),
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
        value = self.discovered_id_display_values.get(value, value)
        if "_CH" in value:
            message_id, _channel = value.split("_CH", 1)
            self.show_signal_dialog(prefill_id=message_id)
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
                chart = SignalChart(
                    self.charts_frame,
                    signal,
                    CHART_COLORS[index % len(CHART_COLORS)],
                    redraw_callback=self._redraw_charts_once,
                )
            else:
                chart.signal = signal
                chart.color = CHART_COLORS[index % len(CHART_COLORS)]
                chart.redraw_callback = self._redraw_charts_once
                chart.title_var.set(signal.label)

            chart.pack_forget()
            chart.pack(fill=tk.X, expand=True, pady=(0, 10))
            ordered_charts[signal.key] = chart

        self.charts = ordered_charts

    def toggle_graph_pause(self) -> None:
        if self.graph_paused:
            self.graph_paused = False
            self.graph_pause_time = None
            self.pause_graph_button.configure(text="Пауза")
            self._update_graph_state()
            self._redraw_charts_once()
            return

        self.graph_paused = True
        self.graph_pause_time = self._graph_view_end_time()
        self.graph_view_offset_seconds = 0.0
        self.pause_graph_button.configure(text="Продолжить")
        self._update_graph_state()

    def return_to_live(self) -> None:
        self.graph_view_offset_seconds = 0.0
        self.graph_paused = False
        self.graph_pause_time = None
        self.pause_graph_button.configure(text="Пауза")
        self._update_graph_state()
        self._redraw_charts_once()

    def clear_graphs(self) -> None:
        for chart in self.charts.values():
            chart.clear()
        self.time_markers.clear()
        self.status_var.set("Графики очищены")
        self._update_graph_state()

    def clear_event_log(self) -> None:
        self.event_rows.clear()
        self.last_event_values.clear()
        self.decoded_events = 0
        self.event_log_var.set("Событий: 0")
        self._event_table_dirty = True
        self.status_var.set("Журнал событий очищен")

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

    def pan_graph_time(self, direction: int) -> None:
        history_seconds = self._graph_history_seconds()
        shift = max(1.0, history_seconds * 0.5)
        target_offset = max(0.0, self.graph_view_offset_seconds - shift if direction > 0 else self.graph_view_offset_seconds + shift)
        base_end = self._graph_base_end_time()
        oldest = self._oldest_chart_timestamp()
        if oldest is not None:
            min_end = min(base_end, oldest + history_seconds)
            max_offset = max(0.0, base_end - min_end)
            target_offset = min(target_offset, max_offset)

        self.graph_view_offset_seconds = target_offset
        if self.graph_view_offset_seconds <= 0:
            self.graph_view_offset_seconds = 0.0
            self.status_var.set("Окно графиков у live")
        else:
            self.status_var.set(f"Окно графиков: -{self._format_seconds(self.graph_view_offset_seconds)} от live")
        self._update_graph_state()
        self._redraw_charts_once()

    def add_time_marker(self) -> None:
        marker_time = self._graph_view_end_time()
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
        history_seconds = self._graph_history_seconds()
        if self.graph_view_offset_seconds > 0:
            mode = f"Просмотр -{self._format_seconds(self.graph_view_offset_seconds)}"
        elif self.graph_paused and self.graph_pause_time is not None:
            mode = f"Пауза до {datetime.fromtimestamp(self.graph_pause_time).strftime('%H:%M:%S')}"
        else:
            mode = "Live"
        self.graph_state_var.set(f"{mode} | окно {history_seconds} сек | маркеров: {len(self.time_markers)}")

    def _redraw_charts_once(self) -> None:
        history_seconds = self._graph_history_seconds()
        now = self._graph_view_end_time()
        for chart in self.charts.values():
            chart.draw(now, history_seconds, self.time_markers)

    def _graph_history_seconds(self) -> int:
        return max(10, int(self.history_var.get() or 600))

    def _graph_base_end_time(self) -> float:
        if self.graph_paused and self.graph_pause_time is not None:
            return self.graph_pause_time
        return time.time()

    def _graph_view_end_time(self) -> float:
        return self._graph_base_end_time() - self.graph_view_offset_seconds

    def _oldest_chart_timestamp(self) -> float | None:
        oldest_values = [chart.points[0][0] for chart in self.charts.values() if chart.points]
        if not oldest_values:
            return None
        return min(oldest_values)

    def _format_seconds(self, seconds: float) -> str:
        total_seconds = max(0, int(round(seconds)))
        minutes, second = divmod(total_seconds, 60)
        hours, minute = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minute:02d}:{second:02d}"
        if minute:
            return f"{minute}:{second:02d}"
        return f"{second} c"

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
        self._remember_can_events(can_message, channel, timestamp)

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

    def _remember_can_events(self, can_message: Any, channel: int, timestamp: float) -> None:
        for decoded_event in self.can_event_decoder.decode(can_message, channel):
            if not self._should_log_can_event(decoded_event):
                continue
            self._remember_event_row(decoded_event, timestamp)

    def _should_log_can_event(self, decoded_event: DecodedCanEvent) -> bool:
        if decoded_event.dedupe != "value":
            return True

        previous_value = self.last_event_values.get(decoded_event.dedupe_key)
        if previous_value == decoded_event.dedupe_value:
            return False

        self.last_event_values[decoded_event.dedupe_key] = decoded_event.dedupe_value
        return True

    def _remember_event_row(self, decoded_event: DecodedCanEvent, timestamp: float) -> None:
        time_text = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]
        level_text = self._event_severity_label(decoded_event.severity)
        values = (
            time_text,
            level_text,
            decoded_event.device,
            decoded_event.title,
            decoded_event.details,
            decoded_event.channel,
            decoded_event.can_id,
            decoded_event.data_hex,
        )
        self.event_rows.appendleft((values, decoded_event.severity))
        self.decoded_events += 1
        self.event_log_var.set(f"Событий: {self.decoded_events}")
        self._event_table_dirty = True

    @staticmethod
    def _event_severity_label(severity: str) -> str:
        return {
            "error": "Ошибка",
            "warning": "Внимание",
            "info": "Инфо",
        }.get(severity, severity)

    def _remember_discovered_id(self, can_message: Any, channel: int) -> None:
        try:
            can_id = get_message_id_string(can_message)
            value = f"{can_id}_CH{channel}"
        except Exception:
            return

        if value in self.discovered_ids:
            return
        self.discovered_ids.add(value)
        label = self.can_id_catalog.describe(can_id, channel)
        display_value = f"{value} - {label}" if label else value
        self.discovered_id_display_values[display_value] = value
        self._refresh_discovered_ids_list()

    def _refresh_discovered_ids_list(self) -> None:
        selected_display = None
        selection = self.ids_list.curselection()
        if selection:
            selected_display = self.ids_list.get(selection[0])

        ordered_values = sorted(
            self.discovered_id_display_values.items(),
            key=lambda item: self._discovered_id_sort_key(item[1], item[0]),
        )

        self.ids_list.delete(0, tk.END)
        for index, (display_value, _raw_value) in enumerate(ordered_values):
            self.ids_list.insert(tk.END, display_value)
            if display_value == selected_display:
                self.ids_list.selection_set(index)

    @staticmethod
    def _discovered_id_sort_key(raw_value: str, display_value: str) -> tuple[int, int, str]:
        message_id, channel = raw_value, -1
        if "_CH" in raw_value:
            message_id, channel_text = raw_value.split("_CH", 1)
            try:
                channel = int(channel_text)
            except ValueError:
                channel = -1

        try:
            numeric_id = parse_can_id(message_id)
        except Exception:
            numeric_id = 0xFFFFFFFF

        return numeric_id, channel, display_value

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

        if self._event_table_dirty:
            self._refresh_event_table()
            self._event_table_dirty = False

        if not self._closing:
            self.root.after(250, self._refresh_message_table)

    def _refresh_event_table(self) -> None:
        for item in self.events_tree.get_children():
            self.events_tree.delete(item)

        for values, severity in self.event_rows:
            self.events_tree.insert("", tk.END, values=values, tags=(severity,))

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

        history_seconds = self._graph_history_seconds()
        now = self._graph_view_end_time()
        for chart in self.charts.values():
            chart.draw(now, history_seconds, self.time_markers)
        self._update_graph_state()
        if not self._closing:
            self.root.after(120, self._redraw_charts)

    def _clear_session_views(self) -> None:
        self.session_messages = 0
        self.parsed_points = 0
        self.recent_rows.clear()
        self.event_rows.clear()
        self.last_event_values.clear()
        self.can_id_stats.clear()
        self.discovered_ids.clear()
        self.discovered_id_display_values.clear()
        self.ids_list.delete(0, tk.END)
        self.time_markers.clear()
        self.graph_view_offset_seconds = 0.0
        self.graph_paused = False
        self.graph_pause_time = None
        self.pause_graph_button.configure(text="Пауза")
        self._message_table_dirty = True
        self._stats_table_dirty = True
        self._event_table_dirty = True
        self.decoded_events = 0
        self.event_log_var.set("Событий: 0")
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
        self._update_session_label()

    def _update_session_label(self) -> None:
        if not self.logger or not self.logger.session_dir:
            self.session_var.set("Сессия: не выбрана")
            return
        csv_name = self.logger.csv_path.name if self.logger.csv_path else "can_messages.csv"
        self.session_var.set(f"Сессия: {self.logger.session_dir} | CSV: {csv_name}")

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

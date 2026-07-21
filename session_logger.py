from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import queue
import threading
from typing import Any


class CsvSessionLogger:
    HEADER = [
        "Record_Number",
        "Session_Elapsed_s",
        "Wall_Time",
        "Channel",
        "CAN_ID_Dec",
        "CAN_ID_Hex",
        "Frame_Type",
        "RTR_Status",
        "Length",
        "Data_Hex",
        "Byte_0",
        "Byte_1",
        "Byte_2",
        "Byte_3",
        "Byte_4",
        "Byte_5",
        "Byte_6",
        "Byte_7",
        "Timestamp_Raw",
        "Parsed_Signals",
    ]

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

        self.session_dir: Path | None = None
        self.csv_path: Path | None = None
        self.started_at: datetime | None = None
        self.dropped_rows = 0

        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=50000)
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

        self.start_new_session()

    def set_root_dir(self, root_dir: str | Path) -> Path:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        return self.start_new_session()

    def start_new_session(self) -> Path:
        started_at = datetime.now()
        session_dir = self._make_session_dir(started_at)
        done = threading.Event()
        result: dict[str, Any] = {}

        self._commands.put(("rotate", (session_dir, started_at, done, result)))
        done.wait(timeout=10)

        if result.get("error"):
            raise RuntimeError(result["error"])

        with self._state_lock:
            self.session_dir = session_dir
            self.csv_path = session_dir / "can_messages.csv"
            self.started_at = started_at

        return session_dir

    def log_message(self, can_message: Any, channel: int, parsed_signals: dict[str, float]) -> None:
        payload = self._snapshot_message(can_message, channel, parsed_signals)
        try:
            self._commands.put_nowait(("message", payload))
        except queue.Full:
            self.dropped_rows += 1

    def close(self) -> None:
        done = threading.Event()
        self._commands.put(("stop", done))
        done.wait(timeout=10)
        self._thread.join(timeout=2)

    def _make_session_dir(self, started_at: datetime) -> Path:
        base_name = started_at.strftime("%Y%m%d_%H%M%S")
        candidate = self.root_dir / base_name
        index = 1
        while candidate.exists():
            index += 1
            candidate = self.root_dir / f"{base_name}_{index:02d}"
        return candidate

    def _writer_loop(self) -> None:
        csv_file = None
        writer = None
        session_started_at: datetime | None = None
        record_number = 0
        pending_flush = 0

        while True:
            try:
                command, payload = self._commands.get(timeout=0.5)
            except queue.Empty:
                if csv_file and pending_flush:
                    csv_file.flush()
                    pending_flush = 0
                continue

            if command == "rotate":
                session_dir, started_at, done, result = payload
                try:
                    if csv_file:
                        csv_file.flush()
                        csv_file.close()

                    session_dir.mkdir(parents=True, exist_ok=True)
                    csv_file = (session_dir / "can_messages.csv").open(
                        "w",
                        newline="",
                        encoding="utf-8-sig",
                    )
                    writer = csv.writer(csv_file, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(self.HEADER)
                    csv_file.flush()
                    session_started_at = started_at
                    record_number = 0
                    pending_flush = 0
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    done.set()

            elif command == "message":
                if not writer or not session_started_at:
                    continue

                record_number += 1
                row = self._row_from_payload(record_number, session_started_at, payload)
                writer.writerow(row)
                pending_flush += 1

                if pending_flush >= 100:
                    csv_file.flush()
                    pending_flush = 0

            elif command == "stop":
                done = payload
                if csv_file:
                    csv_file.flush()
                    csv_file.close()
                done.set()
                return

    def _snapshot_message(
        self,
        can_message: Any,
        channel: int,
        parsed_signals: dict[str, float],
    ) -> dict[str, Any]:
        data = list(bytes(getattr(can_message, "data", b"")))
        received_at = getattr(can_message, "receive_time", None)
        if not isinstance(received_at, datetime):
            received_at = datetime.now()

        can_id = int(getattr(can_message, "id", 0))
        if hasattr(can_message, "get_id_string"):
            can_id_hex = can_message.get_id_string()
        else:
            can_id_hex = f"0x{can_id:X}"

        frame_type = can_message.get_frame_type() if hasattr(can_message, "get_frame_type") else "STD"
        rtr_status = can_message.get_rtr_status() if hasattr(can_message, "get_rtr_status") else "DATA"
        data_hex = can_message.get_data_hex() if hasattr(can_message, "get_data_hex") else " ".join(f"{b:02X}" for b in data)

        return {
            "received_at": received_at,
            "channel": channel,
            "can_id": can_id,
            "can_id_hex": can_id_hex,
            "frame_type": frame_type,
            "rtr_status": rtr_status,
            "length": int(getattr(can_message, "length", len(data))),
            "data_hex": data_hex,
            "data": data,
            "timestamp_raw": getattr(can_message, "timestamp", ""),
            "parsed_signals": dict(parsed_signals),
        }

    def _row_from_payload(
        self,
        record_number: int,
        session_started_at: datetime,
        payload: dict[str, Any],
    ) -> list[Any]:
        received_at = payload["received_at"]
        elapsed = max(0.0, (received_at - session_started_at).total_seconds())
        data = list(payload["data"])
        byte_cells = [f"{data[index]:02X}" if index < len(data) else "" for index in range(8)]
        parsed = "; ".join(
            f"{name}={value:.6g}" for name, value in sorted(payload["parsed_signals"].items())
        )

        return [
            record_number,
            f"{elapsed:.6f}",
            received_at.isoformat(timespec="milliseconds"),
            payload["channel"],
            payload["can_id"],
            payload["can_id_hex"],
            payload["frame_type"],
            payload["rtr_status"],
            payload["length"],
            payload["data_hex"],
            *byte_cells,
            payload["timestamp_raw"],
            parsed,
        ]

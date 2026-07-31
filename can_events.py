from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import struct
from typing import Any

from can_signal import get_message_id_string, normalize_can_id


EVENT_CATALOG_PATH = Path(__file__).resolve().parent / "can_event_catalog.json"


@dataclass(frozen=True)
class DecodedCanEvent:
    event_key: str
    device: str
    title: str
    details: str
    category: str
    severity: str
    source_name: str
    can_id: str
    channel: int
    data_hex: str
    dedupe: str
    dedupe_key: str
    dedupe_value: str


class CanEventDecoder:
    def __init__(self, catalog: dict[str, Any]):
        self.catalog = catalog
        self.value_maps = {
            str(name): {str(key): str(value) for key, value in values.items()}
            for name, values in dict(catalog.get("value_maps") or {}).items()
            if isinstance(values, dict)
        }
        self._events_by_id_code: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._load_events(catalog.get("events") or [])

    @classmethod
    def from_file(cls, path: str | Path = EVENT_CATALOG_PATH) -> "CanEventDecoder":
        catalog_path = Path(path)
        if not catalog_path.exists():
            return cls({"events": [], "value_maps": {}})

        with catalog_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, dict):
            raise ValueError(f"Unsupported CAN event catalog format: {catalog_path}")
        return cls(payload)

    def decode(self, can_message: Any, channel: int) -> list[DecodedCanEvent]:
        data = bytes(getattr(can_message, "data", b""))
        if len(data) < 2:
            return []

        try:
            can_id = get_message_id_string(can_message)
        except Exception:
            return []

        message_code = int.from_bytes(data[0:2], byteorder="little", signed=False)
        events = self._events_by_id_code.get((can_id, message_code), [])
        if not events:
            return []

        data_hex = self._message_data_hex(can_message, data)
        decoded: list[DecodedCanEvent] = []
        for event in events:
            decoded_event = self._decode_event(event, data, data_hex, can_id, int(channel))
            if decoded_event is not None:
                decoded.append(decoded_event)
        return decoded

    def _load_events(self, events: Any) -> None:
        for event_payload in events:
            if not isinstance(event_payload, dict):
                continue

            event = dict(event_payload)
            message_code = _parse_int(event.get("message_code", 0))
            event["message_code_int"] = message_code
            event["can_ids"] = [normalize_can_id(can_id) for can_id in event.get("can_ids") or []]
            event["devices"] = {
                normalize_can_id(can_id): str(label)
                for can_id, label in dict(event.get("devices") or {}).items()
            }
            event["ignore_values"] = {_parse_int(value) for value in event.get("ignore_values") or []}

            for can_id in event["can_ids"]:
                self._events_by_id_code.setdefault((can_id, message_code), []).append(event)

    def _decode_event(
        self,
        event: dict[str, Any],
        data: bytes,
        data_hex: str,
        can_id: str,
        channel: int,
    ) -> DecodedCanEvent | None:
        value_config = event.get("value") if isinstance(event.get("value"), dict) else None
        raw_value = self._read_source(data, str(value_config.get("source"))) if value_config else None
        if isinstance(raw_value, int) and raw_value in event.get("ignore_values", set()):
            return None

        details: list[str] = []
        if value_config and raw_value is not None:
            details.append(self._format_field(value_config, raw_value))

        for extra in event.get("extra_fields") or []:
            if not isinstance(extra, dict):
                continue
            extra_value = self._read_source(data, str(extra.get("source")))
            if extra_value is not None:
                details.append(self._format_field(extra, extra_value))

        source_name = str(event.get("source_name") or "")
        if source_name:
            details.append(source_name)

        severity = str(event.get("severity") or "info")
        severity_by_value = event.get("severity_by_value")
        if isinstance(raw_value, int) and isinstance(severity_by_value, dict):
            severity = str(severity_by_value.get(str(raw_value), severity))

        event_key = str(event.get("key") or f"{can_id}:{event.get('message_code_int', 0)}")
        dedupe = str(event.get("dedupe") or "none")
        dedupe_value = str(raw_value) if raw_value is not None else data_hex

        return DecodedCanEvent(
            event_key=event_key,
            device=self._event_device(event, can_id),
            title=str(event.get("title") or source_name or event_key),
            details="; ".join(details),
            category=str(event.get("category") or ""),
            severity=severity,
            source_name=source_name,
            can_id=can_id,
            channel=channel,
            data_hex=data_hex,
            dedupe=dedupe,
            dedupe_key=f"{channel}:{can_id}:{event_key}",
            dedupe_value=dedupe_value,
        )

    def _event_device(self, event: dict[str, Any], can_id: str) -> str:
        devices = event.get("devices")
        if isinstance(devices, dict):
            device = devices.get(can_id)
            if device:
                return str(device)
        return str(event.get("device") or "")

    def _format_field(self, config: dict[str, Any], raw_value: int | float) -> str:
        label = str(config.get("label") or "Значение")
        return f"{label}: {self._format_value(config, raw_value)}"

    def _format_value(self, config: dict[str, Any], raw_value: int | float) -> str:
        if isinstance(raw_value, float):
            return f"{raw_value:.6g}"

        value_map_name = config.get("map")
        if value_map_name:
            value_map = self.value_maps.get(str(value_map_name), {})
            mapped_value = value_map.get(str(raw_value))
            if mapped_value:
                return f"{mapped_value} ({raw_value})"

        value_format = str(config.get("format") or "")
        if value_format == "bitmask":
            bits = [str(index + 1) for index in range(16) if raw_value & (1 << index)]
            if bits:
                return f"0x{raw_value:04X} (каналы: {', '.join(bits)})"
            return "0x0000"

        if value_format == "hex":
            return f"0x{raw_value:X}"

        return f"{raw_value} (0x{raw_value:X})"

    @staticmethod
    def _read_source(data: bytes, source: str) -> int | float | None:
        if source == "message_code_u16":
            return _read_u16(data, 0)
        if source == "code_u16":
            return _read_u16(data, 2)
        if source == "value_u16_lo":
            return _read_u16(data, 4)
        if source == "value_u16_hi":
            return _read_u16(data, 6)
        if source == "value_error_u16":
            high_word = _read_u16(data, 6)
            if high_word:
                return high_word
            return _read_u16(data, 4)
        if source == "value_u32":
            if len(data) < 8:
                return None
            return int.from_bytes(data[4:8], byteorder="little", signed=False)
        if source == "value_i32":
            if len(data) < 8:
                return None
            return int.from_bytes(data[4:8], byteorder="little", signed=True)
        if source == "value_float":
            if len(data) < 8:
                return None
            return float(struct.unpack("<f", data[4:8])[0])
        return None

    @staticmethod
    def _message_data_hex(can_message: Any, data: bytes) -> str:
        if hasattr(can_message, "get_data_hex"):
            try:
                return str(can_message.get_data_hex())
            except Exception:
                pass
        return " ".join(f"{byte:02X}" for byte in data)


def load_can_event_decoder(path: str | Path = EVENT_CATALOG_PATH) -> CanEventDecoder:
    return CanEventDecoder.from_file(path)


def _read_u16(data: bytes, offset: int) -> int | None:
    if offset < 0 or offset + 2 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 2], byteorder="little", signed=False)


def _parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, 10)

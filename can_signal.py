from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import struct
from typing import Any


SUPPORTED_TYPES = (
    "float32",
    "int32",
    "uint32",
    "int16",
    "uint16",
    "int8",
    "uint8",
)

SUPPORTED_BYTE_ORDERS = ("little_endian", "big_endian")


def parse_can_id(value: Any) -> int:
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("CAN ID is empty")

    if text.lower().startswith("0x"):
        return int(text, 16)

    text = text.replace(" ", "")
    return int(text, 16)


def normalize_can_id(value: Any) -> str:
    can_id = parse_can_id(value)
    if can_id > 0x7FF:
        return f"0x{can_id:08X}"
    return f"0x{can_id:03X}"


def get_message_id(can_message: Any) -> int:
    raw_id = getattr(can_message, "id", None)
    if raw_id is None and hasattr(can_message, "get_id_string"):
        raw_id = can_message.get_id_string()
    return parse_can_id(raw_id)


def get_message_id_string(can_message: Any) -> str:
    return normalize_can_id(get_message_id(can_message))


def get_message_signature(can_message: Any, byte_count: int = 4) -> str:
    data = bytes(getattr(can_message, "data", b""))
    if len(data) < byte_count:
        return ""
    return "".join(f"{byte:02X}" for byte in data[:byte_count])


def _signal_name_from_key(signal_key: str) -> str:
    key_without_channel = re.sub(r"_CH\d+$", "", signal_key)
    parts = key_without_channel.split("_")
    if len(parts) <= 1:
        return "Value"
    return "_".join(parts[1:]) or "Value"


def _channel_from_key(signal_key: str, fallback: int = 0) -> int:
    match = re.search(r"_CH(\d+)$", signal_key)
    if not match:
        return fallback
    return int(match.group(1))


def _id_from_key(signal_key: str) -> str:
    return signal_key.split("_", 1)[0]


def _clean_hex_bytes(value: Any, field_name: str) -> str:
    text = str(value or "").strip().replace(" ", "").upper()
    if text and not re.fullmatch(r"[0-9A-F]+", text):
        raise ValueError(f"{field_name} must contain only hex symbols")
    if len(text) % 2 != 0:
        raise ValueError(f"{field_name} length must be even")
    return text


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _normalize_can_id_list(value: Any) -> tuple[str, ...]:
    return tuple(normalize_can_id(item) for item in _as_list(value))


def _int_list(value: Any) -> tuple[int, ...]:
    return tuple(int(item) for item in _as_list(value))


@dataclass
class SignalDefinition:
    message_id: str
    name: str
    channel: int = 0
    type: str = "float32"
    byte_order: str = "little_endian"
    start_byte: int = 0
    length: int = 4
    scale: float = 1.0
    offset: float = 0.0
    first_bytes: str = ""
    match_offset: int = 0
    match_bytes: str = ""
    message_id_aliases: tuple[str, ...] = ()
    match_offset_aliases: tuple[int, ...] = ()
    color: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], fallback_key: str | None = None) -> "SignalDefinition":
        source = dict(payload)

        if fallback_key:
            source.setdefault("message_id", _id_from_key(fallback_key))
            source.setdefault("name", _signal_name_from_key(fallback_key))
            source.setdefault("channel", _channel_from_key(fallback_key, int(source.get("channel", 0))))

        message_id = normalize_can_id(source.get("message_id", source.get("id", "0x000")))
        parser_type = str(source.get("type", "float32"))
        if parser_type not in SUPPORTED_TYPES:
            parser_type = "float32"

        byte_order = str(source.get("byte_order", "little_endian"))
        if byte_order not in SUPPORTED_BYTE_ORDERS:
            byte_order = "little_endian"

        return cls(
            message_id=message_id,
            name=str(source.get("name", "Value")).strip() or "Value",
            channel=int(source.get("channel", 0)),
            type=parser_type,
            byte_order=byte_order,
            start_byte=int(source.get("start_byte", 0)),
            length=int(source.get("length", 4)),
            scale=float(source.get("scale", 1.0)),
            offset=float(source.get("offset", 0.0)),
            first_bytes=_clean_hex_bytes(source.get("first_bytes", ""), "first_bytes"),
            match_offset=int(source.get("match_offset", 0)),
            match_bytes=_clean_hex_bytes(source.get("match_bytes", ""), "match_bytes"),
            message_id_aliases=_normalize_can_id_list(source.get("message_id_aliases", source.get("id_aliases"))),
            match_offset_aliases=_int_list(source.get("match_offset_aliases")),
            color=str(source.get("color", "")),
        )

    @property
    def key(self) -> str:
        safe_name = re.sub(r"\s+", "_", self.name.strip()) or "Value"
        return f"{normalize_can_id(self.message_id)}_{safe_name}_CH{self.channel}"

    @property
    def label(self) -> str:
        message_ids = list(dict.fromkeys([normalize_can_id(self.message_id), *self.message_id_aliases]))
        label = f"CH{self.channel}: {'/'.join(message_ids)} {self.name}"
        if self.first_bytes:
            label = f"{label} [{self.first_bytes}]"
        if self.match_bytes:
            offsets = list(dict.fromkeys([str(self.match_offset), *(str(offset) for offset in self.match_offset_aliases)]))
            label = f"{label} @B{'/'.join(offsets)}:{self.match_bytes}"
        return label

    def to_mapping(self) -> dict[str, Any]:
        return {
            "message_id": normalize_can_id(self.message_id),
            "name": self.name,
            "channel": self.channel,
            "type": self.type,
            "byte_order": self.byte_order,
            "start_byte": self.start_byte,
            "length": self.length,
            "scale": self.scale,
            "offset": self.offset,
            "first_bytes": self.first_bytes,
            "match_offset": self.match_offset,
            "match_bytes": self.match_bytes,
            "message_id_aliases": list(self.message_id_aliases),
            "match_offset_aliases": list(self.match_offset_aliases),
            "color": self.color,
        }


@dataclass
class ProjectTemplate:
    name: str = "CAN project"
    channel: int = 0
    baud_rate: int = 500000
    history_seconds: int = 600
    signals: list[SignalDefinition] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "ProjectTemplate":
        template_path = Path(path)
        with template_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if isinstance(payload, dict) and "template_key" in payload:
            from template_registry import project_template_from_definition

            return project_template_from_definition(payload)

        if isinstance(payload, dict) and "signals" in payload:
            signals_payload = payload.get("signals") or []
            signals = [
                SignalDefinition.from_mapping(item)
                for item in signals_payload
                if isinstance(item, dict)
            ]
            return cls(
                name=str(payload.get("name", template_path.stem)),
                channel=int(payload.get("channel", 0)),
                baud_rate=int(payload.get("baud_rate", 500000)),
                history_seconds=int(payload.get("history_seconds", 600)),
                signals=signals,
            )

        if isinstance(payload, dict):
            signals = [
                SignalDefinition.from_mapping(config, fallback_key=signal_key)
                for signal_key, config in payload.items()
                if isinstance(config, dict)
            ]
            return cls(name=template_path.stem, signals=signals)

        raise ValueError("Unsupported template format")

    def save(self, path: str | Path) -> None:
        signal_payloads = []
        for signal in self.signals:
            signal_payload = signal.to_mapping()
            signal_payload.pop("channel", None)
            signal_payloads.append(signal_payload)

        payload = {
            "version": 1,
            "name": self.name,
            "baud_rate": self.baud_rate,
            "history_seconds": self.history_seconds,
            "signals": signal_payloads,
        }
        with Path(path).open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)


class SignalIndex:
    def __init__(self, signals: list[SignalDefinition] | tuple[SignalDefinition, ...] = ()):
        self._by_channel_id: dict[tuple[int, int], list[SignalDefinition]] = {}
        for signal in signals:
            self.add(signal)

    def add(self, signal: SignalDefinition) -> None:
        message_ids = list(dict.fromkeys([signal.message_id, *signal.message_id_aliases]))
        for message_id in message_ids:
            key = (int(signal.channel), parse_can_id(message_id))
            self._by_channel_id.setdefault(key, []).append(signal)

    def candidates(self, can_message: Any, channel: int) -> tuple[SignalDefinition, ...]:
        try:
            message_id = get_message_id(can_message)
        except Exception:
            return ()
        return tuple(self._by_channel_id.get((int(channel), message_id), ()))

    def parse_message(self, can_message: Any, channel: int) -> dict[str, float]:
        values: dict[str, float] = {}
        for signal in self.candidates(can_message, channel):
            if not message_payload_matches_signal(can_message, signal):
                continue

            value = parse_signal_value(can_message, signal)
            if value is not None:
                values[signal.key] = value
        return values


def message_matches_signal(can_message: Any, channel: int, signal: SignalDefinition) -> bool:
    if int(channel) != int(signal.channel):
        return False

    message_ids = {parse_can_id(signal.message_id)}
    message_ids.update(parse_can_id(message_id) for message_id in signal.message_id_aliases)
    if get_message_id(can_message) not in message_ids:
        return False

    return message_payload_matches_signal(can_message, signal)


def message_payload_matches_signal(can_message: Any, signal: SignalDefinition) -> bool:
    if signal.first_bytes:
        actual = get_message_signature(can_message, len(signal.first_bytes) // 2)
        if actual.upper() != signal.first_bytes.upper():
            return False

    if signal.match_bytes:
        data = bytes(getattr(can_message, "data", b""))
        match = bytes.fromhex(signal.match_bytes)
        offsets = [int(signal.match_offset), *signal.match_offset_aliases]
        if not any(_match_bytes_at_offset(data, match, offset) for offset in offsets):
            return False

    return True


def _match_bytes_at_offset(data: bytes, match: bytes, offset: int) -> bool:
    start = int(offset)
    end = start + len(match)
    if start < 0 or end > len(data):
        return False
    return data[start:end] == match


def parse_signal_value(can_message: Any, signal: SignalDefinition) -> float | None:
    data = bytes(getattr(can_message, "data", b""))
    start = int(signal.start_byte)
    length = int(signal.length)

    if start < 0 or length <= 0 or start + length > len(data):
        return None

    data_bytes = data[start : start + length]

    if all(byte == 0xFF for byte in data_bytes):
        if signal.type in ("uint32", "int32", "float32"):
            return 4294967295.0 * signal.scale + signal.offset
        if signal.type in ("uint16", "int16"):
            return 65535.0 * signal.scale + signal.offset
        if signal.type in ("uint8", "int8"):
            return 255.0 * signal.scale + signal.offset

    endian = ">" if signal.byte_order == "big_endian" else "<"

    formats = {
        "float32": (4, f"{endian}f"),
        "int32": (4, f"{endian}i"),
        "uint32": (4, f"{endian}I"),
        "int16": (2, f"{endian}h"),
        "uint16": (2, f"{endian}H"),
        "int8": (1, "b"),
        "uint8": (1, "B"),
    }

    required_length, format_code = formats.get(signal.type, formats["float32"])
    if len(data_bytes) < required_length:
        return None

    raw_value = struct.unpack(format_code, data_bytes[:required_length])[0]

    if signal.type == "float32" and (math.isnan(raw_value) or math.isinf(raw_value)):
        raw_value = struct.unpack(f"{endian}I", data_bytes[:4])[0]

    return float(raw_value) * signal.scale + signal.offset


def parse_message_signals(
    can_message: Any,
    channel: int,
    signals: list[SignalDefinition] | SignalIndex,
) -> dict[str, float]:
    if isinstance(signals, SignalIndex):
        return signals.parse_message(can_message, channel)

    values: dict[str, float] = {}
    for signal in signals:
        if not message_matches_signal(can_message, channel, signal):
            continue

        value = parse_signal_value(can_message, signal)
        if value is not None:
            values[signal.key] = value

    return values

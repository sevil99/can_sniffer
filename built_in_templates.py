from __future__ import annotations

from dataclasses import dataclass

from can_signal import ProjectTemplate, SignalDefinition


MID_CHANNEL_DEFAULT = 1
MID_BAUD_RATE_DEFAULT = 500000
MID_HISTORY_SECONDS_DEFAULT = 600

KSI_GENERAL_BASE = 0x0100

MID_MESSAGE_CODES = {
    "knock": 0x0003,
    "offset": 0x0002,
    "sync_errors": 0x0001,
}

MID_METRIC_LABELS = {
    "knock": "Детонация",
    "offset": "Смещение",
    "sync_errors": "Счетчик ошибок",
}

MID_METRIC_TYPES = {
    "knock": "float32",
    "offset": "float32",
    "sync_errors": "uint32",
}

MID_CYLINDERS = tuple(
    [(f"A{index}", 0x000E + index) for index in range(1, 13)]
    + [(f"B{index}", 0x001A + index) for index in range(1, 13)]
)


@dataclass(frozen=True)
class BuiltInTemplateInfo:
    key: str
    title: str
    description: str


BUILT_IN_TEMPLATES = (
    BuiltInTemplateInfo(
        key="mid",
        title="МИД",
        description="Модуль измерения детонации: детонация, смещение и счетчик ошибок по цилиндрам.",
    ),
)


def code_match_bytes(code: int) -> str:
    return code.to_bytes(2, byteorder="little", signed=False).hex().upper()


def cylinder_general_id(base_id: int) -> str:
    return f"0x{base_id + KSI_GENERAL_BASE:03X}"


def build_mid_template(
    selected: dict[str, set[str]],
    channel: int = MID_CHANNEL_DEFAULT,
    baud_rate: int = MID_BAUD_RATE_DEFAULT,
    history_seconds: int = MID_HISTORY_SECONDS_DEFAULT,
) -> ProjectTemplate:
    signals: list[SignalDefinition] = []

    for cylinder, base_id in MID_CYLINDERS:
        metrics = selected.get(cylinder, set())
        for metric_key in ("knock", "offset", "sync_errors"):
            if metric_key not in metrics:
                continue

            signals.append(
                SignalDefinition.from_mapping(
                    {
                        "message_id": cylinder_general_id(base_id),
                        "name": f"{cylinder} {MID_METRIC_LABELS[metric_key]}",
                        "channel": channel,
                        "type": MID_METRIC_TYPES[metric_key],
                        "byte_order": "little_endian",
                        "start_byte": 4,
                        "length": 4,
                        "scale": 1.0,
                        "offset": 0.0,
                        "match_offset": 2,
                        "match_bytes": code_match_bytes(MID_MESSAGE_CODES[metric_key]),
                    }
                )
            )

    return ProjectTemplate(
        name="МИД",
        channel=channel,
        baud_rate=baud_rate,
        history_seconds=history_seconds,
        signals=signals,
    )


def default_mid_selection() -> dict[str, set[str]]:
    return {cylinder: set(MID_MESSAGE_CODES) for cylinder, _base_id in MID_CYLINDERS}

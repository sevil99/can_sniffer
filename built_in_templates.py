from __future__ import annotations

from dataclasses import dataclass

from can_signal import ProjectTemplate, SignalDefinition


MID_CHANNEL_DEFAULT = 0
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

GAS_REGULATOR_DEVICE_ID_DEFAULT = 0x001
GAS_REGULATOR_BAUD_RATE_DEFAULT = 500000
GAS_REGULATOR_HISTORY_SECONDS_DEFAULT = 600

PID_IDS = {
    0x27: "PV",
    0x28: "SP",
    0x29: "CV",
    0x30: "CV_P",
    0x31: "CV_I",
    0x32: "CV_D",
    0x33: "Kp",
    0x34: "Ki",
    0x35: "Kd",
    0x36: "PD",
    0x37: "PD_DZ",
}


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
    BuiltInTemplateInfo(
        key="gas_regulator",
        title="Регулятор газа",
        description="PID-параметры регулятора газа: PV, SP, CV, составляющие PID и коэффициенты.",
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
    return {cylinder: set() for cylinder, _base_id in MID_CYLINDERS}


def build_gas_regulator_template(
    selected_pid_ids: set[int],
    device_id: int = GAS_REGULATOR_DEVICE_ID_DEFAULT,
    channel: int = MID_CHANNEL_DEFAULT,
    baud_rate: int = GAS_REGULATOR_BAUD_RATE_DEFAULT,
    history_seconds: int = GAS_REGULATOR_HISTORY_SECONDS_DEFAULT,
) -> ProjectTemplate:
    signals: list[SignalDefinition] = []

    for pid_id, name in PID_IDS.items():
        if pid_id not in selected_pid_ids:
            continue

        signals.append(
            SignalDefinition.from_mapping(
                {
                    "message_id": f"0x{device_id:03X}",
                    "name": name,
                    "channel": channel,
                    "type": "float32",
                    "byte_order": "little_endian",
                    "start_byte": 4,
                    "length": 4,
                    "scale": 1.0,
                    "offset": 0.0,
                    "match_offset": 2,
                    "match_bytes": code_match_bytes(pid_id),
                }
            )
        )

    return ProjectTemplate(
        name="Регулятор газа",
        channel=channel,
        baud_rate=baud_rate,
        history_seconds=history_seconds,
        signals=signals,
    )

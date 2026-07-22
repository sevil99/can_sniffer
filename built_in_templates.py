from __future__ import annotations

from template_registry import (
    TemplateInfo as BuiltInTemplateInfo,
    code_match_bytes,
    get_mid_cylinders,
    get_mid_metrics,
    get_pid_ids,
    list_template_infos,
    load_project_template,
    load_template_definition,
)


_MID_DEFINITION = load_template_definition("mid")
_GAS_REGULATOR_DEFINITION = load_template_definition("gas_regulator")

MID_CHANNEL_DEFAULT = int(_MID_DEFINITION.get("project", {}).get("channel", 0))
MID_BAUD_RATE_DEFAULT = int(_MID_DEFINITION.get("project", {}).get("baud_rate", 500000))
MID_HISTORY_SECONDS_DEFAULT = int(_MID_DEFINITION.get("project", {}).get("history_seconds", 600))

MID_CYLINDERS = get_mid_cylinders(_MID_DEFINITION)
MID_METRICS = get_mid_metrics(_MID_DEFINITION)
MID_MESSAGE_CODES = {
    str(metric["key"]): int(str(metric["code"]), 16)
    for metric in MID_METRICS
}
MID_METRIC_LABELS = {
    str(metric["key"]): str(metric["label"])
    for metric in MID_METRICS
}
MID_METRIC_TYPES = {
    str(metric["key"]): str(metric["type"])
    for metric in MID_METRICS
}

GAS_REGULATOR_DEVICE_ID_DEFAULT = int(str(_GAS_REGULATOR_DEFINITION.get("device_id", "0x001")), 16)
GAS_REGULATOR_BAUD_RATE_DEFAULT = int(_GAS_REGULATOR_DEFINITION.get("project", {}).get("baud_rate", 500000))
GAS_REGULATOR_HISTORY_SECONDS_DEFAULT = int(
    _GAS_REGULATOR_DEFINITION.get("project", {}).get("history_seconds", 600)
)

PID_IDS = get_pid_ids(_GAS_REGULATOR_DEFINITION)
BUILT_IN_TEMPLATES = list_template_infos()


def cylinder_general_id(base_id: int) -> str:
    general_base = int(str(_MID_DEFINITION.get("ksi_general_base", "0x100")), 16)
    return f"0x{base_id + general_base:03X}"


def build_mid_template(
    selected: dict[str, set[str]],
    channel: int = MID_CHANNEL_DEFAULT,
    baud_rate: int = MID_BAUD_RATE_DEFAULT,
    history_seconds: int = MID_HISTORY_SECONDS_DEFAULT,
):
    return load_project_template(
        "mid",
        selected=selected,
        channel=channel,
        baud_rate=baud_rate,
        history_seconds=history_seconds,
    )


def default_mid_selection() -> dict[str, set[str]]:
    return {cylinder: set() for cylinder, _base_id in MID_CYLINDERS}


def build_gas_regulator_template(
    selected_pid_ids: set[int],
    device_id: int = GAS_REGULATOR_DEVICE_ID_DEFAULT,
    channel: int = MID_CHANNEL_DEFAULT,
    baud_rate: int = GAS_REGULATOR_BAUD_RATE_DEFAULT,
    history_seconds: int = GAS_REGULATOR_HISTORY_SECONDS_DEFAULT,
):
    return load_project_template(
        "gas_regulator",
        selected=selected_pid_ids,
        channel=channel,
        baud_rate=baud_rate,
        history_seconds=history_seconds,
        device_id=device_id,
    )

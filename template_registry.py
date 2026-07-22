from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from can_signal import ProjectTemplate, SignalDefinition, parse_can_id


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    title: str
    description: str
    path: Path


def code_match_bytes(code: int) -> str:
    return int(code).to_bytes(2, byteorder="little", signed=False).hex().upper()


def resolve_template_path(key_or_path: str | Path) -> Path:
    candidate = Path(key_or_path)
    if candidate.exists():
        return candidate

    if candidate.suffix:
        template_path = TEMPLATES_DIR / candidate.name
    else:
        template_path = TEMPLATES_DIR / f"{candidate}.json"

    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {key_or_path}")

    return template_path


def load_template_definition(key_or_path: str | Path) -> dict[str, Any]:
    path = resolve_template_path(key_or_path)
    with path.open("r", encoding="utf-8") as file:
        definition = json.load(file)

    if not isinstance(definition, dict):
        raise ValueError(f"Unsupported template definition: {path}")

    definition = dict(definition)
    definition["_path"] = str(path)
    return definition


def list_template_infos() -> tuple[TemplateInfo, ...]:
    ordered_infos: list[tuple[int, TemplateInfo]] = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        definition = load_template_definition(path)
        key = str(definition.get("template_key") or path.stem)
        ordered_infos.append(
            (
                int(definition.get("order", 1000)),
                TemplateInfo(
                    key=key,
                    title=str(definition.get("title") or definition.get("name") or path.stem),
                    description=str(definition.get("description") or ""),
                    path=path,
                ),
            )
        )
    return tuple(info for _order, info in sorted(ordered_infos, key=lambda item: (item[0], item[1].title)))


def project_template_from_definition(
    definition: dict[str, Any],
    selected: Any = None,
    channel: int | None = None,
    baud_rate: int | None = None,
    history_seconds: int | None = None,
    device_id: int | None = None,
) -> ProjectTemplate:
    template_key = str(definition.get("template_key") or "")
    project = dict(definition.get("project") or {})

    project_channel = int(project.get("channel", 0) if channel is None else channel)
    project_baud_rate = int(project.get("baud_rate", 500000) if baud_rate is None else baud_rate)
    project_history = int(project.get("history_seconds", 600) if history_seconds is None else history_seconds)

    if template_key == "mid":
        signals = _build_mid_signals(definition, selected, project_channel)
    elif template_key == "gas_regulator":
        signals = _build_gas_regulator_signals(definition, selected, project_channel, device_id)
    else:
        raise ValueError(f"Unknown template definition: {template_key or '<empty>'}")

    return ProjectTemplate(
        name=str(project.get("name") or definition.get("title") or template_key or "CAN project"),
        channel=project_channel,
        baud_rate=project_baud_rate,
        history_seconds=project_history,
        signals=signals,
    )


def load_project_template(
    key_or_path: str | Path,
    selected: Any = None,
    channel: int | None = None,
    baud_rate: int | None = None,
    history_seconds: int | None = None,
    device_id: int | None = None,
) -> ProjectTemplate:
    definition = load_template_definition(key_or_path)
    return project_template_from_definition(
        definition,
        selected=selected,
        channel=channel,
        baud_rate=baud_rate,
        history_seconds=history_seconds,
        device_id=device_id,
    )


def get_mid_cylinders(definition: dict[str, Any] | None = None) -> tuple[tuple[str, int], ...]:
    definition = definition or load_template_definition("mid")
    cylinders: list[tuple[str, int]] = []
    for group in definition.get("cylinder_groups") or []:
        prefix = str(group["prefix"])
        start = int(group["start"])
        end = int(group["end"])
        base_id_start = parse_can_id(group["base_id_start"])
        for index in range(start, end + 1):
            cylinders.append((f"{prefix}{index}", base_id_start + index - start))
    return tuple(cylinders)


def get_mid_metrics(definition: dict[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    definition = definition or load_template_definition("mid")
    return tuple(dict(metric) for metric in definition.get("metrics") or [])


def get_pid_ids(definition: dict[str, Any] | None = None) -> dict[int, str]:
    definition = definition or load_template_definition("gas_regulator")
    return {
        parse_can_id(signal["pid_id"]): str(signal["name"])
        for signal in definition.get("pid_signals") or []
    }


def _build_mid_signals(definition: dict[str, Any], selected: Any, channel: int) -> list[SignalDefinition]:
    defaults = dict(definition.get("signal_defaults") or {})
    general_base = parse_can_id(definition.get("ksi_general_base", "0x100"))
    metrics = get_mid_metrics(definition)
    cylinders = get_mid_cylinders(definition)

    if selected is None:
        selected = {cylinder: {str(metric["key"]) for metric in metrics} for cylinder, _ in cylinders}

    signals: list[SignalDefinition] = []
    for cylinder, base_id in cylinders:
        selected_metrics = set(selected.get(cylinder, set()))
        for metric in metrics:
            metric_key = str(metric["key"])
            if metric_key not in selected_metrics:
                continue

            signals.append(
                SignalDefinition.from_mapping(
                    {
                        **defaults,
                        "message_id": f"0x{general_base + base_id:03X}",
                        "name": f"{cylinder} {metric['label']}",
                        "channel": channel,
                        "type": metric["type"],
                        "match_bytes": code_match_bytes(parse_can_id(metric["code"])),
                    }
                )
            )
    return signals


def _build_gas_regulator_signals(
    definition: dict[str, Any],
    selected: Any,
    channel: int,
    device_id: int | None,
) -> list[SignalDefinition]:
    defaults = dict(definition.get("signal_defaults") or {})
    message_id = device_id if device_id is not None else parse_can_id(definition.get("device_id", "0x001"))
    pid_ids = get_pid_ids(definition)
    selected_pid_ids = set(pid_ids) if selected is None else {int(pid_id) for pid_id in selected}

    signals: list[SignalDefinition] = []
    for pid_id, name in pid_ids.items():
        if pid_id not in selected_pid_ids:
            continue

        signals.append(
            SignalDefinition.from_mapping(
                {
                    **defaults,
                    "message_id": f"0x{message_id:03X}",
                    "name": name,
                    "channel": channel,
                    "match_bytes": code_match_bytes(pid_id),
                }
            )
        )
    return signals

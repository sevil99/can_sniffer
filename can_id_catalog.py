from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from can_signal import ProjectTemplate, normalize_can_id
from template_registry import list_template_infos


CATALOG_PATH = Path(__file__).resolve().parent / "can_id_catalog.json"


class CanIdCatalog:
    def __init__(self) -> None:
        self._by_id: dict[str, list[str]] = {}
        self._by_channel_id: dict[tuple[str, int], list[str]] = {}

    def add(self, message_id: Any, label: str, channel: int | None = None) -> None:
        normalized_id = normalize_can_id(message_id)
        clean_label = str(label).strip()
        if not clean_label:
            return

        self._append_unique(self._by_id.setdefault(normalized_id, []), clean_label)
        if channel is not None:
            self._append_unique(self._by_channel_id.setdefault((normalized_id, int(channel)), []), clean_label)

    def describe(self, message_id: Any, channel: int | None = None) -> str:
        normalized_id = normalize_can_id(message_id)
        labels: list[str] = []

        if channel is not None:
            for label in self._by_channel_id.get((normalized_id, int(channel)), []):
                self._append_unique(labels, label)

        for label in self._by_id.get(normalized_id, []):
            self._append_unique(labels, label)

        return ", ".join(labels)

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)


def load_can_id_catalog(catalog_path: str | Path = CATALOG_PATH) -> CanIdCatalog:
    catalog = CanIdCatalog()
    _load_template_labels(catalog)
    _load_json_catalog(catalog, Path(catalog_path))
    return catalog


def _load_template_labels(catalog: CanIdCatalog) -> None:
    for info in list_template_infos():
        try:
            template = ProjectTemplate.load(info.path)
        except Exception:
            continue

        for signal in template.signals:
            label = _template_signal_label(info.key, template.name or info.title, signal.name)
            catalog.add(signal.message_id, label, signal.channel)


def _template_signal_label(template_key: str, template_name: str, signal_name: str) -> str:
    if template_key == "mid":
        cylinder = signal_name.split(maxsplit=1)[0].strip()
        if cylinder:
            return f"{template_name} {cylinder}"

    return template_name


def _load_json_catalog(catalog: CanIdCatalog, path: Path) -> None:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    for entry in _iter_json_entries(payload):
        message_id = entry.get("id") or entry.get("can_id") or entry.get("message_id")
        label = entry.get("label") or entry.get("name") or entry.get("module")
        channel = entry.get("channel")
        if message_id is None or label is None:
            continue

        catalog.add(message_id, str(label), int(channel) if channel is not None else None)


def _iter_json_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]

    if not isinstance(payload, dict):
        return []

    entries = payload.get("ids") or payload.get("can_ids")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]

    result: list[dict[str, Any]] = []
    for key, value in payload.items():
        if key in {"version", "ids", "can_ids"}:
            continue

        if isinstance(value, str):
            result.append({"id": key, "label": value})
        elif isinstance(value, dict):
            result.append({"id": key, **value})

    return result

"""The Gulf voice AI provider registry (providers.yaml) and how ready each provider is to test."""

from __future__ import annotations

import os
from typing import Any

import yaml

from .config import ROOT
from .stacks import list_stacks, requirements


def load() -> list[dict[str, Any]]:
    p = ROOT / "providers.yaml"
    return yaml.safe_load(p.read_text()).get("providers", []) if p.exists() else []


def status(pr: dict[str, Any], stacks: dict[str, dict[str, Any]]) -> str:
    ids = pr.get("stacks", [])
    if not ids:
        return "no stack yet: " + pr.get("how_to_test", "see notes")
    states = []
    for sid in ids:
        st = stacks.get(sid)
        if st is None:
            states.append(f"{sid}: missing file")
            continue
        miss = requirements(st)
        states.append(f"{sid}: {'ready' if not miss else 'needs ' + ', '.join(miss)}")
    return "; ".join(states)


def print_providers(group: str | None = None) -> None:
    stacks = {s["id"]: s for s in list_stacks() if not s.get("error")}
    for pr in load():
        if group and pr.get("group") != group:
            continue
        print(f"{pr['name']}  [{pr.get('hq', '?')}, {pr.get('group', '?')}]  {', '.join(pr.get('types', []))}")
        print(f"    {status(pr, stacks)}")

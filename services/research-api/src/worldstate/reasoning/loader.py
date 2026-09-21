"""Load and hash the bundled macro reasoning playbook."""

from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

import yaml

from worldstate.reasoning.schema import MechanismPlaybook


def playbook_path() -> Path:
    return Path(str(files("worldstate.reasoning").joinpath("playbooks/macro_reasoning_v1.yaml")))


def load_playbook() -> tuple[MechanismPlaybook, str]:
    raw = playbook_path().read_bytes()
    parsed = yaml.safe_load(raw.decode("utf-8"))
    return MechanismPlaybook.model_validate(parsed), hashlib.sha256(raw).hexdigest()

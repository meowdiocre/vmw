"""Profile loading: configs/*.yml -> Profile (plan 01)."""

from __future__ import annotations

from pathlib import Path

import yaml

from vmw.profiles.schema import Profile

# configs/ sits at the repo root: python/vmw/profiles/loader.py -> ../../..
CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs"

# Shared defaults every profile inherits. A profile file carries only what
# differs from this base (name, memory, disk); the values common to every VM
# live here once instead of being copied into each profile.
DEFAULTS_STEM = "_defaults"


class ProfileError(Exception):
    """Raised when a profile cannot be found or fails validation."""


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively overlay ``override`` onto ``base`` (override wins).

    Nested mappings merge key-by-key; scalars and lists replace wholesale.
    Neither input is mutated.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ProfileError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {path} is empty or not a mapping")
    return raw


def load_config(name: str, configs_dir: Path | None = None) -> Profile:
    """Load configs/<name>.yml (merged over configs/_defaults.yml) into a Profile."""
    configs_dir = configs_dir or CONFIGS_DIR
    path = configs_dir / f"{name}.yml"
    if not path.is_file():
        raise ProfileError(f"profile '{name}' not found at {path}")
    raw = _load_yaml(path)

    defaults_path = configs_dir / f"{DEFAULTS_STEM}.yml"
    if name != DEFAULTS_STEM and defaults_path.is_file():
        raw = _deep_merge(_load_yaml(defaults_path), raw)

    try:
        return Profile.model_validate(raw)
    except Exception as exc:
        raise ProfileError(f"profile {name} failed validation: {exc}") from exc


def discover(configs_dir: Path | None = None) -> list[str]:
    """Every profile name available in configs/ (the _defaults base excluded)."""
    configs_dir = configs_dir or CONFIGS_DIR
    if not configs_dir.is_dir():
        return []
    return sorted(p.stem for p in configs_dir.glob("*.yml") if not p.stem.startswith("_"))

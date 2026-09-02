"""Round-trip profile editing (plan 07, D4).

Loads a profile YAML preserving its comments and key order, applies
field edits to the in-memory document, validates the result against the
schema, and writes it back atomically. The point of ruamel round-trip
mode is that saving a profile does not strip the comments that explain
it.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from ruamel.yaml import YAML

from vmw.profiles.loader import CONFIGS_DIR
from vmw.profiles.schema import Profile


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_roundtrip(name: str, configs_dir: Path | None = None):
    """Load a profile as a comment-preserving document (CommentedMap)."""
    configs_dir = configs_dir or CONFIGS_DIR
    path = configs_dir / f"{name}.yml"
    return _yaml().load(path.read_text())


def dump_roundtrip(data) -> str:
    """Serialise a round-trip document back to YAML text."""
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def validate(data) -> Profile:
    """Validate a document dict against the schema (raises on failure)."""
    return Profile.model_validate(_plain(data))


def _plain(data):
    """Recursively convert ruamel Commented* into plain dict/list/scalars."""
    if hasattr(data, "items"):
        return {k: _plain(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_plain(v) for v in data]
    return data


def save(name: str, data, configs_dir: Path | None = None) -> Path:
    """Validate then atomically write configs/<name>.yml. Returns the path.

    Raises pydantic ValidationError if the document is invalid; the file
    on disk is never touched in that case.
    """
    validate(data)  # never write an invalid profile
    configs_dir = configs_dir or CONFIGS_DIR
    configs_dir.mkdir(parents=True, exist_ok=True)
    path = configs_dir / f"{name}.yml"
    text = dump_roundtrip(data)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def new_document(name: str):
    """A fresh round-trip document from schema defaults for a new profile.

    Only the required fields are prompted; everything else takes its
    schema default so the file stays short and the editor fills the rest.
    """
    seed = {
        "name": name,
        "vm": {"memory_mib": 8192, "vcpus": 4},
        "device": {"disk_size_gb": 150},
    }
    return _yaml().load(dump_from_plain(seed))


def dump_from_plain(plain: dict) -> str:
    buf = io.StringIO()
    _yaml().dump(plain, buf)
    return buf.getvalue()

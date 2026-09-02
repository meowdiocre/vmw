"""Turn a pydantic model into form-field descriptors (plan 07, D3).

The schema in profiles/schema.py is fully typed, so the widget for each
field is derivable from its annotation. Deriving descriptors here, apart
from any Textual code, keeps the mapping unit-testable and means a new
schema field appears in the editor with no extra UI work.
"""

from __future__ import annotations

import enum
import types
import typing
from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic.fields import FieldInfo


@dataclass
class FieldSpec:
    """One editable field: enough for the editor to pick a widget."""

    path: str  # dotted path, e.g. "cpu.topology.cores"
    name: str  # leaf name shown as the label
    kind: str  # "select" | "switch" | "int" | "text"
    value: object
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    optional: bool = False


@dataclass
class SectionSpec:
    """A model section: its fields, plus any nested sections."""

    path: str
    name: str
    fields: list[FieldSpec] = field(default_factory=list)
    sections: list[SectionSpec] = field(default_factory=list)


def _unwrap_optional(annotation) -> tuple[object, bool]:
    """Return (inner type, was_optional) for `X | None` annotations."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _literal_choices(annotation) -> tuple[str, ...] | None:
    if typing.get_origin(annotation) is typing.Literal:
        return tuple(str(a) for a in typing.get_args(annotation))
    return None


def _field_spec(path: str, name: str, info: FieldInfo, value: object) -> FieldSpec | None:
    annotation, optional = _unwrap_optional(info.annotation)

    choices = _literal_choices(annotation)
    if choices is not None:
        return FieldSpec(path, name, "select", value, choices=choices, optional=optional)

    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        opts = tuple(str(m.value) for m in annotation)
        return FieldSpec(
            path,
            name,
            "select",
            str(value.value if hasattr(value, "value") else value),
            choices=opts,
            optional=optional,
        )

    if annotation is bool:
        return FieldSpec(path, name, "switch", bool(value), optional=optional)

    if annotation is int:
        lo, hi = _int_bounds(info)
        return FieldSpec(path, name, "int", value, minimum=lo, maximum=hi, optional=optional)

    if annotation is str:
        return FieldSpec(path, name, "text", "" if value is None else str(value), optional=optional)

    # Paths, lists, and nested models are not inline-editable here.
    return None


def _int_bounds(info: FieldInfo) -> tuple[int | None, int | None]:
    lo = hi = None
    for meta in info.metadata:
        lo = getattr(meta, "ge", lo) if getattr(meta, "ge", None) is not None else lo
        gt = getattr(meta, "gt", None)
        if gt is not None:
            lo = gt + 1
        hi = getattr(meta, "le", hi) if getattr(meta, "le", None) is not None else hi
    return lo, hi


def build_sections(model: BaseModel, path: str = "", name: str = "") -> SectionSpec:
    """Walk a pydantic instance into a tree of sections and fields."""
    section = SectionSpec(path=path or "", name=name or model.__class__.__name__)
    for fname, info in type(model).model_fields.items():
        value = getattr(model, fname)
        child_path = f"{path}.{fname}" if path else fname
        if isinstance(value, BaseModel):
            section.sections.append(build_sections(value, child_path, fname))
            continue
        spec = _field_spec(child_path, fname, info, value)
        if spec is not None:
            section.fields.append(spec)
    return section


def apply_edit(data: dict, path: str, raw: str, kind: str) -> None:
    """Set a dotted path in a plain dict, coercing to the field's kind.

    Operates on the round-trippable dict, not the model, so comments and
    key order survive. Validation happens when the dict is re-validated.
    """
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    leaf = parts[-1]
    if kind == "switch":
        node[leaf] = bool(raw)
    elif kind == "int":
        node[leaf] = int(raw)
    else:
        node[leaf] = raw

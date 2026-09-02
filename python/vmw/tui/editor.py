"""Profile editor screen (plan 07, D3/D4).

Every widget is generated from the schema via formgen, so a new schema
field appears here with no edit to this file. Changes apply to a
round-trip YAML document (comments preserved), validate through the
schema on save, and write atomically. Fully keyboard operable.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, Select, Static, Switch

from vmw.profiles import editor as profile_editor
from vmw.tui.formgen import FieldSpec, SectionSpec, apply_edit, build_sections


class ProfileEditorScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, name: str | None):
        super().__init__()
        self.profile_name = name
        self.is_new = name is None
        self._doc = None
        self._baseline = ""  # serialised doc at load; dirty = current differs
        self._discard_armed = False

    def compose(self) -> ComposeResult:
        yield Header()
        title = "New profile" if self.is_new else f"Edit profile: {self.profile_name}"
        yield Label(title, id="editor-title")
        yield Static("", id="editor-status")
        with VerticalScroll(id="editor-body"):
            yield Vertical(id="editor-fields")
        yield Footer()

    def on_mount(self) -> None:
        if self.is_new:
            self._ask_new_name()
        else:
            self._load(self.profile_name)

    def _ask_new_name(self) -> None:
        # A new profile needs a name before anything else; reuse the modal.

        def got(name: str | None) -> None:
            if not name:
                self.app.pop_screen()
                return
            self.profile_name = name
            self._doc = profile_editor.new_document(name)
            self._render_form()
            self._status(f"new profile '{name}', ctrl+s to save")

        # PathInputScreen is a plain text prompt; a real build would use a
        # dedicated NameInput, but this keeps the surface small.
        self.app.push_screen(_NameScreen(), got)

    def _load(self, name: str) -> None:
        try:
            self._doc = profile_editor.load_roundtrip(name)
        except Exception as exc:
            self._status(f"cannot load {name}: {exc}", error=True)
            return
        self._render_form()

    def _render_form(self) -> None:
        from vmw.profiles.loader import load_config

        try:
            model = load_config(self.profile_name)
        except Exception:
            model = profile_editor.validate(self._doc)
        tree = build_sections(model)
        container = self.query_one("#editor-fields", Vertical)
        container.remove_children()
        self._mount_section(container, tree, top=True)
        # Baseline is the document as loaded. _apply skips no-op writes
        # (mount echoes and edits equal to the original), so an untouched
        # editor never diverges from this and saves stay minimal.
        self._baseline = profile_editor.dump_roundtrip(self._doc)

    def _is_dirty(self) -> bool:
        """True when the document differs from what was loaded."""
        if self._doc is None:
            return False
        return profile_editor.dump_roundtrip(self._doc) != self._baseline

    def _mount_section(self, parent, section: SectionSpec, top: bool = False) -> None:
        if not top:
            parent.mount(Static(section.name.upper(), classes="section-head"))
        for spec in section.fields:
            parent.mount(_FieldRow(spec, self._widget_for(spec)))
        for sub in section.sections:
            self._mount_section(parent, sub)

    def _widget_for(self, spec: FieldSpec):
        if spec.kind == "select":
            options = [(c, c) for c in spec.choices]
            return Select(options, value=str(spec.value), allow_blank=False, id=self._wid(spec))
        if spec.kind == "switch":
            return Switch(value=bool(spec.value), id=self._wid(spec))
        placeholder = ""
        if spec.kind == "int" and (spec.minimum is not None or spec.maximum is not None):
            placeholder = f"{spec.minimum or ''}..{spec.maximum or ''}"
        return Input(
            value="" if spec.value is None else str(spec.value),
            placeholder=placeholder,
            id=self._wid(spec),
        )

    @staticmethod
    def _wid(spec: FieldSpec) -> str:
        return "f_" + spec.path.replace(".", "_")

    # -- change handlers ---------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply(event.select, str(event.value))

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._apply(event.switch, event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._apply(event.input, event.value)

    def _apply(self, widget, raw) -> None:
        spec = getattr(widget, "_spec", None)
        if spec is None or self._doc is None:
            return
        # Skip writes that would not change the value. This drops the
        # Changed event every widget emits as it mounts, and also keeps an
        # edit that lands back on the original from touching the file, so
        # saved profiles carry only real changes.
        if _same_value(raw, spec):
            return
        try:
            apply_edit(self._doc, spec.path, raw, spec.kind)
        except (ValueError, TypeError):
            self._status(f"{spec.name}: invalid value", error=True)
            return
        self._discard_armed = False
        if self._is_dirty():
            self._status("modified, ctrl+s to save")

    # -- save --------------------------------------------------------------

    def action_save(self) -> None:
        if self._doc is None or not self.profile_name:
            return
        try:
            path = profile_editor.save(self.profile_name, self._doc)
        except Exception as exc:
            self._status(f"not saved: {_first_error(exc)}", error=True)
            return
        self._baseline = profile_editor.dump_roundtrip(self._doc)  # now clean
        note = self._deploy_note()
        self._status(f"saved {path.name}. {note}")
        self.app.notify(f"saved {path.name}")

    def _deploy_note(self) -> str:
        """Warn that a defined domain must be redeployed for changes to land."""
        try:
            from vmw.infra.probe import domain_defined

            if self.app.host is not None and domain_defined(self.profile_name):
                return f"redeploy to apply: vmw deploy {self.profile_name}"
        except Exception:
            pass
        return "not yet deployed."

    def action_close(self) -> None:
        if self._is_dirty() and not self._discard_armed:
            self._status("unsaved changes, ctrl+s to save, or escape again to discard")
            self._discard_armed = True  # a second escape discards
            return
        self.app.pop_screen()

    def _status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#editor-status", Static)
        status.update(text)
        status.set_class(error, "error")


def _same_value(raw, spec: FieldSpec) -> bool:
    """True when raw equals the field's original value, per its kind."""
    if spec.kind == "switch":
        return bool(raw) == bool(spec.value)
    if spec.kind == "int":
        try:
            return int(raw) == int(spec.value)
        except (ValueError, TypeError):
            return False
    return str(raw) == ("" if spec.value is None else str(spec.value))


def _first_error(exc: Exception) -> str:
    """Compress a pydantic ValidationError to its first human message."""
    errs = getattr(exc, "errors", None)
    if callable(errs):
        items = errs()
        if items:
            loc = ".".join(str(p) for p in items[0].get("loc", ()))
            return f"{loc}: {items[0].get('msg', 'invalid')}"
    return str(exc).splitlines()[0]


class _FieldRow(Horizontal):
    """A label plus its generated input, laid out on one line."""

    def __init__(self, spec: FieldSpec, widget) -> None:
        super().__init__(classes="field-row")
        self._spec = spec
        self._widget = widget
        widget._spec = spec

    def compose(self) -> ComposeResult:
        yield Label(self._spec.name, classes="field-label")
        yield self._widget


class _NameScreen(Screen[str]):
    """One-line name prompt for a new profile."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New profile name", id="question")
            yield Label("letters, digits, dash, underscore    enter to continue", id="modal-help")
            yield Input(id="newname")

    def on_mount(self) -> None:
        self.query_one("#newname", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value and value.replace("-", "").replace("_", "").isalnum():
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss("")

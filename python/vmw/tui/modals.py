"""Modal screens: one per Prompt kind (plan 03).

Each modal maps 1:1 to a workflow Prompt kind and dismisses with the
answer string (or None when cancelled). PasswordScreen is the session
sudo capture [A2/B5]: the value is held in memory only and piped to
sudo -S by infra/sh.py. It is never logged and never persisted.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList


class _BaseModal(ModalScreen[str | None]):
    """Shared chrome: esc cancels (dismiss None)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(_BaseModal):
    """yes/no question -> 'y' or 'n' (replaces read -p).

    Answerable with a single key. The buttons are there for the mouse,
    but nobody should have to tab to one to say yes.
    """

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, question: str, default: str = "y"):
        super().__init__()
        self.question = question
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="question")
            yield Label("y = yes    n = no    esc = cancel", id="modal-help")
            with Horizontal(id="buttons"):
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_mount(self) -> None:
        self.query_one("#yes" if self.default == "y" else "#no", Button).focus()

    def action_yes(self) -> None:
        self.dismiss("y")

    def action_no(self) -> None:
        self.dismiss("n")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss("y" if event.button.id == "yes" else "n")


class ChoiceScreen(_BaseModal):
    """Pick exactly one option (distro / muarch menus).

    Uses OptionList, not SelectionList. SelectionList is a multi-select
    widget: it draws checkboxes, which tells the user they may pick
    several, and it has no "one was chosen" message. OptionList is the
    single-select widget and emits OptionSelected on enter or click.
    """

    def __init__(self, question: str, choices: tuple[str, ...], default: str | None = None):
        super().__init__()
        self.question = question
        self.choices = tuple(choices)
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="question")
            yield Label("up/down to move    enter to pick    esc to cancel", id="modal-help")
            yield OptionList(*self.choices, id="choices")

    def on_mount(self) -> None:
        options = self.query_one("#choices", OptionList)
        if self.default in self.choices:
            options.highlighted = self.choices.index(self.default)
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.choices[event.option_index])


class DeviceSelectScreen(ChoiceScreen):
    """GPU / device picker fed from lspci (same shape as ChoiceScreen)."""


class PathInputScreen(_BaseModal):
    """Free-text path entry with a non-empty validation (logo BMP)."""

    def __init__(self, question: str, default: str = ""):
        super().__init__()
        self.question = question
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="question")
            yield Input(value=self.default, id="path")
            yield Label("", id="error")

    def on_mount(self) -> None:
        self.query_one("#path", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        error = self.query_one("#error", Label)
        if not value:
            error.update("path cannot be empty")
            return
        # Catch the mistake here, where it costs a keystroke, rather than
        # part-way through a build.
        path = Path(value).expanduser()
        if not path.exists():
            error.update(f"no such file: {path}")
            return
        if not path.is_file():
            error.update(f"not a file: {path}")
            return
        self.dismiss(str(path))


class PasswordScreen(_BaseModal):
    """Session sudo password (VMW_SUDO formalized) [A2/B5].

    The input is masked; the value returns to the caller which hands it
    to RunContext.root. It is never written to disk or the run log.
    """

    def __init__(self, question: str = "sudo password for this session"):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="question")
            yield Input(password=True, id="password")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

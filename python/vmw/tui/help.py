"""Help overlay: every binding in one place (plan 07, D6)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

_SECTIONS = [
    (
        "Dashboard",
        [
            ("tab", "move between the profile rail and build list"),
            ("↑ ↓", "move within the focused region"),
            ("enter", "open the focused item (edit profile / rebuild step)"),
            ("e", "edit the selected profile"),
            ("n", "new profile"),
            ("r", "rebuild the focused build step"),
            ("p", "show the plan for the focused step (runs nothing)"),
            ("s", "full setup wizard"),
            ("l", "view the last build log"),
            ("q", "quit"),
        ],
    ),
    (
        "Editor",
        [
            ("↑ ↓", "move between fields"),
            ("ctrl+s", "validate and save"),
            ("escape", "close (twice to discard changes)"),
        ],
    ),
    (
        "Build screen",
        [
            ("c", "cancel after the current action"),
            ("escape", "back to the dashboard (the build keeps running)"),
        ],
    ),
]


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("question_mark", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Keys", id="help-title")
            for title, rows in _SECTIONS:
                yield Static(title, classes="help-section")
                for key, desc in rows:
                    yield Static(f"[b]{key:>8}[/b]   {desc}", classes="help-row")
            yield Static("esc to close", classes="help-foot")

    def action_close(self) -> None:
        self.dismiss(None)

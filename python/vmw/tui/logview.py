"""Log screen: view the most recent build log.

Reads the newest logs/<epoch>.log under the repo into a RichLog. Read
only. Escape returns to the dashboard.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog


class LogScreen(Screen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="log-title")
        yield Container(RichLog(max_lines=5000, id="log-view", wrap=True), id="log-view-wrap")
        yield Footer()

    def on_mount(self) -> None:
        log = self._latest_log()
        title = self.query_one("#log-title", Label)
        view = self.query_one("#log-view", RichLog)
        if log is None:
            title.update("no build logs yet")
            return
        title.update(str(log))
        try:
            from vmw.tui.build import style_log_line

            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                view.write(style_log_line(line))
        except OSError as exc:
            title.update(f"cannot read {log}: {exc}")

    def _latest_log(self) -> Path | None:
        logs = self.app.repo_root / "logs"
        if not logs.is_dir():
            return None
        files = sorted(logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def action_close(self) -> None:
        self.app.pop_screen()

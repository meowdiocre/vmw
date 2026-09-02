"""Build screen: stream a run, cancel safely (plan 03).

RichLog(max_lines=5000) streams action output. An indeterminate
ProgressBar shows activity. The header shows the current action. The
worker attaches to the App node, not this screen, so navigating away
does not cancel the build.

Cancel sets the context's cancel_event. The engine checks it between
actions [A5]. state.json keys are written only when an action succeeds.
A cancelled source tree is cleaned by the next rebuild's reset Action.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ProgressBar, RichLog

# Words that decide how a build line is coloured. Kept here so the build
# screen and the log viewer render the same output identically.
_ERROR_WORDS = ("error", "failed", "failure", "fatal", "cannot", "no such")
_WARN_WORDS = ("warning", "warn:", "skipping", "deprecated")


def style_log_line(line: str) -> Text:
    """Colour one build line: errors red, warnings yellow, engine steps bold.

    Forty minutes of makepkg output scrolls past here. Without this the
    one line that matters looks exactly like the 3000 that do not.
    """
    lowered = line.lower()
    if any(word in lowered for word in _ERROR_WORDS):
        return Text(line, style="bold red")
    if any(word in lowered for word in _WARN_WORDS):
        return Text(line, style="yellow")
    # Engine progress lines look like "[qemu] probe: done".
    if line.startswith("[") and "]" in line:
        return Text(line, style="bold")
    # Echoed commands, dimmed so real output stands out.
    if line.lstrip().startswith("$ "):
        return Text(line, style="dim")
    return Text(line)


class BuildScreen(Screen[None]):
    BINDINGS = [
        Binding("c", "cancel", "Cancel build"),
        # Say plainly that leaving does not stop the build, or a user who
        # wants to stop it will press escape and believe they have.
        Binding("escape", "close", "Back (keeps building)"),
    ]

    def __init__(self, steps, profile):
        super().__init__()
        self.steps = steps
        self.profile = profile
        self._finished = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="build-header")
        yield ProgressBar(total=None, show_eta=False, id="progress")
        yield Container(RichLog(max_lines=5000, id="log", wrap=True), id="log-wrap")
        yield Footer()

    def on_mount(self) -> None:
        names = ", ".join(s.name for s in self.steps)
        self.query_one("#build-header", Label).update(f"building {self.profile.name}: {names}")
        self.app.start_build(self.steps, self.profile, self._on_build_done, target=self)

    def _emit(self, line: str) -> None:
        """Append one line to the RichLog and track the current action."""
        try:
            self.app.call_from_thread(self._render_line, line)
        except Exception:
            pass  # screen closed; the App-node worker keeps running

    def _render_line(self, line: str) -> None:
        self.query_one("#log", RichLog).write(style_log_line(line))
        if not self._finished:
            header = self._header_for(line)
            if header is not None:
                self.query_one("#build-header", Label).update(header)

    def _header_for(self, line: str) -> str | None:
        """Map an engine log line to a header, or None to leave it as is."""
        # Engine lines look like "[qemu] probe: done" or "[qemu] complete".
        if line.startswith("[") and "]" in line:
            step = line[1 : line.index("]")]
            rest = line[line.index("]") + 2 :]
            if rest.startswith("probe:"):
                return f"{self.profile.name}: running {step}"
            if rest == "complete":
                return f"{self.profile.name}: {step} done"
        return None

    def _on_build_done(self, rc: int, error: str | None) -> None:
        def apply() -> None:
            self._finished = True
            self.query_one("#progress", ProgressBar).display = False
            header = self.query_one("#build-header", Label)
            header.remove_class("done", "failed", "cancelled")
            if error:
                header.update(f"build error: {error}")
                header.add_class("failed")
            elif rc == 130:
                header.update("build cancelled. the next rebuild resets the source tree.")
                header.add_class("cancelled")
            elif rc == 0:
                header.update("build complete. press escape to return.")
                header.add_class("done")
            else:
                header.update(f"build finished with rc={rc}. see the log above.")
                header.add_class("failed")

        self.app.call_from_thread(apply)

    def action_cancel(self) -> None:
        if self._finished:
            return
        self.app.cancel_build()
        self.query_one("#build-header", Label).update("cancelling after the current action...")

    def action_close(self) -> None:
        # The worker is on the App node. Closing the screen leaves it running.
        self.app.pop_screen()

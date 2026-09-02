"""Setup wizard: profile -> steps -> summary -> Run (plan 03).

Three pages in one screen. Page 1 lists configs/*.yml; page 2 is a step
checklist pre-checked where probe() == DONE (a focused rebuild via the
dashboard pre-selects just that step); page 3 renders the probe-driven
plan preview and a Run button that opens the build screen.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    SelectionList,
)
from textual.widgets.selection_list import Selection

from vmw.infra.probe import State
from vmw.workflow.prompt import PromptAnswers


class WizardScreen(Screen[None]):
    # Everything here must be reachable without a mouse. Buttons stay for
    # people who want them, but no operation requires tabbing to one.
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("left", "back", "Back", show=False),
        Binding("right", "next", "Next"),
        Binding("ctrl+r", "run", "Run"),
    ]

    PAGES = ("profile", "steps", "summary")

    def __init__(self, focus_step: str | None = None, plan_only: bool = False):
        super().__init__()
        self.focus_step = focus_step
        self.plan_only = plan_only
        self.page = 0
        self.profile_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Setup wizard", id="wizard-title")
        with Container(id="pages"):
            with Vertical(id="page-profile", classes="page"):
                yield Label("Choose a profile", classes="page-title")
                yield ListView(id="profile-list")
            with Vertical(id="page-steps", classes="page"):
                yield Label("Steps to run", classes="page-title")
                yield SelectionList(id="step-list")
            with Vertical(id="page-summary", classes="page"):
                yield Label("Summary", classes="page-title")
                yield Label("", id="summary-text")
        with Horizontal(id="wizard-nav"):
            yield Button("Back", id="back")
            yield Button("Next", id="next", variant="primary")
            yield Button("Run", id="run", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        if self.plan_only:
            self.query_one("#wizard-title", Label).update("Plan (nothing will run)")
        self._populate_profiles()
        # A focused rebuild/plan lands on the summary for that one step;
        # a full setup starts at the profile list.
        self._show_page(2 if self.focus_step is not None else 0)

    def _populate_profiles(self) -> None:
        lv = self.query_one("#profile-list", ListView)
        names = self.app.profiles()
        for name in names:
            lv.append(ListItem(Label(name), id=f"prof-{name}"))
        if names:
            # Without an initial highlight the list has no current item and
            # enter does nothing at all, which reads as a dead keyboard.
            lv.index = 0
            if self.profile_name is None:
                self.profile_name = names[0]

    def _populate_steps(self) -> None:
        sl = self.query_one("#step-list", SelectionList)
        sl.clear_options()
        steps = self.app.ordered_steps()
        host = self.app.host
        for step in steps:
            try:
                state = step.probe(host) if host is not None else State.MISSING
            except Exception:
                state = State.MISSING
            done = state is State.DONE
            if self.focus_step is not None:
                selected = step.name == self.focus_step
            else:
                selected = not done  # pre-check the work that remains
            label = self._step_label(step, state)
            sl.add_option(Selection(label, step.name, id=step.name, initial_state=selected))

    def _step_label(self, step, state: State) -> str:
        """Step name plus probe state; deploy shows the target domain."""
        if step.name == "deploy" and self.profile_name:
            try:
                domain = self.app.load_profile(self.profile_name).domain_name
                return f"{step.name} ({domain}) [{state.value}]"
            except Exception:
                pass
        return f"{step.name} [{state.value}]"

    def _populate_summary(self) -> None:
        selected = self._selected_steps()
        lines = [f"profile: {self.profile_name}", f"steps: {', '.join(selected) or '(none)'}", ""]
        plan_lines = self._plan_preview(selected)
        lines += plan_lines or ["(nothing to do; every selected step is done)"]
        self.query_one("#summary-text", Label).update("\n".join(lines))

    def _plan_preview(self, selected: list[str]) -> list[str]:
        if self.profile_name is None:
            return []
        try:
            profile = self.app.load_profile(self.profile_name)
        except Exception as exc:
            return [f"cannot load profile: {exc}"]
        host = self.app.host
        out: list[str] = []
        answers = PromptAnswers()
        for name in selected:
            step = self.app.step_by_name(name)
            if step is None:
                continue
            try:
                for prompt in step.prompts(profile):
                    answers.set(prompt.id, answers.answer(prompt))
                actions = step.plan(profile, host, answers)
            except Exception as exc:
                out.append(f"[{name}] plan error: {exc}")
                continue
            out.append(f"[{name}]")
            out += [f"  {a.shell_line()}" for a in actions] or ["  (nothing to do)"]
        return out

    def _selected_steps(self) -> list[str]:
        sl = self.query_one("#step-list", SelectionList)
        return [str(v) for v in sl.selected]

    def _show_page(self, index: int) -> None:
        self.page = max(0, min(index, len(self.PAGES) - 1))
        current = self.PAGES[self.page]
        for page_id in self.PAGES:
            widget = self.query_one(f"#page-{page_id}")
            widget.display = page_id == current
        if current == "steps":
            self._populate_steps()
        if current == "summary":
            self._populate_summary()
        # In focused mode Back closes rather than paging, so label it honestly.
        back = self.query_one("#back", Button)
        back.display = self.page > 0
        back.label = "Close" if self.focus_step is not None else "Back"
        self.query_one("#next", Button).display = self.page < len(self.PAGES) - 1
        # Plan-only never offers Run: the whole point is to look without acting.
        run = self.query_one("#run", Button)
        run.display = self.page == len(self.PAGES) - 1 and not self.plan_only
        self._focus_page(current)

    def _focus_page(self, current: str) -> None:
        """Put the keyboard where the work is for this page.

        Focus must never be left on a hidden widget, or every key press
        goes nowhere and the app looks frozen.
        """
        if current == "profile":
            self.query_one("#profile-list", ListView).focus()
        elif current == "steps":
            self.query_one("#step-list", SelectionList).focus()
        else:
            run = self.query_one("#run", Button)
            # On the summary, enter should run. In plan-only there is
            # nothing to run, so park on the close button instead.
            (run if run.display else self.query_one("#back", Button)).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id.startswith("prof-"):
            self.profile_name = item_id[len("prof-") :]
            self._show_page(1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Buttons are a convenience; they route to the same actions as keys."""
        bid = event.button.id
        if bid == "next":
            self.action_next()
        elif bid == "back":
            self.action_back()
        elif bid == "run":
            self._run()

    def action_next(self) -> None:
        """Advance one page. Never starts a build.

        Paging and running are deliberately different keys. An arrow key
        that reaches the last page and then launches a real build is a
        trap: the user is navigating, not consenting.
        """
        if self.page < len(self.PAGES) - 1:
            self._capture_highlighted_profile()
            self._show_page(self.page + 1)
        elif not self.plan_only:
            self.app.notify("press ctrl+r or enter on Run to start", severity="information")

    def action_run(self) -> None:
        if self.plan_only:
            self.app.notify("plan view only; press escape and use enter to rebuild")
            return
        self._run()

    def _capture_highlighted_profile(self) -> None:
        """Take the highlighted profile even if enter was never pressed."""
        if self.page != 0:
            return
        lv = self.query_one("#profile-list", ListView)
        names = self.app.profiles()
        if lv.index is not None and 0 <= lv.index < len(names):
            self.profile_name = names[lv.index]

    def action_back(self) -> None:
        # A focused rebuild or plan opens straight at the summary, so the
        # earlier pages were never visited. Walking back into them would
        # strand the user in a wizard they did not start: one key opened
        # this, one key closes it.
        if self.page == 0 or self.focus_step is not None:
            self.app.pop_screen()
        else:
            self._show_page(self.page - 1)

    def _run(self) -> None:
        selected = self._selected_steps()
        if not selected:
            self.app.notify("no steps selected", severity="warning")
            return
        if self.profile_name is None:
            self.app.notify("no profile selected", severity="warning")
            return
        try:
            profile = self.app.load_profile(self.profile_name)
        except Exception as exc:
            self.app.notify(f"cannot load profile: {exc}", severity="error")
            return
        steps = [self.app.step_by_name(n) for n in selected]
        steps = [s for s in steps if s is not None]
        from vmw.tui.build import BuildScreen

        self.app.push_screen(BuildScreen(steps, profile))

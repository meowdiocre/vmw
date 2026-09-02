"""Dashboard: three-region operations view (plan 07).

Top bar of live host/guest telemetry, a profile rail on the left, and a
right pane split into build state and the selected domain's facts. Every
number shown is one the host can measure; guest-side detector numbers
are deliberately absent (they cannot be observed from here).

Fully operable without a mouse: tab moves between regions, arrows move
within one, and every action has a key.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, ListItem, ListView, Static

from vmw.infra.metrics import HostSampler, sample_domain
from vmw.infra.probe import State
from vmw.tui.topbar import TopBar

# state -> (glyph, rich style)
GLYPH = {
    State.DONE: ("✔", "green"),
    State.PARTIAL: ("◐", "yellow"),
    State.MISSING: ("✖", "red"),
    State.STALE: ("↻", "magenta"),
}

# Poll host telemetry this often. Two seconds keeps the cost negligible
# on a machine that is already thermally limited (plan 07 risks).
POLL_SECONDS = 2.0


class DashboardScreen(Screen[None]):
    BINDINGS = [
        Binding("tab", "focus_next_region", "Next region", show=False),
        Binding("enter", "open", "Open", priority=True),
        Binding("e", "edit_profile", "Edit"),
        Binding("n", "new_profile", "New"),
        Binding("r", "rebuild", "Rebuild"),
        Binding("p", "plan", "Plan"),
        Binding("s", "setup", "Setup"),
        Binding("l", "log", "Log"),
        Binding("question_mark", "help", "Help"),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield TopBar()
        with Horizontal(id="body"):
            with Vertical(id="rail"):
                yield Static("PROFILES", classes="rail-title")
                yield ListView(id="profiles")
                yield Static("", id="rail-hint")
            with Vertical(id="mainpane"):
                yield Static("BUILD STATE", classes="pane-title")
                yield DataTable(id="steps")
                yield Static("DOMAIN", classes="pane-title", id="domain-title")
                yield Static("", id="domain-facts")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("", "step", "detail", "built")
        self._populate_profiles()
        self.refresh_probes()
        self._sampler = HostSampler()
        self.set_interval(POLL_SECONDS, self._poll)
        self._poll()  # first paint immediately
        self.query_one("#profiles", ListView).focus()

    def on_screen_resume(self) -> None:
        self.refresh_probes()

    # -- live telemetry ----------------------------------------------------

    def _poll(self) -> None:
        bar = self.query_one(TopBar)
        try:
            bar.update_host(self._sampler.sample())
        except Exception:
            pass  # never let a sampling hiccup kill the UI
        name = self._selected_profile_domain()
        if name:
            bar.update_guest(name, sample_domain(name))

    def action_refresh(self) -> None:
        self.refresh_probes()
        self._update_domain_facts()

    # -- profiles rail -----------------------------------------------------

    def _populate_profiles(self) -> None:
        lv = self.query_one("#profiles", ListView)
        lv.clear()
        names = self.app.profiles()
        for name in names:
            lv.append(ListItem(Static(name, classes="profile-name"), id=f"prof-{name}"))
        if names:
            lv.index = 0
        hint = self.query_one("#rail-hint", Static)
        hint.update("n new   e edit" if names else "no profiles. n to create one.")

    def _selected_profile_name(self) -> str | None:
        lv = self.query_one("#profiles", ListView)
        names = self.app.profiles()
        if lv.index is not None and 0 <= lv.index < len(names):
            return names[lv.index]
        return None

    def _selected_profile_domain(self) -> str | None:
        name = self._selected_profile_name()
        if name is None:
            return None
        try:
            return self.app.load_profile(name).domain_name
        except Exception:
            return name

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        # Moving the rail selection re-targets the guest bar and detail pane.
        self._update_domain_facts()
        name = self._selected_profile_domain()
        if name:
            self.query_one(TopBar).update_guest(name, sample_domain(name))

    # -- build-state table -------------------------------------------------

    def refresh_probes(self) -> None:
        host = self.app.host
        table = self.query_one(DataTable)
        table.clear()
        self._row_states = []
        if host is None:
            self.query_one("#rail-hint", Static).update("host detection failed")
            return
        from vmw.steps import registry

        domain = self._selected_profile_domain()
        rows = registry.probe_all(host, domain=domain)
        hashes = self._build_hashes()
        for row in rows:
            glyph, style = GLYPH[row.state]
            self._row_states.append(row)
            table.add_row(
                Text(glyph, style=style),
                row.name,
                row.detail or "-",
                hashes.get(row.name, "-"),
                key=row.name,
            )

    def _build_hashes(self) -> dict[str, str]:
        try:
            from vmw.workflow.context import StateStore

            store = StateStore.open(self.app.state_path())
        except Exception:
            return {}
        out: dict[str, str] = {}
        for key, value in store.values.items():
            if key.startswith("values.") and key.endswith(".build_hash") and value:
                step = key[len("values.") : -len(".build_hash")]
                out[step] = f"hash {value[:8]}"
        return out

    # -- domain facts pane -------------------------------------------------

    def _update_domain_facts(self) -> None:
        name = self._selected_profile_name()
        title = self.query_one("#domain-title", Static)
        body = self.query_one("#domain-facts", Static)
        if name is None:
            title.update("DOMAIN")
            body.update(Text("select a profile", style="dim"))
            return
        try:
            from vmw.infra.domain_facts import read_domain_facts

            profile = self.app.load_profile(name)
            facts = read_domain_facts(profile.domain_name, profile=profile)
        except Exception as exc:
            body.update(Text(f"cannot read domain: {exc}", style="red"))
            return
        title.update(f"DOMAIN  {facts.name}   ({facts.source_label})")
        line = Text(overflow="fold")
        line.append(f"disk {facts.disk_bus} {facts.disk_size}    ")
        line.append(f"net {facts.network} {facts.mac}\n")
        line.append(f"gpu {facts.gpu}    tpm {facts.tpm}    hvci {facts.hvci}\n")
        line.append(f"firmware {facts.firmware}")
        body.update(line)

    # -- actions -----------------------------------------------------------

    def _focused_step_name(self) -> str | None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or not self._row_states:
            return None
        try:
            return self._row_states[table.cursor_row].name
        except IndexError:
            return None

    def _focused_region(self) -> str:
        focused = self.app.focused
        if focused is None:
            return "rail"
        node = focused
        while node is not None:
            if getattr(node, "id", None) == "steps":
                return "steps"
            if getattr(node, "id", None) == "profiles":
                return "rail"
            node = node.parent
        return "rail"

    def action_focus_next_region(self) -> None:
        if self._focused_region() == "rail":
            self.query_one("#steps", DataTable).focus()
        else:
            self.query_one("#profiles", ListView).focus()

    def action_open(self) -> None:
        """Enter: rebuild the focused step, or open the focused profile."""
        if self._focused_region() == "steps":
            self.action_rebuild()
        else:
            self.action_edit_profile()

    def action_setup(self) -> None:
        from vmw.tui.wizard import WizardScreen

        self.app.push_screen(WizardScreen())

    def action_rebuild(self) -> None:
        name = self._focused_step_name()
        if name is None:
            self.app.notify("no step selected", severity="warning")
            return
        from vmw.tui.wizard import WizardScreen

        self.app.push_screen(WizardScreen(focus_step=name))

    def action_plan(self) -> None:
        name = self._focused_step_name()
        if name is None:
            self.app.notify("no step selected", severity="warning")
            return
        from vmw.tui.wizard import WizardScreen

        self.app.push_screen(WizardScreen(focus_step=name, plan_only=True))

    def action_edit_profile(self) -> None:
        name = self._selected_profile_name()
        if name is None:
            self.app.notify("no profile selected", severity="warning")
            return
        from vmw.tui.editor import ProfileEditorScreen

        self.app.push_screen(ProfileEditorScreen(name))

    def action_new_profile(self) -> None:
        from vmw.tui.editor import ProfileEditorScreen

        self.app.push_screen(ProfileEditorScreen(None))

    def action_log(self) -> None:
        from vmw.tui.logview import LogScreen

        self.app.push_screen(LogScreen())

    def action_help(self) -> None:
        from vmw.tui.help import HelpScreen

        self.app.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.app.exit()

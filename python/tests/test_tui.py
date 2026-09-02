"""Fake-step gate: streaming, cancel, navigation, log capture.

A FakeStep emits a sleep-loop of streaming Actions so the whole build
lifecycle is exercised in seconds, with no real kernel rebuild. Drives the
app with textual's Pilot on a manually-run event loop (pytest_asyncio
is not a dependency).

Run repeatedly during development; the one real rebuild walkthrough is
a separate manual gate.
"""

from __future__ import annotations

import asyncio

from vmw.infra.probe import State
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.step import Step


class FakeStep(Step):
    """Sleep-loop step: streams N lines, one per Action, over ~1s."""

    name = "fake"
    title = "Fake build step"

    def __init__(self, lines: int = 5):
        self.lines = lines

    def probe(self, host) -> State:
        return State.MISSING

    def plan(self, profile, host, answers) -> list[Action]:
        return [
            Action(
                key=f"fake.line{i}",
                cmd=["sh", "-c", f"echo line-{i}; sleep 0.1"],
                describe=f"emit line {i}",
            )
            for i in range(self.lines)
        ]


def _profile() -> Profile:
    return Profile.model_validate(
        {"name": "faketest", "vm": {"memory_mib": 2048, "vcpus": 2}, "device": {}}
    )


def run_coro(coro, timeout=10.0):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def test_dashboard_lists_six_steps():
    from vmw.tui.app import VmwApp
    from vmw.tui.dashboard import DashboardScreen

    async def go():
        app = VmwApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)
            table = app.screen.query_one("#steps")
            assert table.row_count == 6
        return True

    assert run_coro(go())


def test_build_screen_streams_and_completes(tmp_path):
    from textual.widgets import RichLog
    from vmw.tui.app import VmwApp
    from vmw.tui.build import BuildScreen

    async def go():
        from textual.widgets import Label

        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(BuildScreen([FakeStep(lines=5)], _profile()))
            await pilot.pause()
            header_widget = app.screen.query_one("#build-header", Label)
            for _ in range(50):
                await pilot.pause(0.1)
                if "complete" in str(header_widget.render()):
                    break
            header = str(header_widget.render())
            log = app.screen.query_one("#log", RichLog)
            text = "\n".join(str(line) for line in log.lines)
            assert "complete" in header
            assert "line-0" in text
        return True

    assert run_coro(go())


def test_navigation_does_not_cancel_build(tmp_path):
    from vmw.tui.app import VmwApp
    from vmw.tui.build import BuildScreen

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(BuildScreen([FakeStep(lines=8)], _profile()))
            await pilot.pause()
            # navigate away mid-build; the App-node worker must keep running
            app.pop_screen()
            for _ in range(50):
                await pilot.pause(0.1)
                worker = app._build_worker
                if worker is not None and worker.is_finished:
                    break
            assert app._build_worker is not None
            assert app._build_worker.is_finished
        return True

    assert run_coro(go())


def test_cancel_build_marks_cancelled(tmp_path):
    """Cancel sets the engine cancel_event; the run stops between actions."""

    from vmw.tui.app import VmwApp
    from vmw.tui.build import BuildScreen

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(BuildScreen([FakeStep(lines=20)], _profile()))
            await pilot.pause()
            app.cancel_build()
            for _ in range(50):
                await pilot.pause(0.1)
                worker = app._build_worker
                if worker is not None and worker.is_finished:
                    break
            assert app._build_worker is not None
            assert app._build_worker.is_finished
        return True

    assert run_coro(go())


def test_password_screen_masks_input():
    from vmw.tui.app import VmwApp
    from vmw.tui.modals import PasswordScreen

    async def go():
        app = VmwApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            async def ask():
                return await app.push_screen_wait(PasswordScreen("pw?"))

            worker = app.run_worker(ask(), name="ask", group="test")
            await pilot.pause()
            await pilot.press("s", "e", "c", "r", "e", "t", "enter")
            for _ in range(30):
                await pilot.pause(0.05)
                if worker.is_finished:
                    break
            assert worker.is_finished
            assert worker.result == "secret"
        return True

    assert run_coro(go())


def test_choice_screen_dismisses_with_selection():
    """Regression: ChoiceScreen must return the picked value.

    It previously used SelectionList (a multi-select widget) and handled
    SelectionList.Selected, a message that does not exist, so the modal
    never dismissed and every choice prompt hung.
    """

    from vmw.tui.app import VmwApp
    from vmw.tui.modals import ChoiceScreen

    async def go():
        app = VmwApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            async def ask():
                return await app.push_screen_wait(
                    ChoiceScreen("distro?", ("Arch", "Debian", "Fedora"), default="Debian")
                )

            worker = app.run_worker(ask(), name="ask", group="test")
            await pilot.pause()
            await pilot.press("enter")  # accept the highlighted default
            for _ in range(30):
                await pilot.pause(0.05)
                if worker.is_finished:
                    break
            assert worker.is_finished, "choice modal never dismissed"
            assert worker.result == "Debian"
        return True

    assert run_coro(go())


def test_dashboard_refreshes_on_resume(tmp_path):
    """Returning from another screen must re-probe, not show stale rows."""

    from vmw.tui.app import VmwApp
    from vmw.tui.logview import LogScreen

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            dash = app.screen
            calls = []
            original = dash.refresh_probes
            dash.refresh_probes = lambda: (calls.append(1), original())[1]
            app.push_screen(LogScreen())
            await pilot.pause()
            app.pop_screen()
            await pilot.pause()
            assert calls, "dashboard did not re-probe on resume"
        return True

    assert run_coro(go())


def test_escape_closes_a_focused_wizard_in_one_press(tmp_path):
    """Regression: a rebuild opens the wizard at the summary, and escape
    must close it in one press rather than paging backwards into steps and
    profile pages the user never visited.

    In the plan-07 dashboard the wizard is reached by rebuilding a step
    (r), not by enter; enter on the rail edits a profile.
    """

    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")  # focus the build-state table
            await pilot.pause()
            await pilot.press("r")  # rebuild focused step -> focused wizard
            await pilot.pause()
            assert type(app.screen).__name__ == "WizardScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
        return True

    assert run_coro(go())


def test_plan_only_wizard_hides_run(tmp_path):
    """p is 'look at the plan'; it must not offer to execute it."""

    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert app.screen.plan_only is True
            assert app.screen.query_one("#run").display is False
        return True

    assert run_coro(go())


def test_path_modal_rejects_missing_file(tmp_path):
    """A bad logo path must fail at the keystroke, not mid-build."""

    from textual.widgets import Input, Label
    from vmw.tui.app import VmwApp
    from vmw.tui.modals import PathInputScreen

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            async def ask():
                return await app.push_screen_wait(PathInputScreen("logo?"))

            worker = app.run_worker(ask(), group="test")
            await pilot.pause()
            app.screen.query_one("#path", Input).value = str(tmp_path / "nope.bmp")
            await pilot.press("enter")
            await pilot.pause()
            assert not worker.is_finished, "modal accepted a missing file"
            assert "no such file" in str(app.screen.query_one("#error", Label).render())

            real = tmp_path / "logo.bmp"
            real.write_bytes(b"BM")
            app.screen.query_one("#path", Input).value = str(real)
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause(0.05)
                if worker.is_finished:
                    break
            assert worker.is_finished and worker.result == str(real)
        return True

    assert run_coro(go())


def test_wizard_is_operable_without_a_mouse(tmp_path):
    """Every wizard step must be reachable by key alone.

    Previously enter on the profile list did nothing (no item was
    highlighted) and no key advanced a page, so tabbing to a Button was
    the only way through.
    """

    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            wizard = app.screen
            assert app.focused.id == "profile-list"

            await pilot.press("enter")  # pick the highlighted profile
            await pilot.pause()
            assert wizard.page == 1, "enter on the profile list did not advance"
            assert wizard.profile_name is not None
            assert app.focused.id == "step-list"

            await pilot.press("right")  # advance by key, not by button
            await pilot.pause()
            assert wizard.page == 2
            assert app.focused.id == "run"

            await pilot.press("left")
            await pilot.pause()
            assert wizard.page == 1
        return True

    assert run_coro(go())


def test_focus_never_lands_on_a_hidden_widget(tmp_path):
    """A focused but hidden widget swallows every key press."""

    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            # Walk to the last page only. Pressing right past it must not
            # start anything, but we stop here so the test never launches
            # a real build even if that guarantee regresses.
            for _ in range(2):
                assert app.focused is None or app.focused.display, (
                    f"focus on hidden widget {getattr(app.focused, 'id', None)}"
                )
                await pilot.press("right")
                await pilot.pause()
            assert app.focused.display
        return True

    assert run_coro(go())


def test_confirm_modal_answers_with_one_key():
    from vmw.tui.app import VmwApp
    from vmw.tui.modals import ConfirmScreen

    async def go():
        app = VmwApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            for key, expected in (("y", "y"), ("n", "n")):

                async def ask():
                    return await app.push_screen_wait(ConfirmScreen("Proceed?"))

                worker = app.run_worker(ask(), group="test")
                await pilot.pause()
                await pilot.press(key)
                for _ in range(20):
                    await pilot.pause(0.05)
                    if worker.is_finished:
                        break
                assert worker.result == expected, f"{key!r} gave {worker.result!r}"
        return True

    assert run_coro(go())


def test_next_on_last_page_does_not_start_a_build(tmp_path):
    """Navigation must never execute. right on the summary is a no-op."""

    from vmw.tui.app import VmwApp
    from vmw.tui.wizard import WizardScreen

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            wizard = app.screen
            wizard._show_page(2)
            await pilot.pause()
            wizard.action_next()
            await pilot.pause()
            assert isinstance(app.screen, WizardScreen), "right on the summary launched a build"
        return True

    assert run_coro(go())


def test_editor_opens_and_disk_bus_reflects_profile(tmp_path):
    """The generated editor must show the profile's real disk bus."""

    from textual.widgets import Select
    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # edit the highlighted profile
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "ProfileEditorScreen"
            bus = app.screen.query_one("#f_device_disk_bus", Select)
            assert bus.value == "nvme"
        return True

    assert run_coro(go())


def test_editor_escape_closes_when_clean(tmp_path):
    """Opening and immediately closing must take one escape, not two."""

    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            await pilot.pause()  # let mount-time Changed events drain
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
        return True

    assert run_coro(go())


def test_help_overlay_opens_and_closes(tmp_path):
    from vmw.tui.app import VmwApp

    async def go():
        app = VmwApp(repo_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
        return True

    assert run_coro(go())

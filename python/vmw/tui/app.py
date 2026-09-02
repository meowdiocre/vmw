"""VmwApp: the dashboard-first Textual frontend (ADR-004).

Adapter only. Every operation is also a CLI subcommand; the TUI adds no
logic of its own. Workers attach to the App node, never a screen, so
navigation does not cancel builds [plan 03]. The prompt sink bridges
workflow Prompts to modals from inside a running worker via
call_from_thread and push_screen_wait.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App
from textual.worker import Worker

from vmw.infra.host import detect_host
from vmw.profiles.loader import discover, load_config
from vmw.steps import registry
from vmw.tui.modals import (
    ChoiceScreen,
    ConfirmScreen,
    DeviceSelectScreen,
    PasswordScreen,
    PathInputScreen,
)
from vmw.workflow.context import RunContext, StateStore
from vmw.workflow.engine import Engine, default_log_file
from vmw.workflow.prompt import Prompt

REPO_ROOT = Path(__file__).resolve().parents[3]


class VmwApp(App[None]):
    """The vmw TUI application."""

    CSS_PATH = "app.tcss"
    TITLE = "vmw"
    SUB_TITLE = "detection-resistant KVM workspace"

    def __init__(self, repo_root: Path | None = None):
        super().__init__()
        self.repo_root = repo_root or REPO_ROOT
        self.host = None
        self._build_worker: Worker | None = None

    def on_mount(self) -> None:
        from vmw.tui.dashboard import DashboardScreen

        try:
            self.host = detect_host()
        except Exception as exc:  # host detect must not kill the TUI
            self.notify(f"host detect failed: {exc}", severity="warning")
        self.push_screen(DashboardScreen())

    def make_context(self, emit) -> RunContext:
        """RunContext wired to TUI sinks (RichLog emit + modal prompts)."""
        return RunContext(
            dry_run=False,
            host=self.host,
            log_sink=emit,
            line_sink=emit,
            prompt_sink=self._prompt_bridge,
            state_store=StateStore.open(self.repo_root / ".vmw" / "state.json"),
            log_file=default_log_file(self.repo_root),
            repo_root=self.repo_root,
        )

    def make_engine(self, ctx: RunContext) -> Engine:
        return Engine(ctx, repo_root=self.repo_root)

    def _prompt_bridge(self, prompt: Prompt) -> str:
        """Route a Prompt to the right modal; block the worker for the answer."""
        future = asyncio.run_coroutine_threadsafe(self._ask_async(prompt), self._loop)
        answer = future.result()
        if answer is None:  # user pressed escape on the modal
            raise InterruptedError(f"prompt '{prompt.id or prompt.kind}' cancelled")
        return answer

    async def _ask_async(self, prompt: Prompt) -> str | None:
        if prompt.kind == "password":
            return await self.push_screen_wait(PasswordScreen(prompt.question))
        if prompt.kind == "confirm":
            return await self.push_screen_wait(
                ConfirmScreen(prompt.question, default=prompt.default or "y")
            )
        if prompt.kind == "choice":
            return await self.push_screen_wait(
                ChoiceScreen(prompt.question, prompt.choices, default=prompt.default)
            )
        if prompt.kind == "device":
            return await self.push_screen_wait(
                DeviceSelectScreen(prompt.question, prompt.choices, default=prompt.default)
            )
        if prompt.kind == "path":
            return await self.push_screen_wait(
                PathInputScreen(prompt.question, default=prompt.default or "")
            )
        return prompt.default or ""

    def start_build(self, steps, profile, on_done, target=None) -> None:
        """Launch a build on an App-node worker. target is the BuildScreen to stream into."""
        self._build_on_done = on_done
        self._build_target = target
        self._build_worker = self._run_build(steps, profile)

    def cancel_build(self) -> None:
        # Signal the engine to stop after the current action. The engine
        # checks cancel_event between actions [A5]; it returns rc=130.
        # We do not call worker.cancel(): the engine runs blocking
        # subprocess I/O with no await points, so a thread cancel is
        # unreliable and could orphan a sudo child.
        ctx = getattr(self, "_build_ctx", None)
        if ctx is not None and ctx.cancel_event is not None:
            ctx.cancel_event.set()

    @work(exclusive=True, exit_on_error=False, thread=True, group="build")
    def _run_build(self, steps, profile) -> None:
        """Engine run on a worker thread; streams into the originating build screen."""
        import threading

        def emit(line: str) -> None:
            target = getattr(self, "_build_target", None)
            if target is not None and target.is_attached:
                target._emit(line)

        on_done = getattr(self, "_build_on_done", None)
        rc = 0
        error: str | None = None
        ctx = self.make_context(emit)
        ctx.cancel_event = threading.Event()
        self._build_ctx = ctx
        engine = self.make_engine(ctx)
        try:
            engine.acquire()
        except Exception as exc:
            if on_done:
                on_done(1, str(exc))
            return
        try:
            rc = engine.run_steps(steps, profile, self.host)
        except InterruptedError as exc:
            rc, error = 130, str(exc)
        except Exception as exc:  # engine boundary already logged it
            rc, error = 1, str(exc)
        finally:
            engine.release()
        if on_done:
            on_done(rc, error)

    def profiles(self) -> list[str]:
        return discover()

    def load_profile(self, name: str):
        return load_config(name)

    def ordered_steps(self):
        return registry.ordered()

    def step_by_name(self, name: str):
        return registry.by_name(name)

    def state_path(self) -> Path:
        return self.repo_root / ".vmw" / "state.json"

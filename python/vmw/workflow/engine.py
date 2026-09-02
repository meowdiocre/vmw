"""Engine: sequence, skip, persist, report, single-writer flock [A4].

The one runner behind both frontends. Acquires an exclusive flock on
.vmw/ at start; a second concurrent run exits naming the holder's
PID. dry_run returns the plan without executing anything. Plans are
probe-driven: plan(profile, host, answers) decides what runs; the
engine never re-derives skip logic itself (the bash vmw::steps
mistake). Here the caller's probe, not the runner, owns skipping.
"""

from __future__ import annotations

import errno
import fcntl
import os
import signal
import subprocess
from pathlib import Path
from typing import IO

from vmw.infra.host import Host
from vmw.infra.probe import State
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.step import Step

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_FILE = REPO_ROOT / ".vmw" / "lock"


class ConcurrentRunError(RuntimeError):
    """Another vmw engine holds the .vmw/ write lock."""


class Engine:
    """Runs steps' plans; the only writer of state.json."""

    def __init__(self, ctx: RunContext, repo_root: Path | None = None):
        self.ctx = ctx
        self.repo_root = repo_root or REPO_ROOT
        self._lock_handle: IO | None = None
        self._proc: subprocess.Popen | None = None

    def acquire(self) -> None:
        """Take the single-writer flock or fail naming the holder PID."""
        lock_path = self.repo_root / ".vmw" / "lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                holder = _lock_holder(lock_path)
                raise ConcurrentRunError(
                    f"another vmw run holds {lock_path}" + (f" (pid {holder})" if holder else "")
                ) from exc
            raise
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._lock_handle = handle

    def release(self) -> None:
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

    def run_steps(
        self, steps: list[Step], profile: Profile, host: Host, force: bool = False
    ) -> int:
        """Run each step's plan in order; return a process exit code.

        force skips the DONE short-circuit: every step runs its plan
        regardless of probe state. rebuild uses it to re-execute a step
        that is already installed; setup leaves it off so idempotent
        re-runs stay cheap.
        """
        failures = 0
        for step in steps:
            state = step.probe(host)
            self.ctx.log(f"[{step.name}] probe: {state.value}")
            if state is State.DONE and not force and not self.ctx.dry_run:
                self.ctx.log(f"[{step.name}] already done on this system, skipping")
                continue
            try:
                rc = self.run_step(step, profile, host)
            except ConcurrentRunError:
                raise
            except Exception as exc:  # engine boundary: report, continue
                self.ctx.log(f"[{step.name}] error: {exc}")
                failures += 1
                continue
            if rc != 0:
                failures += 1
        return 1 if failures else 0

    def run_step(self, step: Step, profile: Profile, host: Host | None = None) -> int:
        """Run one step: prompts, plan, execute, persist."""
        host = host or self.ctx.host
        for prompt in step.prompts(profile):
            self.ctx.ask(prompt)

        actions = step.plan(profile, host, self.ctx.answers)
        if self.ctx.dry_run:
            for action in actions:
                self.ctx.log(f"PLAN {action.shell_line()}")
            return 0

        for action in actions:
            if self._cancelled():
                self.ctx.log(f"[{step.name}] cancelled before {action.key}")
                return 130
            if (
                not action.always
                and self.ctx.state_store
                and self.ctx.state_store.is_done(action.state_key)
            ):
                self.ctx.log(f"[{step.name}] {action.key}: done, skipping")
                continue
            rc = self._execute(step, action)
            if rc == 0:
                if self.ctx.state_store and not action.always:
                    self.ctx.state_store.done(action.state_key)
            elif rc == 130:
                self.ctx.log(f"[{step.name}] cancelled during {action.key}")
                return 130
            else:
                self.ctx.log(
                    f"[{step.name}] action {action.key} failed (rc={rc}); see {self.ctx.log_file}"
                )
                return rc
        self.ctx.log(f"[{step.name}] complete")
        return 0

    def _execute(self, step: Step, action: Action) -> int:
        try:
            self.ctx.run_action(action)
        except ConcurrentRunError:
            raise
        except KeyboardInterrupt:
            self.ctx.log(f"[{step.name}] interrupted during {action.key}")
            return 130
        except Exception as exc:
            self.ctx.log(f"[{step.name}] {action.key}: {exc}")
            return 1
        return 0

    def cancel(self) -> None:
        """Kill the running action's process group [A5]."""
        if self._proc is not None and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if self.ctx.cancel_event is not None:
            self.ctx.cancel_event.set()

    def _cancelled(self) -> bool:
        return self.ctx.cancel_event is not None and self.ctx.cancel_event.is_set()


def _lock_holder(lock_path: Path) -> str | None:
    try:
        return lock_path.read_text().strip() or None
    except OSError:
        return None


def default_log_file(repo_root: Path | None = None) -> Path:
    """logs/<epoch>.log, matching the legacy tee location."""
    import time

    root = repo_root or REPO_ROOT
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / f"{int(time.time())}.log"

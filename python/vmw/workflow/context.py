"""RunContext: sinks, cancellation, dry-run (plan 01).

One engine, two frontends: the TUI supplies RichLog + modal sinks, the
CLI supplies stdout + stdin/getpass. The engine only sees this object.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from vmw.infra import sh
from vmw.workflow.action import Action
from vmw.workflow.prompt import Prompt, PromptAnswers

if TYPE_CHECKING:  # pragma: no cover - typing only
    from vmw.infra.host import Host


@dataclass
class RunContext:
    """Execution context handed to step run() and the engine.

    root is lazy: the first root action triggers the password Prompt
    once per session [A2]; the answer lives in memory only.
    """

    dry_run: bool = False
    host: Host | None = None
    answers: PromptAnswers = field(default_factory=PromptAnswers)
    root: RootAuth | None = None
    log_sink: Callable[[str], None] = field(default=lambda line: print(line))
    line_sink: Callable[[str], None] = field(default=lambda line: print(line))
    prompt_sink: Callable[[Prompt], str] = field(default=lambda p: p.default or "")
    cancel_event: asyncio.Event | None = None
    state_store: StateStore | None = None
    work_dir: Path = field(default_factory=lambda: Path(".vmw"))
    log_file: Path | None = None
    repo_root: Path | None = None

    def emit(self, line: str) -> None:
        """Stream one output line (TUI RichLog / CLI stdout)."""
        self.line_sink(line)

    def log(self, message: str) -> None:
        """Structured log line (also appended to the run log)."""
        self.log_sink(message)
        if self.log_file is not None:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")

    def ask(self, prompt: Prompt) -> str:
        """Route a prompt to the frontend sink; cache by prompt id."""
        if prompt.id and prompt.id in self.answers.values:
            return self.answers.values[prompt.id]
        answer = self.prompt_sink(prompt)
        if prompt.id:
            self.answers.set(prompt.id, answer)
        # never log secrets (A2/ADR-007)
        if not prompt.is_secret and self.log_file is not None:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"prompt {prompt.id or prompt.kind}: {answer}\n")
        return answer

    def root_password(self) -> str:
        """The session password, prompting for it if not yet captured.

        Order: already captured -> VMW_SUDO env var (the documented
        convention [B5]) -> password Prompt once per session.
        """
        if self.root is not None:
            return self.root.password()
        env_password = os.environ.get("VMW_SUDO")
        if env_password:
            self.root = RootAuth(env_password)
            return env_password
        prompt = Prompt(
            kind="password", question="sudo password for this session", id="root.password"
        )
        password = self.ask(prompt)
        if not password:
            raise PermissionError("no session password provided for root actions")
        self.root = RootAuth(password)
        return password

    def run_action(self, action: Action) -> None:
        """Execute one action (cmd or func) through this context."""
        if action.func is not None:
            action.func(self)
            return
        sh.run_cmd(
            action.argv(),
            root=action.root,
            cwd=action.cwd,
            env=dict(action.env) or None,
            line_sink=self.emit,
            password=self.root_password() if action.root else None,
            terminal=action.terminal,
            log_file=self.log_file,
        )

    def sh(self, cmd: list[str], *, root: bool = False, cwd: str | Path | None = None) -> str:
        """Run a helper command from a func action; return stdout."""
        return sh.capture(
            cmd,
            root=root,
            cwd=cwd,
            password=self.root_password() if root else None,
        )

    def read_root_bytes(self, path: str | Path) -> bytes:
        """Read a root-only file (FACP, efivars, BGRT) via sudo cat."""
        import subprocess

        password = self.root_password()
        proc = subprocess.run(
            ["sudo", "-S", "--", "cat", str(path)],
            input=(password + "\n").encode(),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise PermissionError(f"cannot read {path} via sudo (rc={proc.returncode})")
        return proc.stdout


class RootAuth:
    """Session-password privilege model (A2 / ADR-007).

    Holds the password in memory only, pipes it via sudo -S. Never
    written to disk, never logged. The TUI's PasswordScreen / the CLI
    getpass populate this once per session.
    """

    def __init__(self, password: str, escalation: str = "sudo"):
        self._password = password
        self.escalation = escalation

    def password(self) -> str:
        return self._password

    def wrap(self, cmd: list[str]) -> list[str]:
        return [self.escalation, "-S", "--", *cmd]

    def password_bytes(self) -> bytes:
        return (self._password + "\n").encode()

    def __repr__(self) -> str:  # never leak the secret
        return "RootAuth(<redacted>)"


class RootRequiredError(RuntimeError):
    """A root Action ran with no privilege source configured."""

    def __init__(self, action: Action):
        self.action = action
        super().__init__(
            f"action '{action.key}' requires root but no root auth is configured for this run"
        )


@dataclass
class StateStore:
    """Engine-side view of .vmw/state.json (engine-only writes).

    Legacy state.json (module.<mod>.<step> shape) is ignored on first
    read [A8]; the new engine re-probes and rebuilds from scratch.
    """

    path: Path
    values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def open(cls, path: Path) -> StateStore:
        import json

        values: dict[str, str] = {}
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            flat = raw.get("values")
            if isinstance(flat, dict):
                # New format: {"values": {...}, "updated": epoch} OR
                # legacy {"values": {...}, "modules": {...}} [A8].
                # Legacy values keys look like "module.mod.step"; new
                # keys are "modules.mod.key"/"values.mod.field"; the
                # legacy nested "modules" dict marks the old shape.
                if "modules" in raw and isinstance(raw["modules"], dict):
                    pass  # legacy: ignore entirely [A8]
                else:
                    values = {str(k): str(v) for k, v in flat.items() if k != "updated"}
        return cls(path=path, values=values)

    def done(self, key: str) -> None:
        self.values[key] = "done"
        self._flush()

    def set_value(self, key: str, value: str) -> None:
        self.values[key] = value
        self._flush()

    def is_done(self, key: str) -> bool:
        return self.values.get(key) == "done"

    def _flush(self) -> None:
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {"values": self.values, "updated": int(__import__("time").time())}
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.path)

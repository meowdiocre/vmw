"""Action: the frozen unit of execution (plan 01).

Two execution shapes, one dataclass:

- cmd actions run argv through infra/sh.py (root wrapping, streaming,
  log tee). They cover the real tools: git, makepkg, ninja, virsh...
- func actions run a Python callable (ctx) -> None. They cover what
  bash did with sed/heredocs: file rewrites, FACP struct reads, XML
  snippets. Funcs needing privilege call sh.run_cmd(..., root=True).

key doubles as the idempotency entry in state.json
(modules.<step>.<key>). root selects the escalation wrapper; describe
feeds plan output and the TUI. always=True re-runs even when state
records it done (the reset-first cancel-hygiene action [A5]).
terminal=True runs with an inherited TTY (makepkg -si needs it for its
internal sudo) instead of the captured, streamed pipes [A2].
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from vmw.workflow.context import RunContext


@dataclass(frozen=True)
class Action:
    key: str
    cmd: Sequence[str] | None = None
    func: Callable[[RunContext], None] | None = None
    root: bool = False
    cwd: str | None = None
    describe: str = ""
    always: bool = False
    terminal: bool = False
    env: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.cmd is None and self.func is None:
            raise ValueError(f"action '{self.key}' needs cmd or func")
        if self.cmd is not None and self.func is not None:
            raise ValueError(f"action '{self.key}' cannot be both cmd and func")

    def argv(self) -> list[str]:
        """Materialize argv (Sequence may be consumed once)."""
        return [str(part) for part in (self.cmd or [])]

    @property
    def state_key(self) -> str:
        """Full state.json idempotency key for this action."""
        return f"modules.{self.key}"

    def shell_line(self) -> str:
        """Human-readable one-liner for plan output and TUI headers."""
        prefix = "root# " if self.root else "$ "
        if self.func is not None:
            return f"(python) {self.describe or self.key}"
        line = f"{prefix}{' '.join(self.argv())}"
        if self.terminal:
            line = f"(terminal) {line}"
        return line


def func_action(
    key: str,
    describe: str,
    fn: Callable[[RunContext], None],
    *,
    always: bool = False,
) -> Action:
    """Convenience constructor for the func shape."""
    return Action(key=key, func=fn, describe=describe, always=always)

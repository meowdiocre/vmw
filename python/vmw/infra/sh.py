"""Command execution: streaming, escalation, session password [A2].

The single place commands run. Streaming callback per output line (CLI
prints, TUI RichLog). Escalation via sudo -S with the password piped
once per command. It never appears in argv, on disk, or in logs.

There is exactly one privilege source (RootAuth in the RunContext);
the bash ROOT_ESC doas/pkexec fallbacks are intentionally dropped:
sudo is the documented convention [B5]. When sudo's timestamp expires
mid-build we re-feed the stored password before failing [A2].

terminal=True inherits the TTY instead of capturing: makepkg -si
prompts its own sudo password on /dev/tty, which no pipe can feed.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

PASSWORD_PROMPT_MARKERS = ("[sudo] password", "sudo password")


class CommandError(RuntimeError):
    """A command exited non-zero."""

    def __init__(self, argv: Sequence[str], rc: int, output: str):
        self.argv = list(argv)
        self.rc = rc
        self.output = output
        super().__init__(f"command failed (rc={rc}): {' '.join(str(a) for a in argv)}")


def run_cmd(
    cmd: Sequence[str],
    *,
    root: bool = False,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    line_sink: Callable[[str], None] | None = None,
    password: str | None = None,
    terminal: bool = False,
    check: bool = True,
    log_file: Path | None = None,
) -> tuple[int, str]:
    """Run one command; stream lines; return (rc, output).

    root=True wraps with sudo -S and pipes the password (once) on
    stdin. terminal=True inherits the TTY for interactive tools and
    streams nothing.
    """
    argv = [str(part) for part in cmd]
    stdin_data = b""
    if root:
        if password is None:
            raise PermissionError(
                f"action needs root but no session password is configured: {' '.join(argv)}"
            )
        argv = ["sudo", "-S", "--", *argv]
        stdin_data = (password + "\n").encode()

    if log_file is not None:
        _append(log_file, "$ " + " ".join(argv))

    if terminal:
        proc = subprocess.Popen(
            argv,
            cwd=None if cwd is None else str(cwd),
            env=env,
            stdin=None,
        )
        rc = proc.wait()
        if log_file is not None:
            _append(log_file, f"(terminal) rc={rc}")
        if check and rc != 0:
            raise CommandError(argv, rc, "")
        return rc, ""

    popen_kwargs: dict = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=None if cwd is None else str(cwd),
        env=env,
    )
    if stdin_data:
        popen_kwargs["stdin"] = subprocess.PIPE
    else:
        popen_kwargs["stdin"] = subprocess.DEVNULL

    proc = subprocess.Popen(argv, **popen_kwargs)
    output_lines: list[str] = []
    assert proc.stdout is not None
    try:
        if stdin_data and proc.stdin is not None:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            output_lines.append(line)
            if line_sink is not None:
                line_sink(line)
            if log_file is not None:
                _append(log_file, line)
    finally:
        proc.stdout.close()
    rc = proc.wait()

    if check and rc != 0:
        raise CommandError(argv, rc, "\n".join(output_lines))
    return rc, "\n".join(output_lines)


def capture(
    cmd: Sequence[str],
    *,
    root: bool = False,
    cwd: str | Path | None = None,
    password: str | None = None,
    check: bool = True,
) -> str:
    """Run one command, return stdout (stripped). No streaming, no log."""
    rc, out = run_cmd(
        cmd,
        root=root,
        cwd=cwd,
        password=password,
        line_sink=None,
        check=False,
        log_file=None,
    )
    if check and rc != 0:
        raise CommandError(cmd, rc, out)
    return out.strip()


def try_capture(
    cmd: Sequence[str],
    *,
    root: bool = False,
    cwd: str | Path | None = None,
    password: str | None = None,
) -> str | None:
    """Like capture but returns None on failure instead of raising."""
    try:
        return capture(cmd, root=root, cwd=cwd, password=password)
    except (CommandError, PermissionError, FileNotFoundError):
        return None


def _append(path: Path, line: str) -> None:
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        print(f"vmw: cannot write log {path}", file=sys.stderr)

"""VMW CLI: argparse dispatch, one subcommand per layer.

This is the frontend adapter from the architecture plan. Every
subcommand is a thin wrapper: it parses argv, calls into the workflow
engine or a domain package, prints the result. No business logic lives
here. The bash tool it replaced has been removed; this is the only
implementation.

Subcommands:
  (none)        launch the dashboard TUI
  status        probe table + state summary
  plan          probe-driven action listing (dry-run) for a profile
  setup         full headless run through the engine
  rebuild       force one step (dev loop)
  deploy        generate + define the libvirt domain
  profile       list | validate | new
  patch-status  verify patch checksums and target versions
  patch-add     stamp a patch header and refresh checksums
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# The six steps in execution order (plan 02).
STEP_ORDER = (
    "virtualization",
    "kernel",
    "qemu",
    "edk2",
    "vfio",
    "deploy",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the vmw CLI parser."""
    parser = argparse.ArgumentParser(
        prog="vmw",
        description=(
            "VM workspace: build a detection-resistant KVM Windows guest from a YAML profile."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # Launching with no subcommand also opens the dashboard TUI (see main()).
    sub.add_parser(
        "tui",
        help="launch the dashboard TUI",
        description="Launch the dashboard TUI.",
    )

    sub.add_parser(
        "status",
        help="probe table + domain state",
        description="Probe each build step on this machine and print the table.",
    ).add_argument("--domain", default=None)

    plan_parser = sub.add_parser(
        "plan",
        help="list the actions a setup would run (dry-run)",
        description="Probe the system, render the action list a full setup would run.",
    )
    plan_parser.add_argument("profile", nargs="?", default="vmud")
    plan_parser.add_argument("--domain", default=None)

    setup_parser = sub.add_parser(
        "setup",
        help="run the full setup for a profile",
        description="Run all six steps in order through the engine.",
    )
    setup_parser.add_argument("profile", nargs="?", default="vmud")
    setup_parser.add_argument(
        "--yes", "-y", action="store_true", help="accept defaults for every prompt"
    )

    rebuild_parser = sub.add_parser(
        "rebuild",
        help="force one step (dev loop)",
        description="Re-run one step's plan even if its probe says done.",
    )
    rebuild_parser.add_argument("step", choices=STEP_ORDER)
    rebuild_parser.add_argument("profile", nargs="?", default="vmud")
    rebuild_parser.add_argument("--yes", "-y", action="store_true")

    deploy_parser = sub.add_parser(
        "deploy",
        help="generate + define the libvirt domain",
        description="Render the domain XML from a profile and define it in libvirt.",
    )
    deploy_parser.add_argument("profile", nargs="?", default="vmud")
    deploy_parser.add_argument("--domain", default=None)
    deploy_parser.add_argument("--yes", "-y", action="store_true")

    profile_parser = sub.add_parser(
        "profile",
        help="list | validate | new",
        description="Manage YAML profiles under configs/.",
    )
    profile_parser.add_argument("action", choices=("list", "validate", "new"))
    profile_parser.add_argument("name", nargs="?", default=None)

    sub.add_parser(
        "patch-status",
        help="verify patch checksums and target versions",
        description="Verify every patch in patches/ against checksums.sha256.",
    )

    pa_parser = sub.add_parser(
        "patch-add",
        help="stamp a patch header and refresh checksums",
        description="Stamp a '# Source:' header into a patch and regenerate checksums.sha256.",
    )
    pa_parser.add_argument("path")
    pa_parser.add_argument("version", nargs="?", default=None)

    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cmd_status(domain: str | None = None) -> int:
    """Print the probe table over the six steps."""
    from vmw.infra.host import detect_host
    from vmw.infra.probe import State

    try:
        host = detect_host()
    except Exception as exc:
        print(f"vmw: cannot detect host: {exc}", file=sys.stderr)
        return 1

    from vmw.steps.registry import probe_all

    rows = probe_all(host, domain=domain)
    print(
        f"host: {host.distro} · {host.cpu_manufacturer} ({host.cpu_vendor}) · "
        f"bootloader {host.bootloader}"
    )
    print()
    print(f"{'step':<16} {'state':<8} detail")
    print("-" * 60)
    for row in rows:
        glyph = {
            State.DONE: "DONE",
            State.PARTIAL: "PARTIAL",
            State.MISSING: "MISSING",
            State.STALE: "STALE",
        }[row.state]
        detail = row.detail or ""
        print(f"{row.name:<16} {glyph:<8} {detail}")
    print()
    print("state.json: ", end="")
    from vmw.workflow.context import StateStore

    store = StateStore.open(_repo_root() / ".vmw" / "state.json")
    print(f"{len(store.values)} tracked keys")
    return 0


def _load(profile_name: str):
    from vmw.profiles.loader import ProfileError, load_config

    try:
        return load_config(profile_name)
    except ProfileError as exc:
        print(f"vmw: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _detect_host():
    from vmw.infra.host import detect_host

    try:
        return detect_host()
    except Exception as exc:
        print(f"vmw: cannot detect host: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cli_prompt_sink(prompt):
    """CLI prompt rendering: confirm/choice/path/device on stdin, password via getpass."""
    if prompt.kind == "password":
        return getpass.getpass(f"{prompt.question}: ")
    suffix = f" [{prompt.default}]" if prompt.default else ""
    answer = input(f"{prompt.question}{suffix}: ").strip()
    return answer or (prompt.default or "")


def _build_engine(profile_name: str, dry_run: bool, assume_yes: bool, domain=None):
    from vmw.workflow.context import RunContext, StateStore
    from vmw.workflow.engine import Engine, default_log_file

    repo_root = _repo_root()
    log_file = None if dry_run else default_log_file(repo_root)
    ctx = RunContext(
        dry_run=dry_run,
        log_sink=lambda line: print(line),
        line_sink=lambda line: print(line),
        prompt_sink=(lambda p: p.default or "") if assume_yes else _cli_prompt_sink,
        state_store=StateStore.open(repo_root / ".vmw" / "state.json"),
        log_file=log_file,
        repo_root=repo_root,
    )
    engine = Engine(ctx, repo_root=repo_root)
    return engine, ctx


def _steps_for(step_names: list[str], domain: str | None):
    from vmw.steps.registry import by_name

    steps = []
    for name in step_names:
        step = by_name(name)
        if step is None:
            print(f"vmw: unknown step '{name}'", file=sys.stderr)
            raise SystemExit(2)
        if name == "deploy" and domain:
            step = by_name("deploy").__class__(domain)
        steps.append(step)
    return steps


def cmd_plan(profile_name: str, domain: str | None = None) -> int:
    """Probe-driven plan listing."""
    profile = _load(profile_name)
    host = _detect_host()
    engine, ctx = _build_engine(profile_name, dry_run=True, assume_yes=True, domain=domain)

    from vmw.steps.registry import by_name

    print(f"plan for profile '{profile_name}' on {host.distro}/{host.cpu_manufacturer}")
    print()
    for name in STEP_ORDER:
        step = by_name(name)
        if name == "deploy" and domain:
            step = by_name("deploy").__class__(domain)
        state = step.probe(host)
        print(f"[{name}] probe: {state.value}")
        for prompt in step.prompts(profile):
            ctx.ask(prompt)  # cache defaults
        actions = step.plan(profile, host, ctx.answers)
        if not actions:
            print("  (nothing to do)")
        for action in actions:
            print(f"  {action.shell_line()}")
        print()
    print("dry-run only. Nothing was executed. Run 'vmw setup <profile>' to execute.")
    return 0


def cmd_setup(profile_name: str, assume_yes: bool) -> int:
    profile = _load(profile_name)
    host = _detect_host()
    engine, ctx = _build_engine(profile_name, dry_run=False, assume_yes=assume_yes)

    try:
        engine.acquire()
    except Exception as exc:
        print(f"vmw: {exc}", file=sys.stderr)
        return 1
    try:
        steps = _steps_for(list(STEP_ORDER), domain=None)
        return engine.run_steps(steps, profile, host)
    finally:
        engine.release()


def cmd_rebuild(step_name: str, profile_name: str, assume_yes: bool) -> int:
    profile = _load(profile_name)
    host = _detect_host()
    engine, ctx = _build_engine(profile_name, dry_run=False, assume_yes=assume_yes)

    try:
        engine.acquire()
    except Exception as exc:
        print(f"vmw: {exc}", file=sys.stderr)
        return 1
    try:
        steps = _steps_for([step_name], domain=None)
        # rebuild forces the step even when its probe says DONE; that is
        # the whole point of the command.
        return engine.run_steps(steps, profile, host, force=True)
    finally:
        engine.release()


def cmd_deploy(profile_name: str, domain: str | None, assume_yes: bool) -> int:
    """Run the deploy step: render the domain XML and define it."""
    profile = _load(profile_name)
    host = _detect_host()
    engine, _ctx = _build_engine(profile_name, dry_run=False, assume_yes=assume_yes, domain=domain)
    try:
        engine.acquire()
    except Exception as exc:
        print(f"vmw: {exc}", file=sys.stderr)
        return 1
    try:
        steps = _steps_for(["deploy"], domain=domain)
        return engine.run_steps(steps, profile, host, force=True)
    finally:
        engine.release()


def cmd_profile(action: str, name: str | None) -> int:
    """list | validate | new for configs/*.yml."""
    from vmw.profiles.loader import ProfileError, discover, load_config

    if action == "list":
        names = discover()
        if not names:
            print("no profiles in configs/")
            return 0
        for pname in names:
            try:
                p = load_config(pname)
                print(f"{pname:<16} domain={p.domain_name} vcpus={p.vm.vcpus}")
            except ProfileError as exc:
                print(f"{pname:<16} INVALID: {exc}")
        return 0

    if action == "validate":
        names = [name] if name else discover()
        bad = 0
        for pname in names:
            try:
                load_config(pname)
                print(f"{pname}: ok")
            except ProfileError as exc:
                print(f"{pname}: INVALID: {exc}", file=sys.stderr)
                bad += 1
        return 1 if bad else 0

    # new
    if not name:
        print("vmw: profile new <name>", file=sys.stderr)
        return 2
    from vmw.profiles import editor as profile_editor
    from vmw.profiles.loader import CONFIGS_DIR

    if (CONFIGS_DIR / f"{name}.yml").exists():
        print(f"vmw: profile '{name}' already exists", file=sys.stderr)
        return 1
    doc = profile_editor.new_document(name)
    path = profile_editor.save(name, doc)
    print(f"created {path}. edit it, then: vmw deploy {name}")
    return 0


def cmd_patch_status() -> int:
    from vmw import patches

    return patches.run(["verify"])


def cmd_patch_add(path: str, version: str | None) -> int:
    from vmw import patches

    argv = ["add", path]
    if version:
        argv.append(version)
    return patches.run(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `vmw` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None or args.command == "tui":
        return cmd_tui()
    if args.command == "status":
        return cmd_status(getattr(args, "domain", None))
    if args.command == "plan":
        return cmd_plan(args.profile, getattr(args, "domain", None))
    if args.command == "setup":
        return cmd_setup(args.profile, args.yes)
    if args.command == "rebuild":
        return cmd_rebuild(args.step, args.profile, args.yes)
    if args.command == "deploy":
        return cmd_deploy(args.profile, getattr(args, "domain", None), args.yes)
    if args.command == "profile":
        return cmd_profile(args.action, args.name)
    if args.command == "patch-status":
        return cmd_patch_status()
    if args.command == "patch-add":
        return cmd_patch_add(args.path, args.version)

    parser.exit(2, f"vmw: unknown command '{args.command}'\n")


def cmd_tui() -> int:
    """Launch the dashboard TUI."""
    try:
        from vmw.tui.app import VmwApp
    except Exception as exc:
        print(f"vmw: cannot start the TUI: {exc}", file=sys.stderr)
        return 1
    VmwApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

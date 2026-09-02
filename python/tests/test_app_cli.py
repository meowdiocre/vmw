"""CLI: every subcommand is implemented in-app (no bash fallback)."""

import pytest
from vmw.app import build_parser, main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "VM workspace" in out


def test_no_args_launches_tui(monkeypatch):
    """No subcommand routes to the TUI launcher (dashboard-first)."""
    import vmw.app as app_mod

    launched = {}
    monkeypatch.setattr(app_mod, "cmd_tui", lambda: launched.__setitem__("tui", True) or 0)
    assert main([]) == 0
    assert launched.get("tui") is True


def test_tui_subcommand_launches_tui(monkeypatch):
    import vmw.app as app_mod

    launched = {}
    monkeypatch.setattr(app_mod, "cmd_tui", lambda: launched.__setitem__("tui", True) or 0)
    assert main(["tui"]) == 0
    assert launched.get("tui") is True


def test_all_subcommands_parse():
    """Every subcommand is implemented; none are legacy stubs anymore."""
    parser = build_parser()
    assert parser.parse_args(["deploy", "aptwannabe"]).profile == "aptwannabe"
    assert parser.parse_args(["profile", "list"]).action == "list"
    assert parser.parse_args(["patch-status"]).command == "patch-status"
    assert parser.parse_args(["patch-add", "p.patch", "v1"]).path == "p.patch"


def test_profile_list_runs_without_a_host(capsys):
    """`vmw profile list` reads configs/ and never touches the system."""
    assert main(["profile", "list"]) == 0
    out = capsys.readouterr().out
    assert "example" in out


def test_unknown_command_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == 2


def test_parser_exposes_tui():
    parser = build_parser()
    args = parser.parse_args(["tui"])
    assert args.command == "tui"


def test_ported_subcommands_parse():
    """plan/setup/rebuild parse their profile/step args."""
    parser = build_parser()
    assert parser.parse_args(["plan", "aptwannabe"]).profile == "aptwannabe"
    assert parser.parse_args(["setup"]).profile == "vmud"
    assert parser.parse_args(["rebuild", "kernel", "vmud"]).step == "kernel"
    assert parser.parse_args(["status"]).command == "status"


def test_rebuild_rejects_unknown_step():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["rebuild", "frobnicate"])


def test_plan_missing_profile_fails_clean(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["plan", "no-such-profile"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "not found" in err

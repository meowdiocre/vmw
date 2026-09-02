"""Workflow engine: plan/dry-run/execute/skip/persist + flock [A4]."""

import pytest
from vmw.infra.probe import State
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext, StateStore
from vmw.workflow.engine import ConcurrentRunError, Engine
from vmw.workflow.step import Step


class FakeStep(Step):
    """Records nothing, probes from a fixed state."""

    name = "fake"
    title = "fake step"

    def __init__(self, state=State.MISSING, actions=None):
        self.state = state
        self.actions = actions or []

    def probe(self, host):
        return self.state

    def plan(self, profile, host, answers):
        return self.actions


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "name": "engine-test",
            "vm": {"memory_mib": 512, "vcpus": 1},
            "device": {"disk_path": "/tmp/e.qcow2"},
        }
    )


def _ctx(tmp_path, dry_run=False):
    log = tmp_path / "run.log"
    store = StateStore.open(tmp_path / "state.json")
    ctx = RunContext(
        dry_run=dry_run,
        log_sink=lambda line: None,
        line_sink=lambda line: None,
        state_store=store,
        log_file=log,
    )
    return ctx, store


def test_dry_run_returns_plan_without_executing(tmp_path):
    ctx, _ = _ctx(tmp_path, dry_run=True)
    engine = Engine(ctx, repo_root=tmp_path)
    logged = []
    ctx.log_sink = logged.append
    step = FakeStep(actions=[Action(key="fake.one", cmd=["touch", str(tmp_path / "marker")])])
    rc = engine.run_step(step, _profile(), host=None)
    assert rc == 0
    assert not (tmp_path / "marker").exists()  # nothing executed
    assert any("touch" in line for line in logged)


def test_execute_marks_done_and_persists(tmp_path):
    ctx, store = _ctx(tmp_path)
    engine = Engine(ctx, repo_root=tmp_path)
    marker = tmp_path / "done.txt"
    step = FakeStep(actions=[Action(key="fake.touch", cmd=["touch", str(marker)])])
    rc = engine.run_step(step, _profile(), host=None)
    assert rc == 0
    assert marker.exists()
    assert store.is_done("modules.fake.touch")
    # state.json on disk in the new flat format
    import json

    payload = json.loads((tmp_path / "state.json").read_text())
    assert payload["values"]["modules.fake.touch"] == "done"


def test_skip_done_actions(tmp_path):
    ctx, store = _ctx(tmp_path)
    store.done("modules.fake.touch")
    engine = Engine(ctx, repo_root=tmp_path)
    marker = tmp_path / "done.txt"
    step = FakeStep(actions=[Action(key="fake.touch", cmd=["touch", str(marker)])])
    rc = engine.run_step(step, _profile(), host=None)
    assert rc == 0
    assert not marker.exists()  # skipped


def test_failed_action_stops_step(tmp_path):
    ctx, _ = _ctx(tmp_path)
    engine = Engine(ctx, repo_root=tmp_path)
    step = FakeStep(
        actions=[
            Action(key="fake.fail", cmd=["false"]),
            Action(key="fake.after", cmd=["touch", str(tmp_path / "after")]),
        ]
    )
    rc = engine.run_step(step, _profile(), host=None)
    assert rc != 0
    assert not (tmp_path / "after").exists()


def test_flock_blocks_second_engine(tmp_path):
    ctx, _ = _ctx(tmp_path)
    first = Engine(ctx, repo_root=tmp_path)
    first.acquire()
    try:
        second_ctx, _ = _ctx(tmp_path / "second")
        second = Engine(second_ctx, repo_root=tmp_path)
        with pytest.raises(ConcurrentRunError):
            second.acquire()
    finally:
        first.release()


def test_root_action_without_auth_fails_cleanly(tmp_path):
    ctx, _ = _ctx(tmp_path)
    engine = Engine(ctx, repo_root=tmp_path)
    step = FakeStep(actions=[Action(key="fake.root", cmd=["id"], root=True)])
    try:
        rc = engine.run_step(step, _profile(), host=None)
        assert rc != 0
    except RuntimeError as exc:
        assert "root" in str(exc)


def test_legacy_state_ignored(tmp_path):
    """[A8] legacy nested state.json is ignored, engine starts fresh."""
    import json

    legacy = {"modules": {"kernel": {"complete": "done"}}, "values": {}}
    (tmp_path / "state.json").write_text(json.dumps(legacy))
    store = StateStore.open(tmp_path / "state.json")
    assert store.values == {}


def test_statestore_roundtrip(tmp_path):
    store = StateStore.open(tmp_path / "state.json")
    store.done("modules.x.y")
    store.set_value("values.kernel.build_hash", "abc")
    again = StateStore.open(tmp_path / "state.json")
    assert again.is_done("modules.x.y")
    assert again.values["values.kernel.build_hash"] == "abc"

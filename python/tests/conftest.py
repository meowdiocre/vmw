"""Test configuration.

Profiles come from tracked fixtures (python/tests/fixtures/configs/), not
the shipped configs/ tree. Personal per-VM profiles under configs/ are
git-ignored (only vmud + _defaults ship), so the suite must not depend on
what a developer happens to keep there. Redirecting the loader/editor to
the fixtures dir keeps CI green regardless of local configs and gives the
disk-bearing "example" profile the genxml/editor tests need.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_CONFIGS = Path(__file__).parent / "fixtures" / "configs"


@pytest.fixture(autouse=True)
def _fixture_configs(monkeypatch):
    """Point profile loading at the fixtures dir for every test.

    Tests that pass an explicit ``configs_dir`` (round-trip save tests
    using tmp_path) are unaffected: that argument still wins.
    """
    from vmw.profiles import editor, loader

    monkeypatch.setattr(loader, "CONFIGS_DIR", FIXTURE_CONFIGS)
    monkeypatch.setattr(editor, "CONFIGS_DIR", FIXTURE_CONFIGS)

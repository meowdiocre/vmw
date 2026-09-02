"""Smoke test: every core package is importable."""

import importlib

import pytest

PACKAGES = [
    "vmw.app",
    "vmw.infra",
    "vmw.workflow",
    "vmw.profiles",
    "vmw.steps",
    "vmw.tui",
]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_importable(package):
    importlib.import_module(package)


def test_legacy_modules_still_importable():
    """Legacy bash-called modules keep their names."""
    for mod in ("vmw.yaml", "vmw.state", "vmw.patches", "vmw.genxml"):
        importlib.import_module(mod)

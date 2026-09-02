"""Distro package tables (from lib/packages.sh + modules' REQUIRED_PKGS_* arrays).

Data lives in vmw/data/distro_packages.toml; this module reads it. The
# EXPERIMENTAL distro labels [A7] are carried in the table.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # py<3.11 fallback for the matrix
    import tomli as tomllib  # type: ignore[no-redef]

DATA_FILE = Path(__file__).parent.parent / "data" / "distro_packages.toml"

# Managers per distro family (lib/packages.sh case block).
MANAGERS: dict[str, dict[str, list[str]]] = {
    "Arch": {"mgr": "pacman", "install": ["-S", "--noconfirm"], "check": ["pacman", "-Q"]},
    "Debian": {"mgr": "apt", "install": ["-y", "install"], "check": ["dpkg", "-s"]},
    "openSUSE": {"mgr": "zypper", "install": ["install", "-y"], "check": ["rpm", "-q"]},
    "Fedora": {"mgr": "dnf", "install": ["-yq", "install"], "check": ["rpm", "-q"]},
}


def load_tables(data_file: Path = DATA_FILE) -> dict[str, Any]:
    """Read the package tables; {} when missing (tests inject paths)."""
    try:
        with data_file.open("rb") as handle:
            return tomllib.load(handle)
    except OSError:
        return {}


def packages_for(distro: str, component: str, tables: dict | None = None) -> list[str]:
    """Package list for component+distro, falling back to family defaults."""
    tables = tables if tables is not None else load_tables()
    entry = tables.get(component, {})
    pkgs = entry.get(distro)
    if pkgs is None and (fallback := entry.get("any")):
        return list(fallback)
    return list(pkgs or [])


def missing(
    packages: list[str], distro: str, which: callable = shutil.which, run: callable = subprocess.run
) -> list[str]:
    """Which packages are not installed on this host."""
    manager = MANAGERS.get(distro)
    if not manager:
        raise ValueError(f"Unsupported distro: {distro}")
    if which(manager["mgr"]) is None:
        # Manager absent (e.g. fixture container): treat all as missing.
        return list(packages)

    missing_pkgs = []
    for pkg in packages:
        proc = run(manager["check"] + [pkg], capture_output=True, check=False)
        if proc.returncode != 0:
            missing_pkgs.append(pkg)
    return missing_pkgs


def install_command(distro: str, packages: list[str]) -> list[str]:
    """Root command (argv) that installs the packages via the distro manager."""
    manager = MANAGERS.get(distro)
    if not manager:
        raise ValueError(f"Unsupported distro: {distro}")
    return [manager["mgr"], *manager["install"], *packages]

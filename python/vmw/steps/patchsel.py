"""Shared patch selection + drift/record helpers for the build steps.

Before this module, edk2, qemu, and kernel each carried their own copy of
the "use the profile's configured patch, else fall back to a host-derived
default" logic. kernel was the odd one out: it ignored the Host it was
handed and re-ran CPU detection three separate times, so it could not be
retargeted the way edk2/qemu could.

Centralising it here has one payoff beyond less code: a profile pins
*nothing* CPU-specific (schema default is ""), so ``select_patch`` derives
the right Intel/AMD patch from the running Host every time. The same
profile builds on any supported machine.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PATCHES_DIR = REPO_ROOT / "patches"


def select_patch(subdir: str, configured: str, host_default: str) -> str:
    """The patch file to apply for a build step.

    ``configured`` is the profile's explicit override; it wins only when
    the named file actually exists under ``patches/<subdir>/``. Otherwise
    (the normal case: profiles pin nothing) the caller's host-derived
    default is used, so an Intel host gets the Intel patch and an AMD host
    the AMD one from the identical profile.
    """
    if configured and (PATCHES_DIR / subdir / configured).is_file():
        return configured
    return host_default


def verify_no_drift(subdir: str, patch_name: str, expected_tag: str) -> Path:
    """Resolve ``patches/<subdir>/<patch_name>`` and guard version drift.

    Raises if the file is missing, or if its ``# Source:`` stamp names a
    source tree other than ``expected_tag`` (a patch built against a
    different upstream revision would apply into the wrong lines). Returns
    the resolved path so the caller can hand it straight to ``git apply``.
    """
    patch = PATCHES_DIR / subdir / patch_name
    if not patch.is_file():
        raise RuntimeError(f"missing patch file: {patch}")

    from vmw.patches import target_version

    stamped = target_version(str(patch))
    if stamped and stamped != expected_tag:
        raise RuntimeError(
            f"patch '{patch_name}' targets {stamped} but source is {expected_tag} - drift detected"
        )
    return patch


def record_build_hash(ctx, step: str, subdir: str, patch_name: str) -> None:
    """Record the applied patch's SHA256 into ``values.<step>.build_hash``.

    ``vmw status`` compares it against patches/checksums.sha256 to flag a
    STALE build after a patch changes on disk.
    """
    from vmw.infra.probe import _file_sha256

    patch = PATCHES_DIR / subdir / patch_name
    digest = _file_sha256(patch)
    if digest and ctx.state_store is not None:
        ctx.state_store.set_value(f"values.{step}.build_hash", digest)
    ctx.log(f"recorded build_hash for {patch_name}")

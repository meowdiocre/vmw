"""Verify patches apply cleanly against their target source trees.

Clones each source repo at the stamped target version and runs
`git apply --check` for every active patch (non-destructive: nothing is
actually applied). Reports which patches fail and why.

Usage:
  python3 -m vmw.patchcheck              # all active patches
  python3 -m vmw.patchcheck qemu         # only qemu patches
  python3 -m vmw.patchcheck --purge      # delete cloned trees before running
  python3 -m vmw.patchcheck --keep       # reuse existing cloned trees (default)
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATCH_DIR = os.path.join(ROOT, "patches")
WORK_DIR = os.path.join(ROOT, ".vmw", "patchcheck")

# component -> (patch dir name, clone url)
SOURCES = {
    "qemu": ("QEMU", "https://github.com/qemu/qemu.git"),
    "edk2": ("EDK2", "https://github.com/tianocore/edk2.git"),
    "kernel": ("Kernel", "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"),
}

ARCHIVE_DIRS = ("Archive",)
ACTIVE_EXTS = (".patch",)


def active_patches(component):
    """Yield (relpath, target_version) for active (non-archive) patches."""
    patch_dir = SOURCES[component][0]
    for root, dirs, files in os.walk(PATCH_DIR):
        rel_root = os.path.relpath(root, PATCH_DIR)
        top = rel_root.split(os.sep)[0]
        if top != patch_dir:
            continue
        dirs[:] = [d for d in dirs if d not in ARCHIVE_DIRS]
        for name in sorted(files):
            if name.endswith(ACTIVE_EXTS):
                rel = os.path.join(rel_root, name)
                ver = target_version(os.path.join(root, name))
                yield rel, ver


def target_version(patch_path):
    with open(patch_path, "rb") as handle:
        for line in handle:
            text = line.decode("utf-8", "replace")
            if text.startswith("# Source:"):
                return text.split(":", 1)[1].strip()
            if text.startswith(("diff ", "---", "+++")):
                break
    return ""


def clone(component, tag, force):
    _, url = SOURCES[component]
    # Kernel patches target an upstream linux tag (v6.16, v7.02); the branch
    # is the version string, not a git tag.
    if component == "kernel":
        tag = f"v{tag}" if tag and not tag.startswith("v") else tag
    dest = os.path.join(WORK_DIR, component, tag or "default")
    if os.path.isdir(os.path.join(dest, ".git")):
        if force:
            shutil.rmtree(dest)
        else:
            return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = ["git", "clone", "--depth=1"]
    if tag:
        cmd += ["--branch", tag]
    cmd += [url, dest]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  clone {component}@{tag}: FAILED\n{proc.stderr.strip()}")
        return None
    # EDK2 needs submodules for the files some patches touch, but they are
    # large and may be unreachable (SSH-only github). Best-effort: if they
    # fail, we still try applying; a patch touching only main-tree files
    # will validate fine.
    if component == "edk2":
        sub = subprocess.run(
            ["git", "-C", dest, "submodule", "update", "--init", "--depth=1"],
            capture_output=True, text=True)
        if sub.returncode != 0:
            print("  warning: edk2 submodule init failed; some patches may "
                  "fail if they touch submodule files")
    return dest


def check_patch(component, dest, rel, ver):
    """Return (ok, message)."""
    # Path inside the patch file is relative to the repo root.
    proc = subprocess.run(
        ["git", "-C", dest, "apply", "--check", os.path.join(PATCH_DIR, rel)],
        capture_output=True, text=True)
    if proc.returncode == 0:
        return True, "applies cleanly"
    return False, proc.stderr.strip() or "apply --check failed"


def run(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", nargs="?", help="qemu|edk2|kernel (default: all)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--purge", action="store_true", help="delete cached clones first")
    group.add_argument("--keep", action="store_true", help="reuse cached clones (default)")
    args = parser.parse_args(argv)

    components = [args.component] if args.component else list(SOURCES)
    if args.purge:
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    total = passed = failed = 0
    for comp in components:
        if comp not in SOURCES:
            print(f"unknown component: {comp}", file=sys.stderr)
            return 2
        patches = list(active_patches(comp))
        if not patches:
            print(f"\n[{comp}] no active patches")
            continue
        # Group by target version so we clone each source once.
        by_version = {}
        for rel, ver in patches:
            by_version.setdefault(ver, []).append(rel)
        print(f"\n[{comp}]")
        for ver, rels in sorted(by_version.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            dest = clone(comp, ver, force=args.purge)
            if dest is None:
                failed += len(rels)
                continue
            for rel in rels:
                total += 1
                ok, msg = check_patch(comp, dest, rel, ver)
                status = "ok  " if ok else "FAIL"
                print(f"  {status} {rel}  ({msg})")
                if ok:
                    passed += 1
                else:
                    failed += 1

    print(f"\n{passed}/{total} patches apply cleanly.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

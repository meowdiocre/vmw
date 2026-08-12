"""Patch integrity verifier for VMW.

Computes SHA256 of every patch in patches/ and stores them in
patches/checksums.sha256. Verifies patches match their expected target
source version (parsed from a "# Source:" header line).

Usage:
  python3 -m vmw.patches gen
  python3 -m vmw.patches verify
  python3 -m vmw.patches version <file>
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATCH_DIR = os.path.join(ROOT, "patches")
CHECKSUM_FILE = os.path.join(PATCH_DIR, "checksums.sha256")

VERSION_RE = re.compile(r"^\s*#\s*(?:Source|Target|Version):\s*(.+?)\s*$", re.I)

PATCH_EXTS = (".patch", ".mypatch", ".dsl", ".aml")


def target_version(patch_path):
    """Return expected source version from the patch header, or ''."""
    try:
        with open(patch_path, "rb") as handle:
            for line in handle:
                try:
                    text = line.decode("utf-8", "replace")
                except UnicodeDecodeError:
                    continue
                match = VERSION_RE.match(text)
                if match:
                    return match.group(1).strip()
                if text.startswith("---") or text.startswith("+++") or text.startswith("diff "):
                    break
    except OSError:
        return ""
    return ""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_patches():
    for root, _, files in os.walk(PATCH_DIR):
        if root == PATCH_DIR:
            continue  # skip checksums file itself (it lives at patches root)
        for name in files:
            if name.endswith(PATCH_EXTS):
                yield os.path.relpath(os.path.join(root, name), PATCH_DIR)


def cmd_gen():
    entries = []
    for rel in sorted(iter_patches()):
        entries.append(f"{sha256(os.path.join(PATCH_DIR, rel))}  {rel}")
    with open(CHECKSUM_FILE, "w") as handle:
        handle.write("# VMW patch checksums\n# Regenerate with: python3 -m vmw.patches gen\n")
        handle.write("\n".join(entries) + "\n")
    print(f"Wrote {len(entries)} checksums to {CHECKSUM_FILE}")
    return 0


def cmd_verify():
    if not os.path.exists(CHECKSUM_FILE):
        print(f"error: missing {CHECKSUM_FILE} - run 'python3 -m vmw.patches gen'", file=sys.stderr)
        return 1

    expected = {}
    with open(CHECKSUM_FILE) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, rel = line.split(None, 1)
            expected[rel] = digest

    failures = 0
    found = set()
    for rel in sorted(iter_patches()):
        found.add(rel)
        actual = sha256(os.path.join(PATCH_DIR, rel))
        if rel in expected:
            if actual != expected[rel]:
                print(f"FAIL {rel}: checksum mismatch")
                failures += 1
            else:
                ver = target_version(os.path.join(PATCH_DIR, rel))
                print(f"ok   {rel}" + (f"  (target {ver})" if ver else ""))
        else:
            print(f"NOTE {rel}: not in checksums.sha256")
            failures += 1

    for rel in set(expected) - found:
        print(f"NOTE {rel}: in checksums but missing on disk")
        failures += 1

    if failures:
        print(f"\n{failures} issue(s) found.", file=sys.stderr)
        return 1
    print("\nAll patches verified.")
    return 0


def cmd_version(path):
    print(target_version(path))
    return 0


def run(argv):
    if not argv or argv[0] not in ("gen", "verify", "version"):
        sys.stderr.write(__doc__ + "\n")
        return 2
    if argv[0] == "gen":
        return cmd_gen()
    if argv[0] == "verify":
        return cmd_verify()
    return cmd_version(argv[1])


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

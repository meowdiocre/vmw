"""VMW Python tooling package.

Invoked as `python3 -m vmw <subcommand> ...`:

  yaml     <file>   -> flatten YAML profile to CFG_* shell assignments
  state    ...      -> .vmw/state.json manifest CRUD
  patches  ...      -> patch checksums gen/verify + version stamping
  genxml   <profile> -> generate libvirt domain XML from a profile
  patchcheck [comp] -> clone sources and verify patches apply cleanly

Each subcommand has its own module (yaml.py, state.py, patches.py, genxml.py)
that can also be run directly: `python3 -m vmw.patches verify`.
"""
import importlib
import sys


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__ + "\n")
        return 2
    sub = sys.argv[1]
    if sub not in ("yaml", "state", "patches", "genxml", "patchcheck"):
        sys.stderr.write(f"unknown subcommand: {sub}\n")
        return 2
    mod = importlib.import_module(f"vmw.{sub}")
    return mod.run(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())

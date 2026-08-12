#!/usr/bin/env python3
"""State manifest manager for VMW.

Stores completed steps per module in .vmw/state.json so re-runs can
skip done work and resume mid-build.

Usage:
  vmw_state.py get [<key>]
  vmw_state.py set <key> <value>
  vmw_state.py has <key>           # exit 0 if key is set & truthy
  vmw_state.py done <module> <step> # mark a step complete
  vmw_state.py pending <module> <step> # remove a step
  vmw_state.py list [<module>]
  vmw_state.py reset [<module>]
"""
import json
import os
import sys

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".vmw")
STATE_FILE = os.path.join(STATE_DIR, "state.json")


def load():
    if not os.path.exists(STATE_FILE):
        return {"modules": {}, "values": {}}
    try:
        with open(STATE_FILE) as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"modules": {}, "values": {}}


def save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = args[0]
    state = load()

    if cmd == "get":
        key = args[1] if len(args) > 1 else None
        if key is None:
            for k, v in sorted(state.get("values", {}).items()):
                print(f"{k}={v}")
        else:
            print(state.get("values", {}).get(key, ""))
    elif cmd == "set":
        key, value = args[1], args[2]
        state.setdefault("values", {})[key] = value
        save(state)
    elif cmd == "has":
        key = args[1]
        val = state.get("values", {}).get(key, "")
        if key.startswith("module."):
            parts = key.split(".", 2)
            if len(parts) == 3:
                _, module, step = parts
                val = state.get("modules", {}).get(module, {}).get(step, "")
        return 0 if val not in (None, "", "false", "0") else 1
    elif cmd == "done":
        module, step = args[1], args[2]
        state.setdefault("modules", {}).setdefault(module, {})[step] = "done"
        save(state)
    elif cmd == "pending":
        module, step = args[1], args[2]
        state.get("modules", {}).get(module, {}).pop(step, None)
        save(state)
    elif cmd == "list":
        module = args[1] if len(args) > 1 else None
        if module:
            steps = state.get("modules", {}).get(module, {})
            for step, status in steps.items():
                print(f"{step}={status}")
        else:
            for mod, steps in state.get("modules", {}).items():
                print(f"[{mod}]")
                for step, status in steps.items():
                    print(f"  {step}={status}")
    elif cmd == "reset":
        module = args[1] if len(args) > 1 else None
        if module:
            state.get("modules", {}).pop(module, None)
        else:
            state = {"modules": {}, "values": {}}
        save(state)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

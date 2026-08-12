#!/usr/bin/env python3
import sys

import yaml


def flatten(prefix, node, out):
    for key, value in node.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flatten(name, value, out)
        elif isinstance(value, (list, tuple)):
            out[name] = " ".join(str(item) for item in value)
        elif isinstance(value, bool):
            out[name] = "true" if value else "false"
        elif value is None:
            out[name] = ""
        else:
            out[name] = str(value)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "-"
    with open(path) as handle:
        data = yaml.safe_load(handle) or {}
    out = {}
    flatten("", data, out)
    for key in sorted(out):
        bash_key = f"CFG_{key.replace('.', '_').replace('-', '_')}"
        value = out[key].replace('"', '\\"')
        print(f'{bash_key}="{value}"')


if __name__ == "__main__":
    main()

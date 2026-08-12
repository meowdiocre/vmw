"""Entry point for `python3 -m vmw`.

Dispatches to a submodule based on argv[1] (see vmw/__init__.py).
"""
import sys

from vmw import main

if __name__ == "__main__":
    sys.exit(main())

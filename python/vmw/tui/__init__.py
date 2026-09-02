"""Frontend layer: the Textual TUI.

Dashboard-first UX (ADR-004). Adapters only. Every operation is also a
CLI subcommand; the TUI adds no logic of its own. Screens, modals, and
workers attach to the App node.
"""

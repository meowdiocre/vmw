"""Infrastructure layer: system truth, no project opinions.

Everything here answers "what is true about this machine": distro,
CPU, bootloader, package tables, shell execution. infra imports nothing
from vmw above its own layer (import-linter "independence" contract).
Contract: plans/01-architecture-plan.md.
"""

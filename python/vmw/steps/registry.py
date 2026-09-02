"""Step registry: the ordered six (plan 02 execution order)."""

from __future__ import annotations

from dataclasses import dataclass

from vmw.infra.host import Host
from vmw.infra.probe import State


@dataclass(frozen=True)
class ProbeRow:
    name: str
    state: State
    detail: str


def _steps() -> list:
    """Import lazily to keep module import cheap and cycle-free."""
    from vmw.steps.deploy import DeployStep
    from vmw.steps.edk2 import Edk2Step
    from vmw.steps.kernel import KernelStep
    from vmw.steps.qemu import QemuStep
    from vmw.steps.vfio import VfioStep
    from vmw.steps.virtualization import VirtualizationStep

    return [
        VirtualizationStep(),
        KernelStep(),
        QemuStep(),
        Edk2Step(),
        VfioStep(),
        DeployStep(),
    ]


def ordered() -> list:
    """The six steps in execution order (plan 02)."""
    return _steps()


def by_name(name: str):
    """One step by its registry name (vmw rebuild <step>)."""
    for step in _steps():
        if step.name == name:
            return step
    return None


def probe_all(host: Host, domain: str | None = None) -> list[ProbeRow]:
    """Probe every step; used by vmw status and the TUI dashboard."""
    from vmw.steps.deploy import DeployStep

    rows = []
    for step in _steps():
        if isinstance(step, DeployStep) and domain:
            step = DeployStep(domain)
        state = step.probe(host)
        rows.append(ProbeRow(name=step.name, state=state, detail=step.probe_detail(host)))
    return rows

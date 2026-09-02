"""Orchestration layer: sequencing, dry-run, resume, single-writer lock.

The Engine runs Actions produced by steps' plan(), persists state to
.vmw/state.json (engine-only writes), and acquires the flock on .vmw/
at start [A4]. workflow may import domain packages and infra, never
frontends or steps. Contract: plans/01-architecture-plan.md.
"""

"""Domain layer: profile schema and loading.

pydantic v2 models mirroring configs/*.yml (ADR-002). Every field must
be read by genxml or a step. The schema is the doc. profiles imports
infra only. Contract: plans/01-architecture-plan.md.
"""

"""Step: the probe/plan/run contract (ADR-003).

probe() and plan() are pure functions of (Host, filesystem) and
(Profile, Host, PromptAnswers) respectively. run() executes via the
RunContext. Steps with distinct separable phases (edk2) probe and plan
per phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from vmw.infra.host import Host
from vmw.infra.probe import State
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import Prompt, PromptAnswers


class Step(ABC):
    """Base class for the six build steps."""

    name: str = ""
    title: str = ""

    @abstractmethod
    def probe(self, host: Host) -> State:
        """Is this step already done on the real system? Pure."""

    def probe_detail(self, host: Host) -> str:
        return ""

    @abstractmethod
    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        """Actions to bring the system to done. Pure."""

    def prompts(self, profile: Profile) -> list[Prompt]:
        """Questions to ask before running. Default: none."""
        return []

    def run(self, profile: Profile, ctx: RunContext) -> bool:
        """Execute the plan through ctx. Default: engine-driven."""
        raise NotImplementedError(f"step {self.name}: run() not ported yet (see plans/02)")

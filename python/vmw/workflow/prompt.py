"""Prompt: interactive question with a kind, ported from prompt.sh [A2].

kinds: confirm | choice | path | device | password. Every prompt has a
stable id; answers flow back into plan() via PromptAnswers so plans can
be rendered the same way the run will execute them. Sinks render them
(TUI modals, CLI stdin); the engine never blocks on presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Prompt:
    kind: str  # confirm | choice | path | device | password
    question: str
    choices: tuple[str, ...] = ()
    default: str | None = None
    id: str = field(default="")

    def __post_init__(self) -> None:
        if self.kind not in ("confirm", "choice", "path", "device", "password"):
            raise ValueError(f"unknown prompt kind: {self.kind}")
        if self.kind == "choice" and not self.choices:
            raise ValueError("choice prompt needs choices")

    @property
    def is_secret(self) -> bool:
        return self.kind == "password"


class PromptAnswers:
    """Answers by prompt id; supplied by the frontend once per session.

    plan() receives this so a wizard-collected answer and a --yes
    default produce the same actions. Unanswered prompts fall back to
    the prompt default (confirm=yes, choice=first) so `vmw plan`
    renders the canonical run.
    """

    def __init__(self, values: dict[str, str] | None = None):
        self.values: dict[str, str] = dict(values or {})

    def answer(self, prompt: Prompt) -> str:
        if prompt.id and prompt.id in self.values:
            return self.values[prompt.id]
        if prompt.default is not None:
            return prompt.default
        if prompt.kind == "confirm":
            return "y"
        if prompt.kind == "choice" and prompt.choices:
            return prompt.choices[0]
        return ""

    def set(self, prompt_id: str, value: str) -> None:
        self.values[prompt_id] = value

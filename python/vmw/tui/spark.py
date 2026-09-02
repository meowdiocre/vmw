"""Sparklines and severity for the top bar (plan 07).

A ring buffer of recent values rendered with Unicode block glyphs, plus
the warn/alert thresholds that turn a number amber or red. Kept separate
so it is unit-testable without a terminal.
"""

from __future__ import annotations

from collections import deque

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 8) -> str:
    """Render the last `width` values as block glyphs, scaled to their range."""
    if not values:
        return " " * width
    tail = values[-width:]
    lo = min(tail)
    hi = max(tail)
    span = hi - lo
    if span <= 0:
        # Flat series: mid-height, not a misleading full or empty bar.
        return _BLOCKS[len(_BLOCKS) // 2] * len(tail)
    out = []
    for v in tail:
        idx = int((v - lo) / span * (len(_BLOCKS) - 1) + 0.5)
        out.append(_BLOCKS[idx])
    return "".join(out)


class Series:
    """Fixed-length history of one metric, for its sparkline."""

    def __init__(self, length: int = 20):
        self._buf: deque[float] = deque(maxlen=length)

    def push(self, value: float) -> None:
        self._buf.append(value)

    def render(self, width: int = 8) -> str:
        return sparkline(list(self._buf), width)


# Semantic thresholds. These are severity, not the accent colour.
def severity(value: float, warn: float, alert: float) -> str:
    """Return 'ok' | 'warn' | 'alert' for a rising metric."""
    if value >= alert:
        return "alert"
    if value >= warn:
        return "warn"
    return "ok"

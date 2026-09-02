"""The always-present telemetry bar (plan 07).

Two rows: host on top, the selected guest below. Every number is one the
host can measure. It updates on a timer owned by the dashboard and shows
severity through colour: a metric past its warn threshold turns amber,
past alert turns red. Thermal is the one that matters most on this
hardware.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from vmw.infra.metrics import DomainSample, HostSample
from vmw.tui.spark import Series, severity

_SEV_STYLE = {"ok": "", "warn": "yellow", "alert": "bold red"}


class TopBar(Static):
    """Host and guest telemetry, refreshed by the dashboard's poller."""

    def __init__(self) -> None:
        super().__init__(id="topbar")
        self._cpu = Series()
        self._vcpu = Series()
        self._host: HostSample | None = None
        self._domain: DomainSample | None = None
        self._domain_name: str = "-"

    def compose(self) -> ComposeResult:
        yield Static(id="topbar-host")
        yield Static(id="topbar-guest")

    def update_host(self, sample: HostSample) -> None:
        self._host = sample
        self._cpu.push(sample.cpu_percent)
        self._render_host()

    def update_guest(self, name: str, sample: DomainSample | None) -> None:
        self._domain_name = name
        self._domain = sample
        if sample is not None:
            self._vcpu.push(sample.vcpu_percent)
        self._render_guest()

    # -- rendering ---------------------------------------------------------

    def _render_host(self) -> None:
        line = Text(no_wrap=True, overflow="ellipsis")
        h = self._host
        if h is None:
            line.append("HOST  sampling…", style="dim")
            self.query_one("#topbar-host", Static).update(line)
            return

        line.append("HOST  ", style="bold")
        line.append(f"cpu {h.cpu_percent:>4.0f}% ")
        line.append(self._cpu.render(8) + "  ", style="cyan")

        if h.temperature_c is not None:
            sev = severity(h.temperature_c, warn=85, alert=90)
            temp = Text(f"{h.temperature_c:.0f}°C", style=_SEV_STYLE[sev])
            if sev != "ok":
                temp.append(" !", style=_SEV_STYLE[sev])
            line.append(temp)
            line.append("  ")

        if h.mhz_max:
            mhz_style = "yellow" if h.throttled else ""
            line.append(
                Text(f"{h.mhz_current / 1000:.1f}/{h.mhz_max / 1000:.1f}GHz", style=mhz_style)
            )
            line.append("  ")

        line.append(f"mem {h.mem_used_kb / 1_048_576:.0f}/{h.mem_total_kb / 1_048_576:.0f}G  ")
        if h.swap_used_kb:
            line.append(f"swap {h.swap_used_kb / 1_048_576:.1f}G  ")

        # PSI avg10 is a 0-100 percentage of time some task was stalled.
        psi = max(h.psi_cpu, h.psi_io, h.psi_mem)
        psi_sev = severity(psi, warn=20.0, alert=50.0)
        line.append(Text(f"psi {psi:.1f}", style=_SEV_STYLE[psi_sev]))

        self.query_one("#topbar-host", Static).update(line)

    def _render_guest(self) -> None:
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append("GUEST ", style="bold")
        d = self._domain
        if d is None:
            line.append(f"{self._domain_name}  no live data", style="dim")
            self.query_one("#topbar-guest", Static).update(line)
            return

        dot = {"running": "green", "paused": "yellow", "shut off": "dim"}.get(d.state, "dim")
        line.append("● ", style=dot)
        line.append(f"{d.name} {d.state}", style=dot)
        line.append("  ")

        if d.is_running:
            line.append(f"vcpu {d.vcpu_percent:>3.0f}% ")
            line.append(self._vcpu.render(6) + "  ", style="cyan")
            if d.preemptions_per_10s is not None:
                sev = severity(d.preemptions_per_10s, warn=500, alert=2000)
                pre = Text(f"preempt {d.preemptions_per_10s}/10s", style=_SEV_STYLE[sev])
                if sev != "ok":
                    pre.append(" !", style=_SEV_STYLE[sev])
                line.append(pre)

        self.query_one("#topbar-guest", Static).update(line)

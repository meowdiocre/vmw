"""Host and guest telemetry for the dashboard top bar (plan 07, D0).

Every number here is one the host can actually measure. Guest-internal
detector numbers (CPUID latency, the VMAware TIMER ratios) are not here:
VMAware runs inside Windows and the host cannot observe them, so a live
panel for them would be inventing values.

The functions are pure over their inputs: each takes the raw text of a
/proc file or the output of a virsh command, so they unit-test against
fixtures with no running system. `sample_host()` and `sample_domain()`
read the real sources and assemble the dataclasses the UI renders.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Host
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CpuTotals:
    """One /proc/stat aggregate line, in jiffies."""

    idle: int
    total: int


def parse_proc_stat(text: str) -> dict[str, CpuTotals]:
    """Map each cpu line in /proc/stat to (idle, total) jiffies.

    Key "cpu" is the aggregate; "cpu0".."cpuN" are per-core. idle counts
    idle+iowait, the rest is busy, exactly as top computes utilisation.
    """
    out: dict[str, CpuTotals] = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        name = parts[0]
        nums = [int(p) for p in parts[1:]]
        if len(nums) < 5:
            continue
        idle = nums[3] + nums[4]  # idle + iowait
        out[name] = CpuTotals(idle=idle, total=sum(nums))
    return out


def cpu_percent(prev: CpuTotals, cur: CpuTotals) -> float:
    """Busy percentage between two /proc/stat samples of the same cpu."""
    d_total = cur.total - prev.total
    d_idle = cur.idle - prev.idle
    if d_total <= 0:
        return 0.0
    return round(100.0 * (d_total - d_idle) / d_total, 1)


def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo into a name -> kB dict (the trailing 'kB' dropped)."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            out[key.strip()] = int(fields[0])
    return out


def parse_pressure(text: str) -> float:
    """The avg10 figure from a /proc/pressure/* file ('some' line)."""
    for line in text.splitlines():
        if line.startswith("some"):
            for token in line.split():
                if token.startswith("avg10="):
                    try:
                        return float(token.split("=", 1)[1])
                    except ValueError:
                        return 0.0
    return 0.0


def parse_cpu_mhz(cpuinfo: str) -> tuple[float, float]:
    """Return (current avg MHz, max seen MHz) from /proc/cpuinfo.

    The gap between them is what makes thermal throttling visible.
    """
    mhz = [
        float(line.split(":", 1)[1])
        for line in cpuinfo.splitlines()
        if line.lower().startswith("cpu mhz")
    ]
    if not mhz:
        return 0.0, 0.0
    return round(sum(mhz) / len(mhz), 0), round(max(mhz), 0)


def read_temperature(hwmon_root: str = "/sys/class/hwmon") -> float | None:
    """Highest CPU-package temperature in °C, or None if unreadable.

    Prefers a Tctl/Tdie/Package label; falls back to the max temp input
    under any hwmon whose name looks like a CPU sensor.
    """
    from pathlib import Path

    root = Path(hwmon_root)
    if not root.is_dir():
        return None
    best: float | None = None
    cpu_chips = ("k10temp", "zenpower", "coretemp", "cpu")
    for chip in sorted(root.glob("hwmon*")):
        try:
            name = (chip / "name").read_text().strip()
        except OSError:
            name = ""
        if name and not any(c in name for c in cpu_chips):
            continue
        for temp in sorted(chip.glob("temp*_input")):
            try:
                milli = int(temp.read_text().strip())
            except (OSError, ValueError):
                continue
            celsius = milli / 1000.0
            if best is None or celsius > best:
                best = celsius
    return round(best, 1) if best is not None else None


@dataclass(frozen=True)
class HostSample:
    cpu_percent: float
    per_core: list[float]
    temperature_c: float | None
    mhz_current: float
    mhz_max: float
    mem_used_kb: int
    mem_total_kb: int
    swap_used_kb: int
    psi_cpu: float
    psi_io: float
    psi_mem: float

    @property
    def throttled(self) -> bool:
        """True when clocks are well below the peak this session has seen."""
        return self.mhz_max > 0 and self.mhz_current < 0.85 * self.mhz_max


class HostSampler:
    """Stateful host sampler: holds the previous /proc/stat for deltas.

    read() is injected so tests drive it with fixture strings. In
    production the default reader hits the real files.
    """

    def __init__(self, read: callable | None = None):
        self._read = read or _read_file
        self._prev: dict[str, CpuTotals] | None = None

    def sample(self) -> HostSample:
        cur = parse_proc_stat(self._read("/proc/stat"))
        prev = self._prev or cur
        self._prev = cur

        agg = cpu_percent(prev.get("cpu", cur["cpu"]), cur["cpu"]) if "cpu" in cur else 0.0
        per_core = [
            cpu_percent(prev[name], cur[name])
            for name in sorted(
                (n for n in cur if n != "cpu"),
                key=lambda n: int(n[3:]),
            )
            if name in prev
        ]

        mem = parse_meminfo(self._read("/proc/meminfo"))
        mem_total = mem.get("MemTotal", 0)
        mem_avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)

        mhz_cur, mhz_max = parse_cpu_mhz(self._read("/proc/cpuinfo"))

        return HostSample(
            cpu_percent=agg,
            per_core=per_core,
            temperature_c=read_temperature(),
            mhz_current=mhz_cur,
            mhz_max=mhz_max,
            mem_used_kb=mem_total - mem_avail,
            mem_total_kb=mem_total,
            swap_used_kb=swap_total - swap_free,
            psi_cpu=parse_pressure(self._read("/proc/pressure/cpu")),
            psi_io=parse_pressure(self._read("/proc/pressure/io")),
            psi_mem=parse_pressure(self._read("/proc/pressure/memory")),
        )


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------
# Guest / domain
# --------------------------------------------------------------------------


def parse_domstats(text: str) -> dict[str, str]:
    """`virsh domstats` output into a flat key -> value dict.

    Lines look like "  cpu.time=12345". The domain header line (no '=')
    is skipped.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


# virsh domstats reports state.state as a libvirt domain-state enum.
_DOMAIN_STATE = {
    "0": "no state",
    "1": "running",
    "2": "blocked",
    "3": "paused",
    "4": "shutting down",
    "5": "shut off",
    "6": "crashed",
    "7": "suspended",
}


@dataclass(frozen=True)
class DomainSample:
    name: str
    state: str  # running | shut off | paused | ...
    vcpu_count: int
    vcpu_percent: float
    balloon_kb: int
    disk_rd_bytes: int
    disk_wr_bytes: int
    net_rx_bytes: int
    net_tx_bytes: int
    preemptions_per_10s: int | None = None
    sampled_at: float = field(default_factory=time.monotonic)

    @property
    def is_running(self) -> bool:
        return self.state == "running"


def domain_from_stats(name: str, stats: dict[str, str]) -> DomainSample:
    """Build a DomainSample from a parsed domstats dict (rates are 0)."""

    def num(key: str, default: int = 0) -> int:
        try:
            return int(stats.get(key, default))
        except (TypeError, ValueError):
            return default

    return DomainSample(
        name=name,
        state=_DOMAIN_STATE.get(stats.get("state.state", ""), "unknown"),
        vcpu_count=num("vcpu.current"),
        vcpu_percent=0.0,
        balloon_kb=num("balloon.current"),
        disk_rd_bytes=num("block.0.rd.bytes"),
        disk_wr_bytes=num("block.0.wr.bytes"),
        net_rx_bytes=num("net.0.rx.bytes"),
        net_tx_bytes=num("net.0.tx.bytes"),
    )


def qemu_preemptions(pids_status: list[str]) -> int:
    """Sum nonvoluntary_ctxt_switches across a qemu process's vCPU tasks.

    Each element is the text of one /proc/<pid>/task/<tid>/status. Only
    tasks named CPU N/KVM are counted, so emulator threads do not inflate
    the number. This is the metric that surfaced the NVMe managed-IRQ
    contention: it separates "guest is busy" from "host is stealing the
    guest's cores".
    """
    total = 0
    for status in pids_status:
        is_vcpu = False
        switches = 0
        for line in status.splitlines():
            if line.startswith("Name:"):
                is_vcpu = "CPU" in line and "KVM" in line
            elif line.startswith("nonvoluntary_ctxt_switches:"):
                try:
                    switches = int(line.split(":", 1)[1])
                except ValueError:
                    switches = 0
        if is_vcpu:
            total += switches
    return total


def sample_domain(
    name: str,
    virsh: str = "virsh",
    run: callable = subprocess.run,
    which: callable = shutil.which,
) -> DomainSample | None:
    """domstats for one domain, or None if virsh/domain is unavailable.

    Never raises: the dashboard degrades to "no live data" rather than
    crashing when libvirt is unreachable or the call needs privileges.
    """
    if which(virsh) is None:
        return None
    try:
        proc = run(
            [virsh, "--connect", "qemu:///system", "domstats", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return domain_from_stats(name, parse_domstats(proc.stdout))

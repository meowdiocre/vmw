"""Metrics sampler unit tests (plan 07, D0). Pure, fixture-driven."""

from __future__ import annotations

from vmw.infra import metrics


def test_parse_proc_stat_idle_and_total():
    text = "cpu  100 0 50 800 50 0 0\ncpu0 10 0 5 80 5 0 0\n"
    stats = metrics.parse_proc_stat(text)
    assert stats["cpu"].idle == 850  # idle 800 + iowait 50
    assert stats["cpu"].total == 1000
    assert "cpu0" in stats


def test_cpu_percent_between_samples():
    prev = metrics.CpuTotals(idle=850, total=1000)
    cur = metrics.CpuTotals(idle=900, total=1100)
    # 100 jiffies elapsed, 50 idle -> 50% busy
    assert metrics.cpu_percent(prev, cur) == 50.0


def test_cpu_percent_no_elapsed_time_is_zero():
    same = metrics.CpuTotals(idle=10, total=20)
    assert metrics.cpu_percent(same, same) == 0.0


def test_parse_meminfo():
    text = "MemTotal:  16000 kB\nMemAvailable: 4000 kB\nSwapTotal: 8000 kB\nSwapFree: 6000 kB\n"
    mem = metrics.parse_meminfo(text)
    assert mem["MemTotal"] == 16000
    assert mem["MemAvailable"] == 4000


def test_parse_pressure_reads_avg10():
    text = "some avg10=0.74 avg60=0.85 avg300=0.98 total=409736941\nfull avg10=0.00 ...\n"
    assert metrics.parse_pressure(text) == 0.74


def test_parse_cpu_mhz_current_and_max():
    text = "cpu MHz : 3000.0\ncpu MHz : 3800.0\ncpu MHz : 3400.0\n"
    cur, mx = metrics.parse_cpu_mhz(text)
    assert cur == 3400.0
    assert mx == 3800.0


def test_host_sampler_first_sample_has_zero_deltas():
    fixtures = {
        "/proc/stat": "cpu 100 0 50 800 50 0 0\ncpu0 50 0 25 400 25 0 0\n",
        "/proc/meminfo": (
            "MemTotal: 16000 kB\nMemAvailable: 4000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
        ),
        "/proc/cpuinfo": "cpu MHz : 3000.0\n",
        "/proc/pressure/cpu": "some avg10=0.10 total=1\n",
        "/proc/pressure/io": "some avg10=0.00 total=1\n",
        "/proc/pressure/memory": "some avg10=0.00 total=1\n",
    }
    sampler = metrics.HostSampler(read=lambda p: fixtures[p])
    s = sampler.sample()
    assert s.cpu_percent == 0.0  # no previous sample -> no delta
    assert s.mem_used_kb == 12000
    assert s.psi_cpu == 0.10


def test_host_sampler_second_sample_computes_busy():
    seq = [
        {
            "/proc/stat": "cpu 100 0 50 800 50 0 0\n",
            "/proc/meminfo": "MemTotal: 16000 kB\nMemAvailable: 4000 kB\n",
            "/proc/cpuinfo": "cpu MHz : 3000.0\n",
            "/proc/pressure/cpu": "some avg10=0.0 total=1\n",
            "/proc/pressure/io": "some avg10=0.0 total=1\n",
            "/proc/pressure/memory": "some avg10=0.0 total=1\n",
        },
        {
            "/proc/stat": "cpu 150 0 50 850 50 0 0\n",  # +50 busy, +50 idle over +100
            "/proc/meminfo": "MemTotal: 16000 kB\nMemAvailable: 4000 kB\n",
            "/proc/cpuinfo": "cpu MHz : 3000.0\n",
            "/proc/pressure/cpu": "some avg10=0.0 total=1\n",
            "/proc/pressure/io": "some avg10=0.0 total=1\n",
            "/proc/pressure/memory": "some avg10=0.0 total=1\n",
        },
    ]
    box = {"i": 0}

    def read(path):
        return seq[box["i"]][path]

    sampler = metrics.HostSampler(read=read)
    sampler.sample()
    box["i"] = 1
    s = sampler.sample()
    assert s.cpu_percent == 50.0


def test_throttled_flag():
    s = metrics.HostSample(
        cpu_percent=80,
        per_core=[],
        temperature_c=90,
        mhz_current=3000,
        mhz_max=4400,
        mem_used_kb=0,
        mem_total_kb=1,
        swap_used_kb=0,
        psi_cpu=0,
        psi_io=0,
        psi_mem=0,
    )
    assert s.throttled is True


def test_parse_domstats_and_state():
    text = "Domain: 'aptwannabe'\n  state.state=1\n  vcpu.current=8\n  balloon.current=8388608\n"
    stats = metrics.parse_domstats(text)
    dom = metrics.domain_from_stats("aptwannabe", stats)
    assert dom.state == "running"
    assert dom.is_running
    assert dom.vcpu_count == 8


def test_domain_shut_off_state():
    stats = metrics.parse_domstats("  state.state=5\n")
    dom = metrics.domain_from_stats("x", stats)
    assert dom.state == "shut off"
    assert not dom.is_running


def test_qemu_preemptions_counts_only_vcpu_threads():
    vcpu = "Name:\tCPU 4/KVM\nnonvoluntary_ctxt_switches:\t3330\n"
    emulator = "Name:\tqemu-system-x86\nnonvoluntary_ctxt_switches:\t99999\n"
    other = "Name:\tCPU 5/KVM\nnonvoluntary_ctxt_switches:\t1559\n"
    total = metrics.qemu_preemptions([vcpu, emulator, other])
    assert total == 3330 + 1559  # emulator thread excluded


def test_sample_domain_returns_none_without_virsh():
    got = metrics.sample_domain("x", which=lambda _: None)
    assert got is None


def test_sample_domain_returns_none_on_failure():
    class Proc:
        returncode = 1
        stdout = ""

    got = metrics.sample_domain(
        "x",
        which=lambda _: "/usr/bin/virsh",
        run=lambda *a, **k: Proc(),
    )
    assert got is None

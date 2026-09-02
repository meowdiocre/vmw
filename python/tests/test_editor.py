"""Schema-driven editor: formgen, round-trip save, domain facts (plan 07)."""

from __future__ import annotations

import pytest
from vmw.infra import domain_facts
from vmw.profiles import editor as pe
from vmw.profiles.loader import load_config
from vmw.tui import formgen
from vmw.tui.spark import Series, severity, sparkline

# -- formgen ---------------------------------------------------------------


def test_formgen_maps_literal_to_select():
    profile = load_config("example")
    tree = formgen.build_sections(profile)
    device = next(s for s in tree.sections if s.name == "device")
    disk_bus = next(f for f in device.fields if f.name == "disk_bus")
    assert disk_bus.kind == "select"
    assert disk_bus.choices == ("nvme", "sata", "virtio", "ide")
    assert disk_bus.value == "nvme"


def test_formgen_maps_bool_to_switch():
    tree = formgen.build_sections(load_config("example"))
    features = next(s for s in tree.sections if s.name == "features")
    hyperv = next(f for f in features.fields if f.name == "hyperv")
    assert hyperv.kind == "switch"
    assert hyperv.value is True


def test_formgen_maps_int_with_bounds():
    tree = formgen.build_sections(load_config("example"))
    vm = next(s for s in tree.sections if s.name == "vm")
    mem = next(f for f in vm.fields if f.name == "memory_mib")
    assert mem.kind == "int"
    assert mem.minimum == 16


def test_formgen_nests_sections():
    tree = formgen.build_sections(load_config("example"))
    cpu = next(s for s in tree.sections if s.name == "cpu")
    assert any(sub.name == "topology" for sub in cpu.sections)


def test_apply_edit_sets_nested_path():
    data = {"cpu": {"topology": {"cores": 4}}}
    formgen.apply_edit(data, "cpu.topology.cores", "6", "int")
    assert data["cpu"]["topology"]["cores"] == 6


def test_apply_edit_coerces_switch():
    data = {}
    formgen.apply_edit(data, "features.hyperv", True, "switch")
    assert data["features"]["hyperv"] is True


# -- round-trip save -------------------------------------------------------


def _seed_configs(tmp_path):
    src = load_config("example")  # ensure a valid document shape
    text = (
        "# a comment that must survive\n"
        "name: rtptest\n"
        "vm:\n  memory_mib: 4096\n  vcpus: 4\n"
        "device:\n  disk_bus: nvme\n  disk_size_gb: 100\n"
    )
    (tmp_path / "rtptest.yml").write_text(text)
    return src


def test_roundtrip_preserves_comments(tmp_path):
    _seed_configs(tmp_path)
    doc = pe.load_roundtrip("rtptest", configs_dir=tmp_path)
    formgen.apply_edit(doc, "device.disk_bus", "sata", "select")
    pe.save("rtptest", doc, configs_dir=tmp_path)
    saved = (tmp_path / "rtptest.yml").read_text()
    assert "# a comment that must survive" in saved
    assert "disk_bus: sata" in saved


def test_save_rejects_invalid_profile(tmp_path):
    _seed_configs(tmp_path)
    doc = pe.load_roundtrip("rtptest", configs_dir=tmp_path)
    formgen.apply_edit(doc, "vm.vcpus", "0", "int")  # ge=1
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        pe.save("rtptest", doc, configs_dir=tmp_path)
    # the file on disk is untouched
    assert "vcpus: 4" in (tmp_path / "rtptest.yml").read_text()


def test_unmodified_save_is_byte_identical(tmp_path):
    _seed_configs(tmp_path)
    before = (tmp_path / "rtptest.yml").read_text()
    doc = pe.load_roundtrip("rtptest", configs_dir=tmp_path)
    pe.save("rtptest", doc, configs_dir=tmp_path)
    after = (tmp_path / "rtptest.yml").read_text()
    assert before == after


# -- domain facts ----------------------------------------------------------


def test_domain_facts_from_profile_shows_intended_bus():
    profile = load_config("example")
    facts = domain_facts.facts_from_profile(profile)
    assert facts.defined is False
    assert facts.disk_bus == "nvme"  # the profile's intent
    assert "not deployed" in facts.source_label


def test_parse_dumpxml_reads_sata_drift():
    xml = """
    <domain>
      <devices>
        <disk type='file' device='disk'>
          <target dev='sda' bus='sata'/>
        </disk>
        <interface type='network'>
          <mac address='52:54:00:e1:1a:96'/>
          <source network='vmw-Router'/>
        </interface>
        <hostdev mode='subsystem' type='pci'/>
        <tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>
      </devices>
      <os><loader>/opt/vmw/firmware/OVMF_CODE.fd</loader></os>
    </domain>
    """
    facts = domain_facts.parse_dumpxml("aptwannabe", xml)
    assert facts.defined is True
    assert facts.disk_bus == "sata"  # the live drift, visible at a glance
    assert facts.mac == "52:54:00:e1:1a:96"
    assert facts.gpu == "pci passthrough"


# -- sparkline -------------------------------------------------------------


def test_sparkline_scales_to_range():
    line = sparkline([0, 50, 100], width=3)
    assert line[0] == "▁"
    assert line[-1] == "█"


def test_sparkline_flat_series_is_midheight():
    assert set(sparkline([5, 5, 5], width=3)) == {"▅"}


def test_severity_thresholds():
    assert severity(10, warn=20, alert=50) == "ok"
    assert severity(30, warn=20, alert=50) == "warn"
    assert severity(60, warn=20, alert=50) == "alert"


def test_series_ring_buffer_bounds_length():
    s = Series(length=3)
    for v in (1, 2, 3, 4, 5):
        s.push(v)
    assert len(s.render(10)) == 3

"""deploy step: genxml + define domain.

Probes: virsh dominfo <profile-name>. Copies patches/QEMU/*.aml to
/opt/vmw/firmware/ before define. Domain XML is rendered by the typed
emitter (vmw.genxml.build_domain_xml).
"""

from __future__ import annotations

from pathlib import Path

from vmw.infra.host import Host
from vmw.infra.probe import State, domain_defined
from vmw.profiles.schema import Profile
from vmw.workflow.action import Action
from vmw.workflow.context import RunContext
from vmw.workflow.prompt import PromptAnswers
from vmw.workflow.step import Step

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path("/opt/vmw")
PATCHES_QEMU = REPO_ROOT / "patches" / "QEMU"


class DeployStep(Step):
    name = "deploy"
    title = "Deploy VM from profile"

    def __init__(self, domain: str | None = None):
        self.domain = domain

    def probe(self, host: Host) -> State:
        # probe() has no profile access; only an explicit domain gives a
        # trustworthy answer. With no domain we report MISSING so the
        # engine never wrongly skips a define (plan() resolves the real
        # domain from the profile and re-guards on domain_defined).
        if self.domain is None:
            return State.MISSING
        if domain_defined(self.domain):
            return State.DONE
        return State.MISSING

    def probe_detail(self, host: Host) -> str:
        if self.domain is None:
            return "domain resolved from profile at plan time"
        if domain_defined(self.domain):
            return f"domain {self.domain} defined in libvirt"
        return f"domain {self.domain} not defined"

    def plan(self, profile: Profile, host: Host, answers: PromptAnswers) -> list[Action]:
        actions: list[Action] = []
        domain = self.domain or profile.domain_name
        out_xml = REPO_ROOT / "configs" / f"{profile.name}.xml"

        # 1. copy .aml blobs (NEW: the fake_battery/spoofed_devices
        #    AML that the guest needs is staged alongside the firmware)
        actions.append(
            Action(
                key="deploy.copy_aml",
                func=_copy_aml_files,
                describe="copy patches/QEMU/*.aml -> /opt/vmw/firmware/",
            )
        )

        # Guard (deploy.sh): refuse to clobber an existing domain. The
        # plan renders nothing beyond the .aml copy when one exists.
        if domain_defined(domain):
            return actions

        # 2. generate the domain XML via the typed emitter.
        actions.append(
            Action(
                key="deploy.genxml",
                func=lambda ctx: _generate_xml(ctx, profile, out_xml),
                describe=f"generate {out_xml}",
            )
        )

        # 3. schema validation via virt-xml-validate (if present)
        actions.append(
            Action(
                key="deploy.validate",
                func=lambda ctx: _validate_xml(ctx, out_xml),
                describe="virt-xml-validate the generated XML",
            )
        )

        # 4. define (guard: refuse to clobber an existing domain)
        actions.append(
            Action(
                key="deploy.define",
                func=lambda ctx: _define_domain(ctx, domain, out_xml),
                describe=f"virsh define {domain}",
            )
        )

        return actions


def _copy_aml_files(ctx: RunContext) -> None:
    """Copy the QEMU AML blobs referenced by acpitable to /opt/vmw/firmware."""
    fw_dir = OUT_DIR / "firmware"
    ctx.sh(["mkdir", "-p", str(fw_dir)], root=True)
    copied = []
    for aml in sorted(PATCHES_QEMU.glob("*.aml")):
        target = fw_dir / aml.name
        ctx.sh(["cp", str(aml), str(target)], root=True)
        copied.append(aml.name)
    if copied:
        ctx.log(f"copied {', '.join(copied)} to {fw_dir}")


def _generate_xml(ctx: RunContext, profile: Profile, out_xml: Path) -> None:
    """Render the domain XML from the typed Profile."""
    from vmw.genxml import build_domain_xml, to_string

    out_xml.write_bytes(to_string(build_domain_xml(profile)))
    ctx.log(f"generated {out_xml}")


def _validate_xml(ctx: RunContext, out_xml: Path) -> None:
    import shutil

    if shutil.which("virt-xml-validate") is None:
        ctx.log("virt-xml-validate not present; skipping schema validation")
        return
    ctx.sh(["virt-xml-validate", str(out_xml), "domain"])
    ctx.log("schema validation passed")


def _define_domain(ctx: RunContext, domain: str, out_xml: Path) -> None:
    """Refuse to clobber an existing domain (deploy.sh guard)."""
    import subprocess

    check = subprocess.run(
        ["virsh", "--connect", "qemu:///system", "dominfo", domain],
        capture_output=True,
        check=False,
    )
    if check.returncode == 0:
        raise RuntimeError(
            f"domain '{domain}' already exists. Undefine it first:\n"
            f"  sudo virsh undefine --nvram '{domain}'"
        )
    ctx.sh(["virsh", "--connect", "qemu:///system", "define", str(out_xml)], root=True)
    ctx.log(f"domain '{domain}' defined from {out_xml}")
    ctx.log(f"start it with: sudo virsh start '{domain}'")

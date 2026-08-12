<div align="center">

# VMW — VM Workspace

A personal VM workspace for automating Linux virtualization setup.

[![](https://dcbadge.limes.pink/api/server/https://discord.gg/hNVHChp7PX)](https://discord.gg/hNVHChp7PX)

</div>

---

## Instructions

<details>
<summary>Expand for details...</summary>

#### 1. Clone Git repository
```sh
git clone --single-branch --depth=1 https://github.com/meowdiocre/vmw
```

#### 2. Change directory
```sh
cd vmw/
```

#### 3. Execute
```sh
./main.sh
```
- Experimental distro support:
```sh
EXPERIMENTAL=1 ./main.sh
```

---

### 4. Update repository
- ***Make sure you're in the `vmw/` root directory when running the command below!***
```sh
git fetch --all && git reset --hard origin/main
```

</details>

---

## Supported Distros

| Distro         | Status       |
|----------------|--------------|
| Arch based     | Supported    |
| Debian based   | Experimental |
| Fedora based   | Experimental |
| openSUSE based | Experimental |

## Prerequisites

- `git` package
- Supported Linux distribution
- UEFI/BIOS Settings:
  - CPU virtualization extensions (VT-x / AMD-V)
  - IOMMU support (VT-d / AMD-Vi)
- A dGPU for passthrough (recommended)

## Troubleshooting

#### QEMU log
```
vfio 0000:01:00.0: failed to setup container for group 13: Failed to set group container: Invalid argument
```
#### dmesg log
```
vfio-pci 0000:01:00.0: Firmware has requested this device have a 1:1 IOMMU mapping, rejecting configuring the device without a 1:1 mapping. Contact your platform vendor.
```

- Disable `Pre-boot DMA Protection` (Needed for VFIO)
  - (*Change `IOMMU` from `[Auto]` to `[Enabled]` to find hidden setting*)

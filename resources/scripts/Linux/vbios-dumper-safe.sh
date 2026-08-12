#!/usr/bin/env bash
# Safe VBIOS dumper for laptops with timeout guards
set -euo pipefail

BDF="0000:01:00.0"
DEV="/sys/bus/pci/devices/$BDF"
OUT="${HOME}/VBIOS_${BDF}.rom"

echo "[*] Targeting GPU at $BDF"
echo "[*] Checking device..."

if [[ ! -d "$DEV" ]]; then
    echo "[!] Device $DEV not found!"
    exit 1
fi

# Check current driver
current_driver=""
if [[ -L "$DEV/driver" ]]; then
    current_driver=$(readlink -f "$DEV/driver")
    current_driver=${current_driver##*/}
    echo "[*] Currently bound to driver: $current_driver"
else
    echo "[*] No driver currently bound"
fi

# ── Step 1: Unbind driver (critical on laptops) ──
if [[ -n "$current_driver" && -f "$DEV/driver/unbind" ]]; then
    echo "[*] Attempting to unbind from $current_driver..."
    if ! echo "$BDF" > "$DEV/driver/unbind" 2>/dev/null; then
        echo "[!] Unbind failed — driver is busy."
        echo "    You may need to stop Display Manager or unload NVIDIA modules first."
        echo "    Try: sudo modprobe -r nvidia-drm nvidia-modeset nvidia-uvm nvidia"
        exit 1
    fi

    # Verify unbind worked
    sleep 0.5
    if [[ -L "$DEV/driver" ]]; then
        echo "[!] Unbind reported success but device still has driver bound."
        echo "    The kernel module likely has active references."
        exit 1
    fi
    echo "[*] Unbind successful"
fi

# ── Step 2: Enable ROM bar ──
echo "[*] Enabling ROM..."
if ! timeout 5 bash -c "echo 1 > '$DEV/rom'" 2>/dev/null; then
    echo "[!] Failed to enable ROM (timed out or permission denied)"
    [[ -n "${current_driver:-}" ]] && echo "    Try: echo '$BDF' > /sys/bus/pci/drivers/$current_driver/bind"
    exit 1
fi

# ── Step 3: Dump with timeout ──
echo "[*] Dumping VBIOS (will timeout after 10s if hung)..."
if ! timeout 10 bash -c "cat '$DEV/rom' > '$OUT'" 2>/dev/null; then
    echo "[!] ROM read hung or failed — this is common on laptop GPUs."
    echo 0 > "$DEV/rom" 2>/dev/null || true

    # Rebind if we unbound
    if [[ -n "${current_driver:-}" && -d "/sys/bus/pci/drivers/$current_driver" ]]; then
        echo "$BDF" > "/sys/bus/pci/drivers/$current_driver/bind" 2>/dev/null || true
    fi
    exit 1
fi

# ── Step 4: Disable ROM bar ──
echo 0 > "$DEV/rom" 2>/dev/null || true

# ── Step 5: Rebind driver ──
if [[ -n "${current_driver:-}" && -d "/sys/bus/pci/drivers/$current_driver" ]]; then
    echo "[*] Rebinding to $current_driver..."
    echo "$BDF" > "/sys/bus/pci/drivers/$current_driver/bind" 2>/dev/null || echo "[!] Rebind failed (you may need to reboot or reload modules)"
fi

SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null)
if [[ "$SIZE" -lt 1000 ]]; then
    echo "[!] Dumped file is too small (${SIZE} bytes) — likely invalid."
    rm -f "$OUT"
    exit 1
fi

echo "[*] Success! VBIOS saved to: $OUT (${SIZE} bytes)"
file "$OUT" 2>/dev/null || true
xxd -l 32 "$OUT" 2>/dev/null || od -A x -t x1z -v -N 32 "$OUT"

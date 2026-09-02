# Roadmap

Current detection status and next steps. Every number is dated with
its VMAware run.

## Detection status

**1 of 85 checks pending in-guest confirmation** (as of 2026-08-28).

- MEASURED_BOOT: fixed 2026-08-28 (commit ee4e314). See
  [Firmware: MEASURED_BOOT](firmware/measured-boot.md).
- BOOT_LOGO: fixed 2026-08-28 (commit ee4e314). See
  [Firmware: BOOT_LOGO](firmware/boot-logo.md).
- TIMER (memory-ratio component): the sole expected residual. See
  [Kernel: TIMER](kernel/timer.md).

**Next action:** re-run VMAware in-guest and update every dated
status line above with the confirmed result.

# Controlled Mixed SATA and USB Native Wipe

This procedure performs parallel native zero overwrites of the two internal SATA
disks and the three currently installed USB-enclosure disks. It destroys every
addressable byte on all five explicitly armed targets.

## Current exact targets

Populate the target list from a fresh inventory immediately before each run.
Do not publish or reuse real serial numbers and capacities:

```text
SATA  SERIAL_1:SIZE_BYTES_1
SATA  SERIAL_2:SIZE_BYTES_2
USB   SERIAL_3:SIZE_BYTES_3
USB   SERIAL_4:SIZE_BYTES_4
USB   SERIAL_5:SIZE_BYTES_5
```

Stop if a new inventory differs in serial, capacity, interface, or protection
status. Disk numbers are current addresses and are not authorization identities.

## Preflight

Use a new Administrator PowerShell. Run the suite before arming gates, then set
the SATA inventory gate and capture a new inventory:

```powershell
.\.venv\Scripts\python.exe -m pytest

$env:DISKWIPER_ENABLE_INTERNAL_SATA_WIPES = "I_UNDERSTAND_INTERNAL_SATA_WIPES_DESTROY_DATA"
.\.venv\Scripts\python.exe -m diskwiper.main --inventory-only |
  Tee-Object mixed-before.txt
```

Run `--native-preflight DISK_NUMBER` separately for all five current disk
numbers. Confirm that every serial, byte capacity, and sector geometry matches
the inventory and target list. Do not proceed if any disk is missing, protected,
or different.

Close applications using these disks. Disable sleep and hibernation for the
duration. Keep the enclosure and PC on stable power. Do not start this procedure
while any earlier wipe job or DiskWiper instance remains active.

## Launch all five armed targets

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
$env:DISKWIPER_ENABLE_NATIVE_WIPES = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"

.\.venv\Scripts\python.exe -m diskwiper.main --enable-real-wipes `
  --real-backend native `
  --native-test-target "SERIAL_1:SIZE_BYTES_1" `
  --native-test-target "SERIAL_2:SIZE_BYTES_2" `
  --native-test-target "SERIAL_3:SIZE_BYTES_3" `
  --native-test-target "SERIAL_4:SIZE_BYTES_4" `
  --native-test-target "SERIAL_5:SIZE_BYTES_5"
```

Confirm the `EXPERIMENTAL native raw zero overwrite` banner. Select exactly
these five disks and use **Wipe All Selected Disks**. Complete the full serial
confirmation independently for every disk.

## During the run

- Do not close DiskWiper, reboot, sleep, hibernate, disconnect the enclosure, or
  power-cycle any target while a job is active.
- Do not run formatting, partitioning, SMART, benchmark, or other storage tools
  against these disks.
- Shared USB bandwidth may make the enclosure disks substantially slower than
  SATA, and total completion time is governed by the slowest disk.
- Each disk has independent progress and verification. A failure or cancellation
  on one disk does not imply success or authorization to disturb another.
- `100%` is not sufficient; each disk must independently reach `COMPLETE` after
  flush, identity revalidation, property refresh, and zero-partition verification.

## Completion

After all five rows show `COMPLETE`, preserve the application log and history,
then close DiskWiper and clear all session gates:

```powershell
Remove-Item Env:DISKWIPER_ENABLE_REAL_WIPES
Remove-Item Env:DISKWIPER_ENABLE_NATIVE_WIPES
Remove-Item Env:DISKWIPER_ENABLE_INTERNAL_SATA_WIPES
```

Set only the SATA inventory gate again, capture `mixed-after.txt`, and verify the
same five identities are present with zero partitions. Preserve both inventory
captures, elapsed times, average speeds, and terminal records. Power-cycle only
after all evidence is captured, then confirm every intended disk is rediscovered.

Because the USB bridge exposes bay identities rather than true media serials,
history is audit evidence for this run and must not be treated as proof about a
later replacement disk installed in the same bay.

## Observed startup issue

During an early five-disk launch, one job reached `ERROR` before writing because
last-second PowerShell discovery timed out while the other jobs were starting.
The other jobs continued normally. This was a transient inventory failure, not
an identity mismatch or raw write error. The native backend now retries one
failed discovery before rejecting a job.

## Completed mixed test — 2026-08-19

The relaunched five-disk run completed successfully. Every target reached
`COMPLETE`, displayed `100.0%`, and passed the native backend's final
zero-partition verification.

Keep the exact device identities, timings, and throughput in private test
records. This document should contain only the procedure and qualitative result.

The attached activity capture explicitly recorded the `VERIFYING` to `COMPLETE`
transition and `no partitions remain` result for disks 0, 1, and 5. Earlier
completion events for disks 4 and 6 had scrolled out of the bounded activity
buffer, while the final screenshot independently showed all five terminal rows,
their durations, average speeds, 100% progress, and empty volume columns.

This validates concurrent native wiping across internal SATA and a three-disk USB
enclosure, independent progress and completion, sustained shared USB throughput,
the transient-discovery retry used by disk 5 on relaunch, and final verification
for all five targets.

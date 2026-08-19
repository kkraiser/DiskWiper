# Controlled Two-Disk Internal SATA Wipe

This procedure destroys every addressable byte on two explicitly armed internal
SATA disks. The SATA allowance does not bypass any other protection. A disk that
is boot, system, configured for firmware boot, hosts a protected path, lacks a
complete identity, or is on the persistent protected list remains protected.

## Establish the exact targets

Open a new Administrator PowerShell in the project directory. Run the automated
suite before arming any session gates, then set only the temporary SATA inventory
gate:

```powershell
.\.venv\Scripts\python.exe -m pytest

$env:DISKWIPER_ENABLE_INTERNAL_SATA_WIPES = "I_UNDERSTAND_INTERNAL_SATA_WIPES_DESTROY_DATA"
.\.venv\Scripts\python.exe -m diskwiper.main --inventory-only |
  Tee-Object sata-before.txt
```

Stop unless exactly the two intended disks are reported `READY` with bus type
`SATA`. Record each complete serial and capacity from this fresh inventory. Do
not infer identity from disk number, model, capacity alone, or an older capture.
Physically disconnect other non-system storage where practical.

Run a read-only preflight for each current disk number:

```powershell
.\.venv\Scripts\python.exe -m diskwiper.main --native-preflight DISK_NUMBER_1
.\.venv\Scripts\python.exe -m diskwiper.main --native-preflight DISK_NUMBER_2
```

Read-only preflight needs the SATA gate so that the disks pass the bus check; it
does not need either destructive-mode gate.

Confirm that each preflight serial, byte capacity, and sector geometry matches
the inventory. If either command fails or any identity differs, stop.

## Arm only those two identities

In the same Administrator PowerShell, keep the SATA gate set, add both native
destructive gates, and replace the placeholders with the freshly verified values:

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
$env:DISKWIPER_ENABLE_NATIVE_WIPES = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"

.\.venv\Scripts\python.exe -m diskwiper.main --enable-real-wipes `
  --real-backend native `
  --native-test-target "SERIAL_1:SIZE_BYTES_1" `
  --native-test-target "SERIAL_2:SIZE_BYTES_2"
```

The banner must say `EXPERIMENTAL native raw zero overwrite`. Each disk requires
its own complete-serial confirmation.

## First run: controlled cancellation

For the first test, select and start only one of the two SATA disks. Leave the
other SATA disk unselected. After several minutes of confirmed write progress,
record the displayed percentage, speed, ETA, and elapsed time, then use that
disk's `Cancel` action once.

Expected results:

- cancellation is cooperative and may wait for the current write chunk;
- the row reaches `CANCELLED / INCOMPLETE`, not `COMPLETE` or `ERROR`;
- displayed progress is greater than 0% and less than 100%;
- the application remains responsive and the other disk is not started or
  changed;
- history records the cancelled/incomplete terminal state and does not report a
  successful physical wipe.

Do not disconnect, power-cycle, close DiskWiper, or force-stop the process while
waiting for cancellation. The partially overwritten disk is deliberately
unusable and must not be treated as sanitized. Preserve the log and history entry.
Any later complete wipe of this disk must restart at byte zero; resume is not
supported.

After confirming the cancellation behavior, close DiskWiper normally, verify no
wipe job remains active, and relaunch with the same three gates and exact targets.
Then select the intended disk or disks for the full completion test.

### Observed cancellation result — 2026-08-18

The first internal SATA cancellation test passed on disk serial `ZX20HKS9`:

```text
Before cancel: WIPING, 3m elapsed, 0.2%, approximately 270.8 MB/s average
After cancel:  CANCELLED / INCOMPLETE, 3m elapsed, 0.2%, stopped
Restart:       Began again from byte zero with behavior similar to the first run
Other disk:    Remained READY and unchanged
```

Raw processed bytes were not displayed and were therefore not part of the manual
UI verification.

## Completion

Wait for every disk started for the full test to reach `COMPLETE`; 100% alone is
insufficient. Preserve the
log and history, then close DiskWiper and clear all three session gates:

```powershell
Remove-Item Env:DISKWIPER_ENABLE_REAL_WIPES
Remove-Item Env:DISKWIPER_ENABLE_NATIVE_WIPES
Remove-Item Env:DISKWIPER_ENABLE_INTERNAL_SATA_WIPES
```

Capture a final inventory (the SATA gate must be set again for a `READY` result)
and verify that both exact identities remain present with zero partitions. Treat
any cancelled, disconnected, short-write, flush-error, identity-mismatch, or
post-wipe verification failure as incomplete and wipe that disk again from byte
zero before considering it erased.

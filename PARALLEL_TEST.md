# Controlled Four-Disk Native Wipe

This procedure destroys all addressable data on four explicitly armed targets.
The current targets total approximately 40.7 TB, so this is not reliably an
overnight operation. At 300 MB/s aggregate it takes about 38 hours; slower inner
tracks, USB sharing, or per-drive limits can extend it further.

## Armed identities

Populate these placeholders from a fresh inventory immediately before the test.
Do not publish or reuse real serial numbers and capacities.

```text
SERIAL_1:SIZE_BYTES_1
SERIAL_2:SIZE_BYTES_2
SERIAL_3:SIZE_BYTES_3
SERIAL_4:SIZE_BYTES_4
```

These are enclosure bay identities combined with exact current capacities. Stop
if inventory reports any different serial or capacity.

## Preflight

From a new Administrator PowerShell using the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m diskwiper.main --inventory-only |
  Tee-Object parallel-before.txt
```

Run `--native-preflight N` separately for every current USB disk number. Confirm
that all four commands pass and map to the identities above. Disk numbers may
change after any reconnect and must not be copied from an older session.

Disconnect other valuable removable storage where practical. Close applications
that may hold files on these disks. Ensure Windows will not sleep or hibernate
during the multi-day operation, and ensure the enclosure and PC have stable power.

## Launch

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
$env:DISKWIPER_ENABLE_NATIVE_WIPES = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"

.\.venv\Scripts\python.exe -m diskwiper.main --enable-real-wipes `
  --real-backend native `
  --native-test-target "SERIAL_1:SIZE_BYTES_1" `
  --native-test-target "SERIAL_2:SIZE_BYTES_2" `
  --native-test-target "SERIAL_3:SIZE_BYTES_3" `
  --native-test-target "SERIAL_4:SIZE_BYTES_4"
```

Confirm the experimental native banner. Select exactly the four armed disks and
use **Wipe All Selected Disks**. Each disk receives its own complete-serial
confirmation. A job starts only after its individual confirmation succeeds.

## Operating rules

- Do not close DiskWiper, disconnect USB, power-cycle the enclosure, allow the PC
  to sleep, or reboot while any job is active.
- Do not run Disk Management, formatting tools, SMART polling, or other storage
  utilities against these disks during the wipe.
- Each disk has independent progress, speed, ETA, cancellation, and history.
- Cancelling one job leaves that disk incomplete but does not authorize stopping
  or changing another job.
- A completed disk must pass identity and zero-partition verification independently.

## Completion

Wait until all four rows reach `COMPLETE`; 100% alone is not sufficient. Then
clear both environment gates, capture `parallel-after.txt`, and verify four
`native-zero-overwrite` history records with exact capacity byte counts. Preserve
the application log and captures, then power-cycle and confirm history recognition
for every bay.

# Controlled Native Wipe Test

The first native test must use an expendable disk. Completing this procedure
destroys every addressable byte on the selected device.

## Current intended target

The expendable 150 GB disk was most recently observed as:

```text
Bay identity: 21A000000419
Size:         150038863360 bytes
Last number:  Disk 4
```

The disk number is not an identity. If either serial or size differs at test
time, stop and investigate rather than changing the target casually.

## Before arming destructive mode

1. Commit and push the current branch, and confirm the automated suite passes.
2. Close applications that may have files open on the target disk.
3. Disconnect valuable non-system removable storage where practical.
4. Open a new Administrator PowerShell session.
5. Capture and review the current inventory:

   ```powershell
   python -m diskwiper.main --inventory-only | Tee-Object native-before.txt
   ```

6. Run the read-only preflight using the number shown by that inventory:

   ```powershell
   python -m diskwiper.main --native-preflight 4
   ```

7. Confirm the preflight reports serial `21A000000419`, size `150038863360`,
   and 512-byte logical and physical sectors.

## Arm this exact target

Set all gates only in the temporary Administrator PowerShell session:

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
$env:DISKWIPER_ENABLE_NATIVE_WIPES = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"
python -m diskwiper.main --enable-real-wipes --real-backend native --native-test-target "21A000000419:150038863360"
```

The application banner must say `EXPERIMENTAL native raw zero overwrite`.
Select only the matching 150 GB disk. The destructive confirmation requires
typing its complete serial number, not four characters.

## During the test

- Do not disconnect or power-cycle the enclosure.
- Do not close DiskWiper while the job is active.
- Observe percentage, confirmed write speed, ETA, and elapsed time.
- Cancellation is cooperative between write chunks. A cancelled disk is
  incomplete and must be wiped again from byte zero.
- Any disconnect, short write, flush error, or verification failure is an error,
  never a successful wipe.

## After completion

1. Require `COMPLETE` in the UI and zero partitions after automatic refresh.
2. Close destructive mode and clear its session gates:

   ```powershell
   Remove-Item Env:DISKWIPER_ENABLE_REAL_WIPES
   Remove-Item Env:DISKWIPER_ENABLE_NATIVE_WIPES
   ```

3. Capture post-test inventory:

   ```powershell
   python -m diskwiper.main --inventory-only | Tee-Object native-after.txt
   ```

4. Confirm the same serial and capacity are present, with no volumes.
5. Preserve `native-before.txt`, `native-after.txt`, the DiskWiper log, elapsed
   time, average throughput, and final history record with the test notes.
6. Power-cycle the enclosure only after all records have been captured, then
   confirm the disk is rediscovered and recognized in wipe history.

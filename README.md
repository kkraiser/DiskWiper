# DiskWiper

DiskWiper is a safety-first Windows 11 utility for inventorying and performing a
full zero overwrite of explicitly selected external HDDs.

The current MVP includes:

- read-only Windows disk inventory;
- fail-closed boot, system, identity, bus, and protected-path checks;
- serial-number confirmation;
- parallel simulated jobs with progress and cancellation;
- SQLite job history and interrupted-job recovery;
- background export of the complete current log without stopping active wipes;
- a guarded, single-job DiskPart `clean all` backend;
- post-operation identity and partition checks.

Empty enclosure slots that Windows reports as zero-byte disk placeholders are
omitted from inventory. Discovery does not assume a fixed enclosure or bay count;
any positive-capacity disk remains visible and is evaluated by the normal safety
policy.

DiskWiper starts in **simulation mode**. Installing or launching it normally cannot
execute DiskPart.

## Development setup

Python 3.12 or newer is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m diskwiper.main
```

To inspect the same read-only inventory and protection decisions without opening
the GUI:

```powershell
python -m diskwiper.main --inventory-only
```

To exercise the native physical-device discovery and geometry checks without
locking, dismounting, or writing, run a read-only preflight for an eligible disk:

```powershell
python -m diskwiper.main --native-preflight 4
```

The disk number is only used to locate the device for this invocation. DiskWiper
checks its full fingerprint before and after opening a `GENERIC_READ` handle and
compares independently queried length and sector geometry. Protected disks fail
before the raw handle is opened. This command cannot be combined with
`--enable-real-wipes`.

Application data is stored under `%LOCALAPPDATA%\DiskWiper` by default. This
includes the SQLite history database and rotating log.

Devices can be permanently protected by creating
`%LOCALAPPDATA%\DiskWiper\protected_devices.json`:

```json
{
  "serial_numbers": ["SERIAL-TO-NEVER-WIPE"],
  "unique_ids": ["WINDOWS-UNIQUE-ID-TO-PROTECT"],
  "stable_keys": []
}
```

Identifiers are compared case-insensitively. A malformed protected-device file
prevents DiskWiper from starting instead of silently dropping its protections.

## Safety model

A disk number is only a current address. Authorization binds the selected disk to
its serial number, Windows unique ID, device path, Plug and Play ID, capacity, and
sector sizes.
The DiskPart worker rediscovers the disk and repeats protection checks immediately
before generating its script. Any missing identity or mismatch aborts the job.

Only disks reported with a `USB` bus type are eligible by default. A temporary,
exact-value environment gate can additionally allow disks reported as `SATA` for
a controlled test; all boot, system, firmware-boot, protected-path, persistent
protection, identity, and geometry checks remain active. All other bus types fail
closed. Simulated history never marks a disk as physically wiped.

## Controlled destructive mode

Do not use destructive mode until simulation, protection tests, and inventory have
been reviewed. Physically disconnect valuable non-system drives before the first
test. Unmounting a filesystem is not equivalent to disconnecting its physical disk.

Destructive mode requires all of the following:

1. An Administrator PowerShell session.
2. The session-only environment gate set to the exact safety value.
3. The explicit command-line flag.
4. A disk that passes every protection check.
5. Confirmation using the selected disk's serial number.
6. Successful identity revalidation immediately before DiskPart starts.

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
python -m diskwiper.main --enable-real-wipes
```

Close that PowerShell session after testing so the environment gate is discarded.
The DiskPart MVP intentionally permits only one real wipe at a time and does not
display a percentage. Parallel physical wipes will use the later native raw-write
backend; parallel simulation is already supported.

## Experimental native backend

The native raw-write backend is available for development but has not yet passed
a controlled physical-disk test. DiskPart remains the default destructive backend.
Selecting native mode requires the normal destructive gate plus a second,
independent experimental gate and an explicit backend selection:

```powershell
$env:DISKWIPER_ENABLE_REAL_WIPES = "I_UNDERSTAND_THIS_DESTROYS_DATA"
$env:DISKWIPER_ENABLE_NATIVE_WIPES = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"
python -m diskwiper.main --enable-real-wipes --real-backend native `
  --native-test-target "SERIAL:SIZE_BYTES"
```

During the controlled test phase, native mode also requires at least one
`--native-test-target SERIAL:SIZE_BYTES`. Repeat the option to arm multiple exact
targets. The backend checks each selected disk against the armed set before and
after volume locking, in addition to its full fingerprint checks. Only the native
backend permits overlapping physical jobs; DiskPart remains single-job.

Omitting either environment gate, the command-line flag, or the native backend
selection starts the application without an enabled native destructive path.
Do not use this mode on a disk containing valuable data. Its first physical test
must use an expendable disk with unrelated storage disconnected.

## Controlled internal SATA test

Internal SATA disks remain protected by default. For a controlled session, set
the additional bus gate before inventory, preflight, and launch:

```powershell
$env:DISKWIPER_ENABLE_INTERNAL_SATA_WIPES = "I_UNDERSTAND_INTERNAL_SATA_WIPES_DESTROY_DATA"
```

This gate only permits the `SATA` bus type to proceed to the normal protection
checks; it does not enable real wipes. Native destructive mode still requires its
two existing gates, `--enable-real-wipes`, Administrator privileges, exact
`SERIAL:SIZE_BYTES` targets, per-disk serial confirmation, and last-second
identity revalidation. See `SATA_TEST.md` for the two-disk procedure.

See `MIXED_TEST.md` for the controlled parallel test covering both internal SATA
and USB-enclosure disks in one native session.

## Important limitation

DiskPart `clean all` writes zeros to the addressable sectors exposed by the drive.
The MVP records this accurately as a zero-overwrite result; it does not claim
certified purge of inaccessible, remapped, or device-internal storage areas.

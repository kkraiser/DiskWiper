# DiskWiper

DiskWiper is a safety-first Windows 11 utility for inventorying and performing a
full zero overwrite of explicitly selected external HDDs.

The current MVP includes:

- read-only Windows disk inventory;
- fail-closed boot, system, identity, bus, and protected-path checks;
- serial-number confirmation;
- parallel simulated jobs with progress and cancellation;
- SQLite job history and interrupted-job recovery;
- a guarded, single-job DiskPart `clean all` backend;
- post-operation identity and partition checks.

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

Only disks reported with a `USB` bus type are eligible in this MVP. All other bus
types fail closed. Simulated history never marks a disk as physically wiped.

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
python -m diskwiper.main --enable-real-wipes --real-backend native
```

Omitting either environment gate, the command-line flag, or the native backend
selection starts the application without an enabled native destructive path.
Do not use this mode on a disk containing valuable data. Its first physical test
must use an expendable disk with unrelated storage disconnected.

## Important limitation

DiskPart `clean all` writes zeros to the addressable sectors exposed by the drive.
The MVP records this accurately as a zero-overwrite result; it does not claim
certified purge of inaccessible, remapped, or device-internal storage areas.

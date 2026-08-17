# DiskWiper

## Project Purpose

**DiskWiper** is a Windows desktop utility for securely erasing multiple spinning hard drives in removable/external enclosures.

The primary use case is processing a collection of retired HDDs through a multi-bay USB enclosure:

1. Insert one or more HDDs.
2. Detect the physical disks.
3. Identify each disk by model, serial number, capacity, bus type, and Windows disk number.
4. Select disks for wiping.
5. Confirm that the selected devices are correct.
6. Securely overwrite the entire addressable HDD with zeros.
7. Track each drive independently.
8. Clearly indicate when a drive has completed successfully.
9. Clearly indicate that device removal is managed by Windows or the enclosure.
10. Replace it with another drive while other bays continue wiping.

The program should prioritize **safety and auditability over convenience**, because an incorrect disk selection can permanently destroy data.

---

# 1. Target Platform

Initial platform:

- Windows 11
- Python 3.12+
- Visual Studio Code
- PowerShell available
- Administrator privileges required for destructive disk operations

Possible later packaging:

- PyInstaller standalone `.exe`
- Windows installer
- Signed executable if the program is eventually distributed

---

# 2. Recommended Technology Stack

## Application

Python.

Reasons:

- Fast to develop.
- Good Windows integration.
- Easy process management.
- Easy JSON logging.
- Suitable for a utility of this size.
- Familiar development environment.

## GUI

Recommended:

**PySide6 / Qt**

Advantages:

- Good table and progress-bar controls.
- Good multi-thread/process support.
- Professional Windows appearance.
- Easier to build a disk-management dashboard than with Tkinter.
- Can later package into a standalone Windows executable.

Dependencies:

```text
PySide6
psutil
pywin32
```

PowerShell and native Windows utilities can initially perform low-level disk operations.

---

# 3. Core Safety Principle

The application must never infer:

> "External disk = safe to erase."

Instead, disks should pass a series of safety checks.

A disk should be considered **protected by default** until the user explicitly selects it.

DiskWiper should automatically block or strongly protect:

- Windows system disk
- Windows boot disk
- Disk containing `C:`
- Any disk containing the running DiskWiper executable
- Any disk containing the current user's profile
- Any disk explicitly placed on a persistent protected-device list

The application should preferably reject wiping these devices entirely rather than merely displaying a warning.

---

# 4. Disk Identification

For every physical disk, collect as much of the following information as Windows exposes:

```text
Windows Disk Number
Model
Manufacturer
Serial Number
Capacity
Bus Type
USB device path
Partition count
Drive letters
Volume labels
Disk status
Online/offline state
Removable/fixed classification
System disk flag
Boot disk flag
Current operation
```

Example:

```text
Disk 4
Bay: Unknown
Model: WDC WD80EFAX-68KNBN0
Serial: 7SG123AB
Capacity: 8.00 TB
Bus: USB
Volumes: E:
Status: Ready
```

The **serial number is especially important** because Windows disk numbers can change when devices are removed and inserted.

Operations should therefore internally track disks using persistent hardware identifiers rather than relying solely upon:

```text
Disk 4
```

---

# 5. Main GUI

The main window should resemble a disk-processing dashboard.

Suggested columns:

| Select | Disk | Status | Model | Serial | Capacity | Interface | Volumes | Progress | Elapsed | Action |
|---|---:|---|---|---|---:|---|---|---:|---|---|

Example:

```text
☑ Disk 3 | WIPING     | WD Red 4TB       | ABC123 | 4 TB  | USB | — | 43%  | 2:13 | Stop
☐ Disk 4 | COMPLETE   | Seagate Exos     | DEF456 | 16 TB | USB | — | 100% | 19:42| Wipe
☐ Disk 5 | READY      | WD Blue 1TB      | GHI789 | 1 TB  | USB | F: | —    | —    | Wipe
☐ Disk 6 | EMPTY BAY? | —                 | —      | —     | —   | — | —    | —    | —
```

Status colors can be used, but status must never depend solely on color.

Recommended status values:

```text
PROTECTED
READY
CONFIRMATION REQUIRED
PREPARING
WIPING
VERIFYING
COMPLETE
EJECTING
REMOVED
CANCELLED
ERROR
DISCONNECTED
```

---

# 6. Disk Refresh Behavior

The application should monitor for hardware changes.

When a disk is inserted:

1. Detect hardware change.
2. Refresh disk inventory.
3. Read identifying information.
4. Run safety checks.
5. Display disk as `READY` or `PROTECTED`.

When a disk disappears:

1. Match disappearance against known device serial/device ID.
2. Mark the disk `REMOVED`.
3. Remove it from the active processing list after a short retention period.

A manual:

```text
Refresh Disks
```

button should also be provided.

---

# 7. Secure Erase Method — HDD

Initial HDD erase implementation:

```text
diskpart
select disk X
clean all
```

The application should generate the DiskPart instruction file itself rather than attempting to emulate DiskPart behavior.

Example temporary script:

```text
select disk 4
clean all
exit
```

Execution:

```powershell
diskpart /s wipe_disk_4.txt
```

However, before execution the program must **revalidate the physical disk identity**.

For example:

```text
Expected:
Disk Number: 4
Serial: ABC123
Capacity: 8 TB

Current:
Disk Number: 4
Serial: ABC123
Capacity: 8 TB
```

Only then should the wipe begin.

This prevents a disk-number reassignment from accidentally causing the wrong disk to be wiped.

---

# 8. Parallel Wiping

Each HDD should operate independently.

Architecture:

```text
GUI Process
    |
    +-- Disk Manager
    |
    +-- Worker: HDD A
    |
    +-- Worker: HDD B
    |
    +-- Worker: HDD C
    |
    +-- Worker: HDD D
```

One disk completing or failing must not affect the others.

The GUI must remain responsive while multiple drives are wiping.

Do not perform erase operations directly on the GUI event thread.

---

# 9. Progress Monitoring

DiskPart's `clean all` command does not provide ideal machine-readable progress reporting.

Therefore implement progress in phases.

## Version 0.1

Status:

```text
WIPING
```

Elapsed time:

```text
04:37:12
```

No fake percentage.

This is preferable to displaying an inaccurate progress estimate.

## Version 0.2

Investigate implementing the zero-fill directly from Python/Windows raw-device APIs.

This would allow:

```text
Bytes Written
Total Bytes
Percentage
Write Throughput
Estimated Remaining Time
```

Example:

```text
8.42 TB / 16.00 TB
52.6%
171 MB/s
ETA 11h 39m
```

A custom raw writer may eventually replace DiskPart once thoroughly tested.

---

# 10. Wipe Confirmation

Starting a wipe should require explicit confirmation.

Suggested confirmation dialog:

```text
SECURE ERASE

You are about to permanently erase:

Disk 4
Seagate Exos X16
Serial: ZL123456
Capacity: 16.0 TB

ALL DATA ON THIS DEVICE WILL BE DESTROYED.

Type the last four characters of the serial number to continue:

[ 3456 ]
```

Buttons:

```text
Cancel
ERASE DISK
```

For batch erase, consider requiring:

```text
ERASE
```

plus displaying all affected serial numbers.

---

# 11. Device Removal

DiskWiper does not issue per-disk ejection requests. Multi-bay bridges may expose
several disks beneath one removable controller and reject or misapply child-device
ejection. After all activity for a bay is complete, the user must follow the
enclosure's hot-swap procedure. Use Windows **Safely Remove Hardware** when
disconnecting the entire enclosure.

---

# 12. Hot-Swap Workflow

The application should be optimized for this loop:

```text
Bay 1 -> COMPLETE -> REMOVE PER ENCLOSURE PROCEDURE -> INSERT NEW HDD -> WIPE
Bay 2 -> WIPING
Bay 3 -> WIPING
Bay 4 -> WIPING
```

The application should not require restarting when disks are exchanged.

---

# 13. Physical Bay Identification

USB enclosures may not expose a reliable concept of:

```text
Bay 1
Bay 2
Bay 3
Bay 4
```

Version 0.1 should therefore not assume the operating system can determine enclosure bay location.

Possible later solution:

Allow the user to assign a temporary label:

```text
Disk 4 -> Bay 1
Disk 5 -> Bay 2
Disk 6 -> Bay 3
Disk 7 -> Bay 4
```

The UI could then display:

```text
BAY 1
BAY 2
BAY 3
BAY 4
```

This mapping can be experimentally tested against the particular USB enclosure.

---

# 14. Completion Verification

After DiskPart exits successfully:

1. Confirm the process return status.
2. Refresh disk metadata.
3. Verify that no normal partitions remain.
4. Record successful completion.

Optional later verification:

Read random sectors from:

```text
beginning
25%
50%
75%
end
```

and confirm they contain zeros.

Full read-back verification should be optional because reading an entire 16 TB drive would approximately double total processing time.

---

# 15. Logging

Maintain two forms of log.

## Application Log

Example:

```text
2026-08-16 14:02:11 DiskWiper started
2026-08-16 14:02:13 Disk 4 detected
2026-08-16 14:02:13 Serial ZL123456
2026-08-16 14:03:02 Wipe authorized
2026-08-16 14:03:03 Wipe started
2026-08-17 09:41:17 Wipe completed
2026-08-17 09:41:20 Verification passed
2026-08-17 09:42:07 Device removed by user
```

## Erase History

Store structured records in JSON or SQLite.

Recommended SQLite eventually.

Fields:

```text
record_id
disk_model
serial_number
capacity_bytes
bus_type
wipe_method
started_at
completed_at
duration_seconds
result
verification_result
application_version
```

This lets the user later answer:

> Did I already wipe this particular disk?

---

# 16. Already-Wiped Detection

When a disk is inserted, compare its serial number with wipe history.

If previously completed:

```text
PREVIOUSLY WIPED
Last wipe: 2026-08-16
Method: Full zero overwrite
```

Do not prevent another wipe, but warn that one has already been recorded.

---

# 17. Power Failure Handling

A power failure during a wipe should result in:

```text
INCOMPLETE / INTERRUPTED
```

rather than assuming the drive was erased.

On next startup, DiskWiper should check its job database for operations that were:

```text
WIPING
```

when the program terminated unexpectedly.

Those should be converted to:

```text
INTERRUPTED
```

The drive must be wiped again from the beginning unless a future implementation supports reliable resume functionality.

---

# 18. UPS Recommendation

For this workflow, putting both the **computer and external enclosure on UPS-backed outlets** is strongly recommended.

The HDD and USB bridge must remain powered during the entire erase.

A momentary power loss to the enclosure could:

- interrupt the zero-fill;
- disconnect the USB bridge;
- leave the job incomplete;
- cause Windows disk enumeration to change;
- potentially cause unexpected behavior across other disks in the enclosure.

DiskWiper itself should assume unexpected disconnects can occur and handle them safely.

---

# 19. Initial Project Structure

```text
DiskWiper/
│
├── README.md
├── requirements.txt
├── pyproject.toml
│
├── diskwiper/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── gui/
│   │   ├── main_window.py
│   │   ├── disk_table.py
│   │   ├── confirm_dialog.py
│   │   └── log_window.py
│   │
│   ├── disks/
│   │   ├── discovery.py
│   │   ├── identity.py
│   │   ├── protection.py
│   │
│   ├── wipe/
│   │   ├── manager.py
│   │   ├── worker.py
│   │   ├── diskpart.py
│   │   └── verify.py
│   │
│   ├── history/
│   │   ├── database.py
│   │   └── models.py
│   │
│   └── util/
│       ├── admin.py
│       ├── logging.py
│       └── powershell.py
│
├── tests/
│   ├── test_disk_identity.py
│   ├── test_protection.py
│   └── test_history.py
│
└── data/
    └── .gitkeep
```

---

# 20. Core Data Model

Example:

```python
@dataclass
class PhysicalDisk:
    disk_number: int
    model: str
    serial_number: str
    capacity_bytes: int
    bus_type: str
    device_id: str

    drive_letters: list[str]

    is_system: bool
    is_boot: bool
    is_protected: bool

    status: DiskStatus
```

Job:

```python
@dataclass
class WipeJob:
    disk: PhysicalDisk

    method: str
    status: WipeStatus

    started_at: datetime | None
    completed_at: datetime | None

    bytes_processed: int | None
    error_message: str | None
```

---

# 21. State Machine

Each disk should follow an explicit state machine.

```text
DETECTED
   |
   v
READY
   |
   v
CONFIRMING
   |
   v
PREPARING
   |
   v
WIPING
   |
   +------> ERROR
   |
   +------> INTERRUPTED
   |
   v
VERIFYING
   |
   +------> ERROR
   |
   v
COMPLETE
   |
   v
EJECTING
   |
   v
SAFE_TO_REMOVE
   |
   v
REMOVED
```

A protected disk instead follows:

```text
DETECTED -> PROTECTED
```

and must never enter the wipe path.

---

# 22. Administrator Privileges

DiskWiper should detect at startup whether it has Administrator rights.

Version 0.1:

```text
DiskWiper requires Administrator privileges to erase physical disks.

[Restart as Administrator]
[Exit]
```

Eventually the GUI could run unelevated and invoke only its disk-management worker with elevated privileges, but that adds complexity and is unnecessary for the initial version.

---

# 23. Development Safety Mode

This is essential.

DiskWiper must initially support:

```text
DEVELOPMENT_MODE = True
```

When enabled:

- disk discovery works;
- GUI works;
- serial-number matching works;
- confirmation works;
- logging works;
- workers run;
- progress simulation works;

but **no physical erase command can execute**.

Instead:

```text
SIMULATION: Would wipe PhysicalDrive4
```

This lets most of the application be developed without risking data.

Actual erase functionality should be enabled only after the disk protection logic has automated tests.

---

# 24. Test Disk

Before using the program on valuable hardware, use an expendable small HDD.

Recommended development progression:

```text
SIMULATION
    ↓
old 500 GB / 1 TB HDD
    ↓
multiple disposable HDDs
    ↓
4-bay parallel test
    ↓
production use
```

Never develop the destructive portions while valuable disks are attached unnecessarily.

---

# 25. MVP — Version 0.1

Version 0.1 should intentionally stay small.

Required:

- Detect physical disks.
- Display disk number.
- Display model.
- Display serial number.
- Display capacity.
- Display bus type.
- Display volumes.
- Identify and block system/boot disk.
- Manual refresh.
- Select HDD.
- Strong confirmation dialog.
- Launch `diskpart clean all`.
- Run several independent wipe workers simultaneously.
- Display current status.
- Display elapsed time.
- Detect success/failure.
- Record completed wipes by serial number.
- Refresh after disk removal/insertion.
- Leave hot-swap and whole-enclosure removal to the user, Windows, and enclosure.

Not required yet:

- Accurate percentage complete.
- ETA.
- SMART health monitoring.
- SSD secure erase.
- ATA Secure Erase.
- NVMe Sanitize.
- Full zero verification.
- Enclosure bay detection.
- Network control.
- Remote monitoring.

---

# 26. Version 0.2

Potential additions:

- Native zero-fill engine.
- Accurate percentage progress.
- MB/s throughput.
- ETA.
- Partial zero verification.
- SMART data.
- Drive temperature.
- Automatically identify HDD versus SSD.
- Optional disk labels such as Bay 1–4.
- User-configurable table column visibility and ordering.
- Windows notifications when a disk finishes.

Example notification:

```text
DiskWiper

Bay 3 completed successfully.

Seagate Exos X16
Serial ZL123456
16 TB

Removal is managed by the enclosure or Windows.
```

---

# 27. Version 0.3

Possible advanced sanitization support:

```text
HDD
    Full overwrite

SATA SSD
    ATA Secure Erase
    ATA Enhanced Secure Erase

NVMe
    NVMe Format
    NVMe Sanitize

Self-encrypting drives
    Cryptographic erase
```

The application should choose methods based upon the device type and capabilities rather than treating all storage devices identically.

---

# 28. Future Feature — Certificate of Erasure

Generate a simple report after each successful wipe:

```text
DISK ERASURE RECORD

Date:
2026-08-17

Model:
Seagate Exos X16

Serial Number:
ZL123456

Capacity:
16 TB

Method:
Full-device zero overwrite

Verification:
Passed

Result:
Successfully erased
```

This could be exported as:

```text
JSON
CSV
PDF
```

Useful even for a personal collection because it creates a permanent inventory of which drives were processed.

---

# 29. Suggested Development Milestones

## Milestone 1 — Safe Disk Inventory

Build:

```text
discovery.py
identity.py
protection.py
```

Goal:

Accurately enumerate disks and positively identify the Windows boot/system drive.

**No erase functionality exists yet.**

## Milestone 2 — Basic GUI

Build the table showing detected disks and device details.

## Milestone 3 — Hot-Plug Detection

Verify that drives can be inserted and removed from the four-drive enclosure while the application is running.

## Milestone 4 — Simulated Jobs

Implement worker threads/processes and simulate four simultaneous wipes.

## Milestone 5 — Confirmation System

Implement serial-number confirmation and last-second identity revalidation.

## Milestone 6 — Real DiskPart Worker

Enable actual wiping only for explicitly selected disks.

Test first using an expendable HDD.

## Milestone 7 — History

Implement SQLite wipe history.

## Milestone 8 — Hot-Swap Guidance

Document user-managed bay removal and whole-enclosure Windows safe removal.

## Milestone 9 — Parallel Production Test

Run four expendable HDDs simultaneously and verify disk replacement while other jobs remain active.

---

# 30. Guiding Design Rule

Every destructive command should satisfy the following rule:

```text
User selected disk
        AND
disk is not protected
        AND
user confirmed hardware identity
        AND
serial number still matches
        AND
capacity still matches
        AND
device path still matches
        AND
disk is still not system/boot disk
        =
erase may proceed
```

If any validation fails:

```text
ABORT
```

Never attempt to guess what the user intended.

---

# 31. Current MVP Handoff — 2026-08-16

## Application status

- DiskPart-based MVP is feature-complete for the current test phase.
- Automated suite: **36 tests passing** on Python 3.12.
- Simulation, parallel simulated jobs, cancellation, persistent history,
  permanent protection, enclosure-position display, read-only speed sampling,
  estimated duration, and 60-second/manual inventory refresh are implemented.
- Per-disk eject was removed. Hot-swap is controlled by the enclosure; use
  Windows safe removal only when disconnecting the entire enclosure.
- A future native Python raw-write backend is planned to provide actual byte
  progress, throughput, ETA, cooperative cancellation, and controlled parallel
  physical wipes while preserving all current safety gates.

## Completed destructive test

One real DiskPart `clean all` test completed successfully on a 150 GB
WD1500ADFD installed in position P2:

```text
Enclosure serial: 21A000000419
Started:          2026-08-16 14:32:27
DiskPart success: 2026-08-16 15:35:47
Elapsed:          approximately 1:03:20
Post-check:       RAW, healthy, zero partitions
Power-cycle:      disk rediscovered and recognized from wipe history
```

This corresponds to roughly 39.5 MB/s and led to investigation of the USB link.

## Test enclosure and identity behavior

Enclosure:

```text
Sabrent DS-SC4B
Advertised link: USB 3.2 Gen 2, up to 10 Gbps
Bay bridges:     ASMedia ASM235CM / VID_174C PID_55AA
```

The enclosure hides the physical disks' model and serial. It exposes bay-based
serials and one shared UniqueId:

```text
P1: 11A000000419
P2: 21A000000419
P3: 31A000000419
P4: 41A000000419
Shared UniqueId: 5000000000000001
```

DiskWiper therefore uses the full fingerprint, including capacity, device path,
PnP identity, and sector geometry. A protected drive moved to another bay may
need to be protected again because the bridge identity follows the bay.

## USB performance investigation

On the current AMD-based Windows 11 PC, all four UAS storage controllers
consistently enumerate beneath:

```text
USB\VID_2109&PID_2822\MSFT20000000001
Bus description: USB2.0 Hub
```

This remained true after:

- using a rear motherboard 10 Gbps USB-C port;
- substituting a known USB 3.1 Gen 2-rated cable;
- fully removing enclosure AC and USB power;
- using a rear motherboard 10 Gbps USB-A port with USB-A-to-USB-C;
- moving between two distinct motherboard USB controller paths.

All four bays use UAS, but their immediate parent remains the VIA Labs USB 2.0
hub. The observed ~39.5 MB/s wipe throughput is consistent with USB 2.0. Other
ASMedia SuperSpeed hubs visible on the PC were traced to unrelated controller
paths, not this enclosure.

## USB performance resolution

A cable explicitly labelled `USB 3.2 10Gbps` resolved the USB 2.0 fallback on
the AMD PC. All four bays now enumerate over UAS beneath:

```text
USB\VID_2109&PID_0822\MSFT30000000001
Friendly name:   Generic SuperSpeed USB Hub
Bus description: USB3.1 Hub
Parent:          USB Root Hub (USB 3.0)
Controller:      AMD USB 3.10 eXtensible Host Controller
```

DiskWiper's read-only benchmark also reports substantially higher throughput.
The earlier `PID_2822` / `USB2.0 Hub` path and approximately 39.5 MB/s ceiling
were therefore caused by the USB connection falling back to USB 2.0. Testing
on the Intel PC is no longer required to isolate this issue.

## Backlog: drive temperature and SMART diagnostics

Explore an optional per-disk `Temperature` column without making SMART support
a requirement for inventory or wiping. The feature must run asynchronously,
display an unavailable value when a bridge does not expose telemetry, and avoid
diagnostic polling while a disk has an active wipe job.

Evidence from the current Sabrent DS-SC4B / ASM235CM enclosure:

- Windows `Get-PhysicalDisk` returns no temperature for any of the four bays.
- `Get-StorageReliabilityCounter` cannot retrieve a CIM reliability resource
  for any bay.
- smartmontools 7.5 `smartctl --scan-open` identifies disks 3 through 6 as SAT
  candidates but fails to open them with Windows error 5.
- `smartctl -a -d sat \\.\PhysicalDrive3` fails with `Invalid argument`.

Future options to investigate:

1. Test other documented smartctl device types or permissions only when doing
   so is read-only and the disk identity can be revalidated.
2. Determine whether HWiNFO can read temperatures through this bridge and, if
   so, whether its shared-memory sensor interface can be consumed safely as an
   optional integration while HWiNFO is running.
3. Keep the UI provider-neutral: Windows reliability counters, smartctl, or an
   external sensor provider may supply a temperature, otherwise show `—`.

Do not add HWiNFO or smartmontools as a mandatory runtime dependency.

---

# Project Working Name

**DiskWiper**

Alternative names:

- DriveScrub
- ZeroBay
- DiskSanitizer
- WipeStation
- DriveWipe

`DiskWiper` is probably the clearest development name.

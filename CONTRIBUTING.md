# Contributing

Thanks for helping improve DiskWiper. Changes to discovery, protection policy,
authorization, locking, raw I/O, and completion verification are safety-critical
and need focused tests and a clear explanation of the failure mode they address.

## Before opening a pull request

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

Keep physical-disk tests out of automated tests. Use synthetic fixtures and fakes
for unit tests. Never commit real serial numbers, device paths, logs, inventory
captures, screenshots, database files, or other machine-specific data.

For behavior changes, update the README or the relevant test procedure. Pull
requests should explain whether they affect simulation, DiskPart, native raw I/O,
or protection decisions.
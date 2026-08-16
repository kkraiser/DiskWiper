from __future__ import annotations

import subprocess

from diskwiper.disks.discovery import PowerShellDiskDiscovery


def test_discovery_hides_powershell_window_on_windows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, b'{"Disks":[]}', b"")

    monkeypatch.setattr("diskwiper.disks.discovery.subprocess.run", fake_run)

    inventory = PowerShellDiskDiscovery().discover()

    assert inventory.disks == ()
    assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW

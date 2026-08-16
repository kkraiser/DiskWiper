from dataclasses import replace

from tests.factories import make_disk


def test_fingerprint_ignores_identifier_case_and_outer_whitespace() -> None:
    first = make_disk().fingerprint
    second = replace(
        first,
        serial_number="  serial1234 ",
        unique_id="usb-unique-serial1234",
        device_path=r"\\?\USBSTOR#DISK&VEN_EXAMPLE#SERIAL1234",
        pnp_device_id=r"usbstor\disk&ven_example\serial1234",
    )

    assert first.matches(second)


def test_fingerprint_detects_capacity_change() -> None:
    first = make_disk().fingerprint
    second = replace(first, size_bytes=first.size_bytes + 512)

    assert not first.matches(second)


def test_disk_number_is_not_part_of_stable_identity() -> None:
    first = make_disk(disk_number=4)
    second = make_disk(disk_number=9)

    assert first.fingerprint.matches(second.fingerprint)


def test_usb_enclosure_position_comes_from_windows_function_number() -> None:
    disk = make_disk(
        location="Integrated : Bus 0 : Device 0 : Function 3 : Adapter 5 : Port 0"
    )

    assert disk.enclosure_position == "P3"


def test_enclosure_position_is_hidden_for_internal_disks() -> None:
    disk = make_disk(bus_type="SATA", location="Integrated : Function 1")

    assert disk.enclosure_position is None


def test_enclosure_position_is_unknown_without_function_metadata() -> None:
    assert make_disk().enclosure_position is None

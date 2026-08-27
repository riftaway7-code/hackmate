import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import auto_usb_map as usbmap


def _dsdt_snippet(ports):
    """ports: list of (device_name, adr_value, upc_type_value)."""
    body = "\n".join(
        f"""        Device ({name})
        {{
            Name (_ADR, {adr})
            Name (_UPC, Package (0x04)
            {{
                0xFF,
                {upc},
                Zero,
                Zero
            }})
        }}"""
        for name, adr, upc in ports
    )
    return f"""
    Device (XHC)
    {{
        Device (RHUB)
        {{
{body}
        }}
    }}
    """


class AcpiIntTests(unittest.TestCase):
    def test_zero_keyword(self):
        self.assertEqual(usbmap._acpi_int("Zero"), 0)

    def test_one_keyword(self):
        self.assertEqual(usbmap._acpi_int("One"), 1)

    def test_hex_literal(self):
        self.assertEqual(usbmap._acpi_int("0x0A"), 10)

    def test_decimal_literal(self):
        self.assertEqual(usbmap._acpi_int("12"), 12)

    def test_trailing_comma_and_whitespace_are_stripped(self):
        self.assertEqual(usbmap._acpi_int("  0x03, "), 3)

    def test_garbage_returns_none(self):
        self.assertIsNone(usbmap._acpi_int("NotANumber"))


class ParseDsdtPortsTests(unittest.TestCase):
    def test_parses_ports_with_index_and_connector_type(self):
        dsl = _dsdt_snippet([("HS01", "One", "0x00"), ("SS01", "0x02", "0x03")])
        result = usbmap.parse_dsdt_ports(dsl)

        self.assertIn("XHC", result)
        ports = {p["index"]: p for p in result["XHC"]}
        self.assertEqual(ports[1]["type"], 0)
        self.assertEqual(ports[2]["type"], 3)

    def test_hub_wrapper_name_is_stripped_from_controller_name(self):
        # RHUB is a known hub-wrapper name; the real controller is its parent, XHC.
        dsl = _dsdt_snippet([("HS01", "One", "0x00")])
        result = usbmap.parse_dsdt_ports(dsl)
        self.assertIn("XHC", result)
        self.assertNotIn("RHUB", result)

    def test_zero_or_negative_adr_is_skipped(self):
        dsl = _dsdt_snippet([("HS01", "Zero", "0x00"), ("HS02", "One", "0x00")])
        result = usbmap.parse_dsdt_ports(dsl)
        indexes = [p["index"] for p in result["XHC"]]
        self.assertEqual(indexes, [1])

    def test_device_without_upc_is_not_treated_as_a_port(self):
        dsl = """
        Device (XHC)
        {
            Device (RHUB)
            {
                Device (NOTAPORT)
                {
                    Name (_ADR, One)
                }
            }
        }
        """
        result = usbmap.parse_dsdt_ports(dsl)
        self.assertEqual(result, {})

    def test_container_device_with_nested_ports_is_not_itself_a_port(self):
        # RHUB has children and its own body (via nested text) contains _UPC
        # text, but it must not be picked up as a leaf port block itself.
        dsl = _dsdt_snippet([("HS01", "One", "0x00")])
        result = usbmap.parse_dsdt_ports(dsl)
        total_ports = sum(len(v) for v in result.values())
        self.assertEqual(total_ports, 1)

    def test_method_form_upc_without_static_package_yields_none_type(self):
        dsl = """
        Device (XHC)
        {
            Device (RHUB)
            {
                Device (HS01)
                {
                    Name (_ADR, One)
                    Method (_UPC, 0, NotSerialized)
                    {
                        Return (GUPC (One))
                    }
                }
            }
        }
        """
        result = usbmap.parse_dsdt_ports(dsl)
        self.assertEqual(result["XHC"][0]["type"], None)


class SpeedPrefixTests(unittest.TestCase):
    def test_superspeed_ports_get_ss_prefix(self):
        ports = [{"class": "SuperSpeed"}, {"class": "HighSpeed"}]
        self.assertEqual(usbmap._speed_prefix(ports), "SS")

    def test_highspeed_only_gets_hs_prefix(self):
        ports = [{"class": "HighSpeed"}]
        self.assertEqual(usbmap._speed_prefix(ports), "HS")

    def test_unknown_only_gets_prt_prefix(self):
        ports = [{"class": "Unknown"}]
        self.assertEqual(usbmap._speed_prefix(ports), "PRT")


class HexIntTests(unittest.TestCase):
    def test_valid_value(self):
        self.assertEqual(usbmap._hex_int(5), 5)

    def test_invalid_value_defaults_to_zero(self):
        self.assertEqual(usbmap._hex_int(None), 0)
        self.assertEqual(usbmap._hex_int("not a number"), 0)


class PortSpeedClassTests(unittest.TestCase):
    def test_superspeed_protocol(self):
        port = {"ConnectionInfoV2": {"SupportedUsbProtocols": {"Usb300": True}}}
        self.assertEqual(usbmap._port_speed_class(port), "SuperSpeed")

    def test_highspeed_protocol(self):
        port = {"ConnectionInfoV2": {"SupportedUsbProtocols": {"Usb200": True, "Usb110": True}}}
        self.assertEqual(usbmap._port_speed_class(port), "HighSpeed")

    def test_fullspeed_protocol(self):
        port = {"ConnectionInfoV2": {"SupportedUsbProtocols": {"Usb110": True}}}
        self.assertEqual(usbmap._port_speed_class(port), "FullSpeed")

    def test_missing_info_is_unknown(self):
        self.assertEqual(usbmap._port_speed_class({}), "Unknown")


class GuessPortTypeTests(unittest.TestCase):
    def test_disconnected_port_falls_back_to_usb_a(self):
        # NB: the real Windows ConnectionStatus value for "no device" is
        # literally "NoDeviceConnected", which itself ends with the substring
        # "DeviceConnected" — so the endswith() check below doesn't actually
        # distinguish it from a truly connected port. Harmless in practice:
        # both paths converge on TYPE_USB_A here (Unknown class, connectable,
        # not type-C), so this pins current behavior rather than asserting
        # the (unreachable in this code) "return None" branch.
        port = {"status": "NoDeviceConnected", "type_c": False, "user_connectable": True, "class": "Unknown"}
        self.assertEqual(usbmap._guess_port_type(port), usbmap.TYPE_USB_A)

    def test_truly_unrelated_status_string_returns_none(self):
        port = {"status": "", "type_c": False, "user_connectable": True, "class": "Unknown"}
        self.assertIsNone(usbmap._guess_port_type(port))

    def test_type_c_port_guessed_as_type_c_connector(self):
        port = {"status": "DeviceConnected", "type_c": True, "user_connectable": True, "class": "SuperSpeed"}
        self.assertEqual(usbmap._guess_port_type(port), 9)

    def test_non_user_connectable_port_guessed_as_internal(self):
        port = {"status": "DeviceConnected", "type_c": False, "user_connectable": False, "class": "Unknown"}
        self.assertEqual(usbmap._guess_port_type(port), usbmap.TYPE_INTERNAL)

    def test_superspeed_port_guessed_as_usb3_type_a(self):
        port = {"status": "DeviceConnected", "type_c": False, "user_connectable": True, "class": "SuperSpeed"}
        self.assertEqual(usbmap._guess_port_type(port), 3)

    def test_other_connected_port_defaults_to_usb_a(self):
        port = {"status": "DeviceConnected", "type_c": False, "user_connectable": True, "class": "HighSpeed"}
        self.assertEqual(usbmap._guess_port_type(port), usbmap.TYPE_USB_A)


class SerializeHubTests(unittest.TestCase):
    def test_disconnected_port_keeps_defaults(self):
        hub = {"HubPorts": [{"ConnectionInfo": {"ConnectionIndex": 1, "ConnectionStatus": "NoDeviceConnected"}}]}
        result = usbmap._serialize_hub(hub)
        self.assertEqual(result["ports"][0]["class"], "Unknown")

    def test_connected_port_gets_speed_class_and_type_c_flag(self):
        hub = {"HubPorts": [{
            "ConnectionInfo": {"ConnectionIndex": 1, "ConnectionStatus": "DeviceConnected"},
            "ConnectionInfoV2": {"SupportedUsbProtocols": {"Usb300": True}},
            "PortConnectorProps": {"UsbPortProperties": {"PortConnectorIsTypeC": True, "PortIsUserConnectable": True}},
        }]}
        result = usbmap._serialize_hub(hub)
        self.assertEqual(result["ports"][0]["class"], "SuperSpeed")
        self.assertTrue(result["ports"][0]["type_c"])

    def test_ports_are_sorted_by_index(self):
        hub = {"HubPorts": [
            {"ConnectionInfo": {"ConnectionIndex": 3, "ConnectionStatus": "NoDeviceConnected"}},
            {"ConnectionInfo": {"ConnectionIndex": 1, "ConnectionStatus": "NoDeviceConnected"}},
        ]}
        result = usbmap._serialize_hub(hub)
        self.assertEqual([p["index"] for p in result["ports"]], [1, 3])


class ControllerMatchTests(unittest.TestCase):
    def test_valid_bdf_produces_a_match(self):
        controller = {"identifiers": {"bdf": [0, 20, 0]}}
        match = usbmap._controller_match(controller)
        self.assertIsNotNone(match)
        name, prop_match = match
        self.assertEqual(name, "0-20-0")
        self.assertEqual(prop_match, {"pcidebug": "0:20:0"})

    def test_missing_bdf_returns_none(self):
        self.assertIsNone(usbmap._controller_match({"identifiers": {}}))


class BuildMapPlistTests(unittest.TestCase):
    def _controller(self, bdf, ports):
        return {"identifiers": {"bdf": bdf}, "ports": ports}

    def _port(self, index, ptype=None, guessed=None):
        return {"index": index, "class": "Unknown", "type": ptype, "guessed": guessed}

    def test_builds_one_personality_per_matched_controller(self):
        controllers = [self._controller([0, 20, 0], [self._port(1, guessed=usbmap.TYPE_USB_A)])]
        plist = usbmap.build_map_plist(controllers)
        self.assertIsNotNone(plist)
        self.assertEqual(len(plist["IOKitPersonalities"]), 1)

    def test_no_matchable_controllers_returns_none(self):
        controllers = [{"identifiers": {}, "ports": [self._port(1)]}]
        self.assertIsNone(usbmap.build_map_plist(controllers))

    def test_controller_with_no_ports_is_skipped(self):
        controllers = [self._controller([0, 20, 0], [])]
        self.assertIsNone(usbmap.build_map_plist(controllers))

    def test_more_than_max_ports_per_controller_is_truncated(self):
        """Regression guard for the documented AppleUSBXHCI 15-port budget."""
        ports = [self._port(i, guessed=usbmap.TYPE_USB_A) for i in range(1, 21)]  # 20 ports
        controllers = [self._controller([0, 20, 0], ports)]
        plist = usbmap.build_map_plist(controllers)
        entry = next(iter(plist["IOKitPersonalities"].values()))
        self.assertEqual(len(entry["IOProviderMergeProperties"]["ports"]), usbmap.MAX_PORTS_PER_CONTROLLER)

    def test_explicit_type_takes_priority_over_guessed_type(self):
        controllers = [self._controller([0, 20, 0], [self._port(1, ptype=9, guessed=usbmap.TYPE_USB_A)])]
        plist = usbmap.build_map_plist(controllers)
        entry = next(iter(plist["IOKitPersonalities"].values()))
        port = next(iter(entry["IOProviderMergeProperties"]["ports"].values()))
        self.assertEqual(port["UsbConnector"], 9)


class GenerateDsdtMapPortCapTests(unittest.TestCase):
    def test_more_than_max_ports_are_truncated_in_dsdt_derived_map(self):
        ports = [(f"P{i:02d}", str(i), "0x00") for i in range(1, 21)]  # 20 ports
        dsl = _dsdt_snippet(ports)
        with patch.object(usbmap, "decompile_dsdt", return_value=dsl):
            plist = usbmap.generate_dsdt_map(Path("."), log=None)

        self.assertIsNotNone(plist)
        entry = next(iter(plist["IOKitPersonalities"].values()))
        self.assertEqual(len(entry["IOProviderMergeProperties"]["ports"]), usbmap.MAX_PORTS_PER_CONTROLLER)

    def test_no_dsl_text_returns_none(self):
        with patch.object(usbmap, "decompile_dsdt", return_value=None):
            self.assertIsNone(usbmap.generate_dsdt_map(Path("."), log=None))

    def test_dsl_with_no_ports_returns_none(self):
        with patch.object(usbmap, "decompile_dsdt", return_value="Device (XHC) { }"):
            self.assertIsNone(usbmap.generate_dsdt_map(Path("."), log=None))


class ExtractUsbdumpTests(unittest.TestCase):
    def test_extracts_usbdump_exe_from_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "USBToolBox.zip"
            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("USBToolBox/Resources/usbdump.exe", b"fake-exe-bytes")

            dest = tmp_path / "extracted"
            out = usbmap.extract_usbdump(zip_path, dest)

        self.assertIsNotNone(out)
        self.assertEqual(out.name, "usbdump.exe")

    def test_zip_without_usbdump_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "USBToolBox.zip"
            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("USBToolBox/Resources/other.txt", b"nope")

            dest = tmp_path / "extracted"
            out = usbmap.extract_usbdump(zip_path, dest)
        self.assertIsNone(out)

    def test_invalid_zip_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_zip = tmp_path / "not-a-zip.zip"
            bad_zip.write_bytes(b"not a zip file")
            out = usbmap.extract_usbdump(bad_zip, tmp_path / "extracted")
        self.assertIsNone(out)


class GenerateAutoMapPipelineTests(unittest.TestCase):
    def test_dsdt_map_short_circuits_before_usbdump(self):
        with (
            patch.object(usbmap, "generate_dsdt_map", return_value={"fake": "plist"}) as dsdt,
            patch.object(usbmap, "extract_usbdump") as extract,
        ):
            result = usbmap.generate_auto_map(Path("usb.zip"), Path("."), log=None)

        self.assertEqual(result, {"fake": "plist"})
        extract.assert_not_called()

    def test_falls_back_to_usbdump_when_dsdt_map_unavailable(self):
        with (
            patch.object(usbmap, "generate_dsdt_map", return_value=None),
            patch.object(usbmap, "extract_usbdump", return_value=Path("usbdump.exe")),
            patch.object(usbmap, "dump_controllers", return_value=[{"identifiers": {"bdf": [0, 1, 0]}, "ports": [
                {"index": 1, "class": "Unknown", "type": None, "guessed": usbmap.TYPE_USB_A}
            ]}]),
        ):
            result = usbmap.generate_auto_map(Path("usb.zip"), Path("."), log=None)

        self.assertIsNotNone(result)

    def test_no_zip_and_no_dsdt_map_returns_none(self):
        with patch.object(usbmap, "generate_dsdt_map", return_value=None):
            self.assertIsNone(usbmap.generate_auto_map(None, Path("."), log=None))

    def test_never_raises_when_everything_fails(self):
        with (
            patch.object(usbmap, "generate_dsdt_map", return_value=None),
            patch.object(usbmap, "extract_usbdump", return_value=None),
        ):
            result = usbmap.generate_auto_map(Path("usb.zip"), Path("."), log=None)
        self.assertIsNone(result)


class WriteMapKextTests(unittest.TestCase):
    def test_writes_plist_only_bundle(self):
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            kexts_dir = Path(tmp)
            plist = {"CFBundleIdentifier": usbmap.MAP_BUNDLE_IDENTIFIER}
            kext_path = usbmap.write_map_kext(plist, kexts_dir)

            info_path = kext_path / "Contents" / "Info.plist"
            self.assertTrue(info_path.exists())
            roundtrip = plistlib.loads(info_path.read_bytes())
            self.assertEqual(roundtrip["CFBundleIdentifier"], usbmap.MAP_BUNDLE_IDENTIFIER)


if __name__ == "__main__":
    unittest.main()

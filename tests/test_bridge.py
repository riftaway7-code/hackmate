import dataclasses
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge


@dataclasses.dataclass
class _Sample:
    name: str
    data: bytes
    nested: list


class ToJsonableTests(unittest.TestCase):
    def test_dataclass_is_converted_to_dict(self):
        obj = _Sample(name="x", data=b"\x01\x02", nested=[])
        result = bridge._to_jsonable(obj)
        self.assertEqual(result["name"], "x")
        self.assertEqual(result["data"], "0102")

    def test_path_is_converted_to_string(self):
        self.assertEqual(bridge._to_jsonable(Path("/a/b")), str(Path("/a/b")))

    def test_bytes_are_hex_encoded(self):
        self.assertEqual(bridge._to_jsonable(b"\xde\xad"), "dead")

    def test_list_and_tuple_are_recursed_into(self):
        self.assertEqual(bridge._to_jsonable([Path("/a"), b"\x01"]), [str(Path("/a")), "01"])
        self.assertEqual(bridge._to_jsonable((1, 2)), [1, 2])

    def test_dict_is_recursed_into(self):
        self.assertEqual(bridge._to_jsonable({"k": b"\x01"}), {"k": "01"})

    def test_plain_values_pass_through_unchanged(self):
        self.assertEqual(bridge._to_jsonable(42), 42)
        self.assertEqual(bridge._to_jsonable("hi"), "hi")
        self.assertIsNone(bridge._to_jsonable(None))


class WriteLineTests(unittest.TestCase):
    def test_writes_one_json_line_to_stdout(self):
        buf = io.StringIO()
        with patch.object(bridge.sys, "stdout", buf):
            bridge._write_line({"id": 1, "result": "ok"})
        line = buf.getvalue()
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(json.loads(line), {"id": 1, "result": "ok"})

    def test_unserializable_object_falls_back_to_error_log_line(self):
        buf = io.StringIO()
        with patch.object(bridge.sys, "stdout", buf):
            bridge._write_line({"id": 5, "result": object()})
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["method"], "log")
        self.assertEqual(parsed["request_id"], 5)
        self.assertEqual(parsed["data"]["level"], "error")


class HandleDispatchTests(unittest.TestCase):
    def test_unknown_method_returns_error(self):
        response = bridge._handle({"id": 1, "method": "does.not.exist", "params": {}})
        self.assertEqual(response["id"], 1)
        self.assertIn("unknown method", response["error"])

    def test_known_method_returns_result(self):
        response = bridge._handle({"id": 2, "method": "system.ping", "params": {}})
        self.assertEqual(response["id"], 2)
        self.assertTrue(response["result"]["ok"])
        self.assertNotIn("error", response)

    def test_handler_exception_is_converted_to_error_response(self):
        def boom(params, emit):
            raise RuntimeError("kaboom")

        with patch.dict(bridge.METHODS, {"test.boom": boom}):
            response = bridge._handle({"id": 3, "method": "test.boom", "params": {}})
        self.assertEqual(response["id"], 3)
        self.assertEqual(response["error"], "kaboom")

    def test_emit_callback_writes_a_notification_with_request_id(self):
        captured = []

        def notifier(params, emit):
            emit("progress", {"message": "halfway"})
            return {"ok": True}

        with (
            patch.dict(bridge.METHODS, {"test.notify": notifier}),
            patch.object(bridge, "_write_line", side_effect=lambda obj: captured.append(obj)),
        ):
            bridge._handle({"id": 7, "method": "test.notify", "params": {}})

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["request_id"], 7)
        self.assertEqual(captured[0]["method"], "progress")
        self.assertEqual(captured[0]["data"], {"message": "halfway"})


class ConfigSessionTests(unittest.TestCase):
    def tearDown(self):
        bridge._config_sessions.clear()

    def test_missing_session_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            bridge._get_config_session({"session_id": "does-not-exist"})

    def test_existing_session_is_returned(self):
        bridge._config_sessions["abc"] = {"cfg": {"A": 1}, "path": Path("x")}
        session = bridge._get_config_session({"session_id": "abc"})
        self.assertEqual(session["cfg"], {"A": 1})

    def test_get_raw_value_reads_from_session_config(self):
        bridge._config_sessions["s1"] = {"cfg": {"Misc": {"Security": {"SecureBootModel": "Default"}}}, "path": Path("x")}
        result = bridge._config_editor_get_raw_value({"session_id": "s1", "path": "Misc.Security.SecureBootModel"}, emit=None)
        self.assertEqual(result, {"type": "string", "value": "Default"})

    def test_get_raw_value_missing_key_raises_runtime_error(self):
        bridge._config_sessions["s1"] = {"cfg": {}, "path": Path("x")}
        with self.assertRaises(RuntimeError):
            bridge._config_editor_get_raw_value({"session_id": "s1", "path": "Nope.Missing"}, emit=None)

    def test_set_raw_value_coerces_and_writes_into_session_config(self):
        cfg = {"Misc": {"Boot": {"Timeout": 5}}}
        bridge._config_sessions["s1"] = {"cfg": cfg, "path": Path("x")}
        bridge._config_editor_set_raw_value(
            {"session_id": "s1", "path": "Misc.Boot.Timeout", "value": "10", "type": "int"}, emit=None
        )
        self.assertEqual(cfg["Misc"]["Boot"]["Timeout"], 10)

    def test_close_removes_the_session(self):
        bridge._config_sessions["s1"] = {"cfg": {}, "path": Path("x")}
        bridge._config_editor_close({"session_id": "s1"}, emit=None)
        self.assertNotIn("s1", bridge._config_sessions)


class RestoreRunGuardTests(unittest.TestCase):
    def test_wrong_confirm_phrase_is_rejected(self):
        with self.assertRaises(ValueError):
            bridge._restore_run(
                {"device": "/dev/sdb", "backup_filename": "x.zip", "confirm_phrase": "nope"},
                emit=lambda *a: None,
            )

    def test_disconnected_device_is_rejected(self):
        with patch.object(bridge.compat, "get_usb_drives", return_value=[]):
            with self.assertRaises(RuntimeError):
                bridge._restore_run(
                    {"device": "/dev/sdb", "backup_filename": "x.zip", "confirm_phrase": "RESTORE /dev/sdb"},
                    emit=lambda *a: None,
                )

    def test_missing_backup_file_is_rejected(self):
        with (
            patch.object(bridge.compat, "get_usb_drives", return_value=[("/dev/sdb", "16 GB", "USB")]),
            patch.object(bridge, "BACKUPS_DIR") as backups_dir,
        ):
            backups_dir.exists.return_value = False
            with self.assertRaises(RuntimeError):
                bridge._restore_run(
                    {"device": "/dev/sdb", "backup_filename": "nope.zip", "confirm_phrase": "RESTORE /dev/sdb"},
                    emit=lambda *a: None,
                )


class UsbMappingApplyGuardTests(unittest.TestCase):
    def test_missing_kext_path_is_rejected(self):
        with self.assertRaises(RuntimeError):
            bridge._usb_mapping_apply(
                {"device": "/dev/sdb", "utbmap_kext_path": "/nonexistent/UTBMap.kext"},
                emit=lambda *a: None,
            )

    def test_wrong_kext_name_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "NotAMap.kext"
            wrong.mkdir()
            with self.assertRaises(RuntimeError):
                bridge._usb_mapping_apply(
                    {"device": "/dev/sdb", "utbmap_kext_path": str(wrong)},
                    emit=lambda *a: None,
                )

    def test_disconnected_device_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            kext = Path(tmp) / "UTBMap.kext"
            kext.mkdir()
            with patch.object(bridge.compat, "get_usb_drives", return_value=[]):
                with self.assertRaises(RuntimeError):
                    bridge._usb_mapping_apply(
                        {"device": "/dev/sdb", "utbmap_kext_path": str(kext)},
                        emit=lambda *a: None,
                    )


class HardwareHandlerTests(unittest.TestCase):
    def test_warnings_handler_filters_unknown_profile_keys(self):
        params = {"profile": {"platform": "laptop", "totally_made_up_field": 1}}
        result = bridge._hardware_warnings(params, emit=None)
        self.assertIn("warnings", result)
        self.assertIsInstance(result["warnings"], list)

    def test_needs_dgpu_prompt_handler(self):
        params = {"profile": {"platform": "laptop", "dgpu_vendor": "nvidia"}}
        result = bridge._hardware_needs_dgpu_prompt(params, emit=None)
        self.assertTrue(result["needed"])


if __name__ == "__main__":
    unittest.main()

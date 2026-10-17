"""Synthetic no-auth SMB3.0.2 wire-format checks; no network or NAS."""
import ast
import importlib.util
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/probe_synology_smb3_negotiate_wire.py")
spec = importlib.util.spec_from_file_location("smb3_wire", SOURCE)
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


def response_header(status=0):
    return struct.pack(
        "<4sHHIHHIIQIIQ16s",
        b"\xfeSMB", 64, 1, status, 0, 1, 1, 0, 0, 0, 0, 0,
        b"\0" * 16,
    )


def response_body(dialect=0x0302, size=65):
    return struct.pack("<HHH", size, 1, dialect)


class SMB3WireNegotiateTests(unittest.TestCase):
    def test_wire_packet_is_exact_smb2_negotiate_0302_only(self):
        raw = wire.make_negotiate()
        self.assertEqual(len(raw), 106)
        self.assertEqual(struct.unpack(">I", raw[:4])[0], 102)
        self.assertEqual(raw[4:8], b"\xfeSMB")
        self.assertEqual(struct.unpack_from("<H", raw, 8)[0], 64)
        self.assertEqual(struct.unpack_from("<H", raw, 4 + 12)[0], 0)
        self.assertEqual(struct.unpack_from("<H", raw, 4 + 64)[0], 36)
        self.assertEqual(struct.unpack_from("<H", raw, 4 + 66)[0], 1)
        self.assertEqual(struct.unpack_from("<H", raw, 4 + 68)[0], 1)
        self.assertEqual(struct.unpack_from("<H", raw, 4 + 100)[0], 0x0302)
        self.assertNotIn(b"\xffSMB", raw)

    def test_valid_response_means_only_smb302_negotiate(self):
        frame = struct.pack(">I", 128)
        got = wire.parse_response(frame, response_header(), response_body())
        self.assertEqual(got, "SMB3_02_NEGOTIATED")

    def test_server_error_exposes_only_numeric_ntstatus(self):
        frame = struct.pack(">I", 128)
        got = wire.parse_response(
            frame, response_header(0xC00000BB), b"\0" * 6)
        self.assertEqual(got, "SMB2_ERROR_STATUS_0xC00000BB")

    def test_invalid_response_protocol_dialect_or_framing_fails(self):
        frame = struct.pack(">I", 128)
        bad = (
            (b"\x81\0\0\x80", response_header(), response_body()),
            (b"\0\0\0\x10", response_header(), response_body()),
            (frame, b"\xffSMB" + response_header()[4:], response_body()),
            (frame, response_header(), response_body(dialect=0x0311)),
            (frame, response_header(), response_body(size=64)),
            (frame, response_header()[:-1], response_body()),
            (frame, response_header(), response_body()[:-1]),
        )
        for malformed in bad:
            with self.subTest(malformed=malformed[0][:4]):
                with self.assertRaises(RuntimeError):
                    wire.parse_response(*malformed)

    def test_targets_only_internal_ipv4_and_exact_ports(self):
        for ip, port in (
            ("127.0.0.1", 1445),
            ("127.0.0.1", 445),
            ("192.168.6.11", 445),
            ("192.168.2.145", 445),
        ):
            with self.subTest(ip=ip):
                with patch.object(wire.socket, "create_connection",
                                  side_effect=ConnectionRefusedError):
                    self.assertEqual(wire.probe_one(ip, port), "TCP_REFUSED")
        for ip, port in (
            ("192.168.6.11", 1445),
            ("8.8.8.8", 445),
            ("::1", 445),
            ("127.0.0.1", 443),
        ):
            with self.subTest(ip=ip, port=port):
                with self.assertRaises(RuntimeError):
                    wire.probe_one(ip, port)

    def test_timeout_reset_and_closed_have_distinct_safe_markers(self):
        for exc, expected in (
            (ConnectionRefusedError(), "TCP_REFUSED"),
            (ConnectionResetError(), "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE"),
            (TimeoutError(), "NEGOTIATE_TIMEOUT"),
            (OSError("private user secret"), "TRANSPORT_ERROR"),
        ):
            with self.subTest(expected=expected):
                with patch.object(wire.socket, "create_connection",
                                  side_effect=exc):
                    self.assertEqual(
                        wire.probe_one("127.0.0.1", 445), expected)

    def test_no_smb_session_password_or_writes(self):
        source = SOURCE.read_text()
        ast.parse(source, filename=str(SOURCE))
        self.assertIn("NO_SMB_AUTHENTICATION_ATTEMPTED", source)
        self.assertIn("NO_MUTATING_SMB_REQUESTS_SENT", source)
        for forbidden in (
            "getpass", "Session(", "TreeConnect(", "FILE_DELETE_ON_CLOSE",
            "os.rename(", "os.unlink(", "open(", "os.chmod(", "FILE_CREATE",
            "os.mkdir(", "SMB1_NEGOTIATE",
        ):
            # Python's ordinary socket context and source reading are fine,
            # but no file open/writes should be used by the probe.
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

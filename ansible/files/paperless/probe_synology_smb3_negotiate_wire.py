#!/usr/bin/env python3
"""Credential-free and non-mutating SMB3.0.2 NEGOTIATE wire diagnostic.

A minimal SMB2 NEGOTIATE request for precisely SMB 3.0.2 is sent on TCP/445
to the loopback and actual ethN addresses on the NAS (default). An optional
--controller-forward targets only 127.0.0.1:1445 via a separate existing
temporary SSH tunnel. There is no SMB session setup, share, login, read,
write, delete, SMB1 fallback, or filesystem mutation. No raw server output,
log content, addresses learned from arbitrary interface names or credentials.
The single dialect result does not assert that all SMB3 versions work.
"""
import argparse
import fcntl
import ipaddress
import re
import socket
import struct
import sys
import uuid

HEADER = struct.Struct("<4sHHIHHIIQIIQ16s")  # SMB2 header is 64 bytes
BODY = struct.Struct("<HHHHI16sQ")            # NEGOTIATE body is 36 bytes
ETHERNET_INTERFACE = re.compile(r"eth[0-9]{1,2}\Z")
PROTOCOL = b"\xfeSMB"
DIALECT = 0x0302  # SMB3.0.2 only; no 3.1.1 contexts or SMB1 downgrade
MAX_RESPONSE_BYTES = 65536


def demand(ok, code):
    if not ok:
        raise RuntimeError(code)


def make_negotiate():
    # Header: 64, credit 1, command 0=NEGOTIATE, zero Session/Tree ID.
    header = HEADER.pack(
        PROTOCOL, 64, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, b"\0" * 16)
    # StructureSize=36, one dialect, signing enabled, no SMB3.1.1 contexts.
    body = BODY.pack(36, 1, 1, 0, 0, uuid.uuid4().bytes_le, 0)
    pdu = header + body + struct.pack("<H", DIALECT)
    demand(len(header) == 64 and len(body) == 36 and len(pdu) == 102,
           "INVALID_NEGOTIATE_PACKET")
    return struct.pack(">I", len(pdu)) + pdu


def read_exact(sock, n):
    chunks = []
    while n:
        part = sock.recv(n)
        if not part:
            raise EOFError()
        chunks.append(part)
        n -= len(part)
    return b"".join(chunks)


def parse_response(prefix, smb2_header, first_six):
    """Pure classifier. One valid SMB2 header means SMB server replied."""
    demand(len(prefix) == 4 and len(smb2_header) == 64 and
           len(first_six) == 6, "BAD_RESPONSE_FRAMING")
    length = struct.unpack(">I", prefix)[0]
    demand(prefix[0] == 0 and 70 <= length <= MAX_RESPONSE_BYTES,
           "BAD_RESPONSE_FRAMING")
    demand(smb2_header[:4] == PROTOCOL and
           struct.unpack_from("<H", smb2_header, 4)[0] == 64 and
           struct.unpack_from("<H", smb2_header, 12)[0] == 0,
           "NOT_SMB2_NEGOTIATE")
    status = struct.unpack_from("<I", smb2_header, 8)[0]
    if status != 0:
        return "SMB2_ERROR_STATUS_0x%08X" % status
    demand(struct.unpack_from("<H", first_six)[0] == 65,
           "UNEXPECTED_NEGOTIATE_RESPONSE")
    dialect = struct.unpack_from("<H", first_six, 4)[0]
    demand(dialect == DIALECT, "UNEXPECTED_SMB_DIALECT")
    return "SMB3_02_NEGOTIATED"


def probe_one(ip, port):
    """No auth or SMB state-changing requests; every socket is closed."""
    target = ipaddress.ip_address(ip)
    demand(target.version == 4 and (target.is_private or target.is_loopback)
           and ((port == 445) or
                (port == 1445 and str(target) == "127.0.0.1")),
           "INVALID_DIAGNOSTIC_TARGET")
    try:
        with socket.create_connection((str(target), port), timeout=4) as conn:
            conn.settimeout(5)
            conn.sendall(make_negotiate())
            frame = read_exact(conn, 4)
            smb_header = read_exact(conn, 64)
            first_six = read_exact(conn, 6)
            return parse_response(frame, smb_header, first_six)
    except EOFError:
        return "REMOTE_CLOSED_BEFORE_NEGOTIATE_RESPONSE"
    except ConnectionResetError:
        return "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE"
    except TimeoutError:
        return "NEGOTIATE_TIMEOUT"
    except ConnectionRefusedError:
        return "TCP_REFUSED"
    except OSError:
        return "TRANSPORT_ERROR"
    except RuntimeError:
        return "UNEXPECTED_SMB_RESPONSE"


def local_interface_ipv4():
    """Read only configured NAS ethN addresses, never Docker bridges."""
    targets = ["127.0.0.1"]
    for _, name in socket.if_nameindex():
        if not ETHERNET_INTERFACE.fullmatch(name):
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                request = struct.pack("256s", name[:15].encode("ascii"))
                result = fcntl.ioctl(sock.fileno(), 0x8915, request)
                ip = socket.inet_ntoa(result[20:24])
                if ip not in targets:
                    targets.append(ip)
        except OSError:
            continue
    demand(2 <= len(targets) <= 5, "NAS_LOCAL_INTERFACES_NOT_VERIFIED")
    return targets


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller-forward", action="store_true")
    args = parser.parse_args(argv)
    targets = (["127.0.0.1"] if args.controller_forward
               else local_interface_ipv4())
    port = 1445 if args.controller_forward else 445
    results = []
    for target in targets:
        outcome = probe_one(target, port)
        results.append(outcome)
        print("SMB3_02_NEGOTIATE", target, outcome, flush=True)
    print("NO_SMB_AUTHENTICATION_ATTEMPTED")
    print("NO_MUTATING_SMB_REQUESTS_SENT")
    print("NO_FILES_CHANGED")
    if any(value != "SMB3_02_NEGOTIATED" for value in results):
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("SMB3_WIRE_DIAGNOSTIC_BLOCKED", file=sys.stderr)
        raise SystemExit(2)

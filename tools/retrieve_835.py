"""Retrieve one completed 835 return file over OpenSSH; do not delete it remotely.

Use an existing SSH alias/key and an operator-confirmed outgoing file path.
Transport verifies bytes, not X12 semantics or claim acceptance. Import the
returned local_file with manage.py import_835 to validate and view its contents.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import uuid
from pathlib import Path

if __package__:
    from . import edi_receive as common
    from .transfer_edi import SSHTransport as BaseSSHTransport, TransportError
else:
    import edi_receive as common
    from transfer_edi import SSHTransport as BaseSSHTransport, TransportError


# Sent on stdin, never installed on the remote host. The remote path is a
# separately quoted argument; neither path nor payload appears in error output.
REMOTE_FINGERPRINT = '''import hashlib, json, os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 67108864:
            raise ValueError()
        digest, size = hashlib.sha256(), 0
        while True:
            block = f.read(1048576)
            if not block:
                break
            size += len(block)
            if size > 67108864:
                raise ValueError()
            digest.update(block)
        after = os.fstat(f.fileno())
        fields = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
        if fields(before) != fields(after):
            raise ValueError()
    print(json.dumps({"sha256": digest.hexdigest(), "bytes": size, "identity": fields(after)}))
except Exception:
    print(json.dumps({"error": "remote_file_unavailable_or_changed"}))
    sys.exit(1)
'''


def validate(args):
    if not re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*", args.host):
        raise common.TransferError("invalid_host")
    if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.remote_file)
            or any(part in {"", ".", ".."} for part in args.remote_file.split("/")[1:])
            or Path(args.remote_file).suffix.lower() not in {".835", ".edi", ".x12"}):
        raise common.TransferError("invalid_remote_file")
    if ((args.port is not None and not 1 <= args.port <= 65535)
            or not 5 <= args.timeout <= 600):
        raise common.TransferError("invalid_limits")
    if args.identity:
        identity = args.identity.expanduser().absolute()
        info = identity.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise common.TransferError("identity_must_be_private")
        args.identity = identity


def checked_fingerprint(value):
    if (not isinstance(value, dict)
            or not isinstance(value.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or type(value.get("bytes")) is not int
            or not 0 < value["bytes"] <= common.MAX_BYTES
            or not isinstance(value.get("identity"), list)
            or len(value["identity"]) != 5
            or any(type(item) is not int or item < 0 for item in value["identity"])
            or value["identity"][2] != value["bytes"]):
        raise TransportError("invalid_remote_fingerprint")
    return value


class SSHTransport(BaseSSHTransport):
    """Reuse timeout/process-group cleanup from the existing outbound transport."""

    def __init__(self, args):
        self.args = args
        self.options = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                        "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
                        "-o", "ServerAliveCountMax=2", "-o", "ForwardAgent=no",
                        "-o", "ClearAllForwardings=yes", "-o", "ControlMaster=no",
                        "-o", "ControlPath=none"]
        if args.identity:
            self.options.extend(["-i", str(args.identity), "-o", "IdentitiesOnly=yes"])

    def fingerprint(self):
        command = shlex.join(["python3", "-", self.args.remote_file])
        port = ["-p", str(self.args.port)] if self.args.port else []
        result = self.run(["ssh", *self.options, *port, self.args.host, command], REMOTE_FINGERPRINT)
        if result.returncode:
            raise self.failure(result, "remote_file_unavailable_or_changed")
        try:
            if len(result.stdout) > 4096:
                raise ValueError()
            return checked_fingerprint(json.loads(result.stdout))
        except (ValueError, TypeError):
            raise TransportError("invalid_remote_fingerprint") from None

    def download(self, destination):
        port = ["-P", str(self.args.port)] if self.args.port else []
        result = self.run(["scp", "-B", "-q", *self.options, *port,
                           f"{self.args.host}:{self.args.remote_file}", str(destination)])
        if result.returncode:
            raise self.failure(result, "scp_failed")


def retrieve(args, transport_factory=SSHTransport):
    validate(args)
    # A dry run does not connect, create directories, or claim to verify a file.
    if args.dry_run:
        return {"status": "dry_run", "network_checked": False,
                "host": args.host, "output_dir": str(args.output_dir.expanduser().absolute())}
    directory = common.private_dir(args.output_dir.expanduser())
    journal = directory / "returns.jsonl"
    fields = {"run_id": uuid.uuid4().hex, "host": args.host,
              "source_ref": hashlib.sha256(f"{args.host}:{args.remote_file}".encode()).hexdigest()}
    with common.transfer_lock(directory / "retrieve.lock"):
        common.audit(journal, "return_retrieval_started", **fields)
        try:
            transport = transport_factory(args)
            before = checked_fingerprint(transport.fingerprint())
            fields.update(sha256=before["sha256"], bytes=before["bytes"])
            final = directory / f"{before['sha256']}.835"
            if final.exists() or final.is_symlink():
                # Do not overwrite an earlier receipt, even if corrupt.
                fd = common.private_open(final, os.O_RDONLY)
                os.close(fd)
                if common.fingerprint(final) != (before["sha256"], before["bytes"]):
                    raise TransportError("destination_conflict")
                common.audit(journal, "return_already_present", **fields)
                return {"status": "already_present", "local_file": str(final),
                        "sha256": before["sha256"], "bytes": before["bytes"], "audit_log": str(journal)}
            with tempfile.TemporaryDirectory(prefix="return-", dir=directory) as staging:
                temporary = Path(staging) / "payload.part"
                fd = common.private_open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                transport.download(temporary)
                # The destination was created privately. Reject any unexpected
                # mode widening or file replacement before publication.
                fd = common.private_open(temporary, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                local = common.fingerprint(temporary)
                after = checked_fingerprint(transport.fingerprint())
                if before != after:
                    raise TransportError("remote_file_changed")
                if local != (before["sha256"], before["bytes"]):
                    raise TransportError("checksum_mismatch")
                try:
                    # Atomic visibility and O_EXCL-like no-overwrite semantics.
                    os.link(temporary, final, follow_symlinks=False)
                except FileExistsError:
                    raise TransportError("destination_conflict") from None
                common.sync_dir(directory)
                common.audit(journal, "return_retrieved", **fields)
            return {"status": "retrieved", "local_file": str(final),
                    "sha256": before["sha256"], "bytes": before["bytes"], "audit_log": str(journal)}
        except (common.TransferError, OSError, KeyboardInterrupt) as exc:
            code = "interrupted" if isinstance(exc, KeyboardInterrupt) else (
                str(exc) if isinstance(exc, common.TransferError) else "local_filesystem_error")
            common.audit(journal, "return_retrieval_failed", error_code=code, **fields)
            raise


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Existing SSH config alias or user@hostname")
    parser.add_argument("--remote-file", required=True,
                        help="Confirmed completed file: absolute path, no spaces; .835/.edi/.x12")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Private local directory for verified files and metadata journal")
    parser.add_argument("--identity", type=Path, help="Optional existing private key; otherwise use SSH config")
    parser.add_argument("--port", type=int, help="Optional port override; otherwise use SSH config")
    parser.add_argument("--timeout", type=int, default=60, help="Per-operation seconds; 5 to 600")
    parser.add_argument("--dry-run", action="store_true", help="Validate arguments only; no network or writes")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    os.umask(0o077)
    try:
        result = retrieve(args)
    except KeyboardInterrupt:
        print(json.dumps({"status": "error", "code": "interrupted"}), file=sys.stderr)
        return 130
    except (common.TransferError, OSError) as exc:
        code = str(exc) if isinstance(exc, common.TransferError) else "local_filesystem_or_tool_error"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

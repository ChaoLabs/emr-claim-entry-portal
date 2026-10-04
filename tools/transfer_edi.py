"""Transfer an immutable EDI file through OpenSSH SCP with durable receipts.

Run on Janus, not inside a Vercel request. Uses the Python standard library.
The companion receiver is sent over the verified SSH connection for each call;
no receiver installation, service, dependency, or database migration is needed.
"""

import argparse
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

if __package__:
    from . import edi_receive as common
else:
    import edi_receive as common


class TransportError(common.TransferError):
    pass


RETRYABLE = {"ssh_failed", "scp_failed", "network_timeout", "transfer_busy"}
SUCCESS = {"published", "already_published", "reconciled"}
RECEIVER_CODES = {
    "invalid_request", "unsafe_directory", "directory_must_be_private",
    "file_must_be_private", "invalid_payload_file", "payload_too_large",
    "source_changed", "different_filesystems", "invalid_receipt",
    "receipt_conflict", "destination_conflict", "publication_uncertain",
    "transfer_busy", "checksum_mismatch", "receiver_filesystem_error",
}


def validate(args):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*", args.host):
        raise common.TransferError("invalid_host")
    # An intentionally narrow path grammar is safe for both SFTP and legacy
    # remote-shell SCP implementations. No remote home expansion or shell tokens.
    if (not re.fullmatch(r"/[a-zA-Z0-9_./-]+", args.remote_root)
            or any(part in {".", "..", ""} for part in args.remote_root.split("/")[1:])):
        raise common.TransferError("invalid_remote_root")
    if not 1 <= args.port <= 65535 or not 1 <= args.attempts <= 5 or not 5 <= args.timeout <= 600:
        raise common.TransferError("invalid_limits")
    if args.batch_id:
        try:
            args.batch_id = str(uuid.UUID(args.batch_id))
        except ValueError:
            raise common.TransferError("invalid_batch_id") from None
    identity = args.identity.expanduser().absolute()
    info = identity.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise common.TransferError("identity_must_be_private")
    args.identity = identity


class SSHTransport:
    def __init__(self, args):
        self.args = args
        self.options = ["-i", str(args.identity),
                        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                        "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=10",
                        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
                        "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
                        "-o", "ControlMaster=no", "-o", "ControlPath=none"]
        self.receiver_source = Path(common.__file__).read_text(encoding="utf-8")

    def run(self, argv, source=None):
        try:
            with subprocess.Popen(
                argv, text=True, start_new_session=True,
                stdin=subprocess.DEVNULL if source is None else subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ) as process:
                try:
                    stdout, stderr = process.communicate(source, timeout=self.args.timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                    # scp starts an ssh child. Kill the process group as well
                    # as the parent, so an abandoned upload cannot outlive a retry.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    if isinstance(exc, KeyboardInterrupt):
                        raise
                    raise TransportError("network_timeout") from None
                return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        except OSError:
            raise TransportError("ssh_tool_unavailable") from None

    def failure(self, result, fallback):
        stderr = result.stderr.lower()
        if "host key verification failed" in stderr or "host identification has changed" in stderr:
            return TransportError("host_key_rejected")
        if "permission denied" in stderr:
            return TransportError("ssh_permission_denied")
        return TransportError(fallback)

    def request(self, action, digest, size, token):
        command = shlex.join(["python3", "-", action, self.args.remote_root,
                              digest, str(size), token])
        result = self.run(["ssh", *self.options, "-p", str(self.args.port),
                           self.args.host, command], self.receiver_source)
        try:
            response = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise self.failure(result, "ssh_failed" if result.returncode else "invalid_response") from None
        if not isinstance(response, dict):
            raise TransportError("invalid_response")
        if response.get("status") == "error":
            code = response.get("code", "receiver_error")
            # Never print arbitrary remote error text, which may contain data.
            if not isinstance(code, str) or code not in RECEIVER_CODES:
                code = "receiver_error"
            raise TransportError(code)
        if result.returncode:
            raise self.failure(result, "ssh_failed")
        if (response.get("transfer_id"), response.get("sha256"), response.get("bytes")) != (digest, digest, size):
            raise TransportError("invalid_response")
        if response.get("status") not in SUCCESS | {"upload_required"}:
            raise TransportError("invalid_response")
        return response["status"]

    def upload(self, snapshot, digest, token):
        destination = f"{self.args.host}:{self.args.remote_root}/staging/{digest}.{token}.part"
        result = self.run(["scp", "-B", "-q", *self.options, "-P", str(self.args.port),
                           str(snapshot), destination])
        if result.returncode:
            raise self.failure(result, "scp_failed")


def transfer(args, transport_factory=SSHTransport, sleep=time.sleep):
    validate(args)
    if args.dry_run:
        digest, size = common.fingerprint(args.file)
        return {"status": "dry_run", "transfer_id": digest, "sha256": digest,
                "bytes": size, "host": args.host, "remote_root": args.remote_root}

    state_dir = common.private_dir(args.state_dir.expanduser())
    journal = state_dir / "transfers.jsonl"
    with common.transfer_lock(state_dir / "sender.lock"):
        # All attempts in this invocation upload this same private snapshot.
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=state_dir) as directory:
            snapshot = Path(directory) / "payload.edi"
            fd = common.private_open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "wb") as handle:
                digest, size = common.fingerprint(args.file, copy_to=handle)
                handle.flush()
                os.fsync(handle.fileno())
            fields = {"transfer_id": digest, "sha256": digest, "bytes": size,
                      "host": args.host, "port": args.port, "remote_root": args.remote_root,
                      "run_id": uuid.uuid4().hex}
            if args.batch_id:
                fields["batch_id"] = args.batch_id
            common.audit(journal, "transfer_started", **fields)
            transport = transport_factory(args)
            for attempt in range(1, args.attempts + 1):
                started = time.monotonic()
                token = uuid.uuid4().hex
                common.audit(journal, "attempt_started", attempt=attempt, upload_token=token, **fields)
                try:
                    status = transport.request("prepare", digest, size, token)
                    if status == "upload_required":
                        transport.upload(snapshot, digest, token)
                        common.audit(journal, "uploaded", attempt=attempt, **fields)
                        status = transport.request("publish", digest, size, token)
                    if status not in SUCCESS:
                        raise TransportError("invalid_response")
                    elapsed = round((time.monotonic() - started) * 1000)
                    common.audit(journal, "transfer_complete", attempt=attempt,
                                 outcome=status, duration_ms=elapsed, **fields)
                    return {"status": status, "transfer_id": digest, "sha256": digest,
                            "bytes": size, "remote_file": f"{args.remote_root}/inbox/{digest}.edi",
                            "audit_log": str(journal)}
                except (TransportError, KeyboardInterrupt) as exc:
                    code = "interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc)
                    common.audit(journal, "attempt_failed", attempt=attempt, error_code=code,
                                 duration_ms=round((time.monotonic() - started) * 1000), **fields)
                    if attempt == args.attempts or code not in RETRYABLE:
                        common.audit(journal, "transfer_failed", error_code=code, **fields)
                        raise
                    sleep(min(2 ** (attempt - 1), 8))
    raise AssertionError("unreachable")


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--host", required=True, help="SSH user@hostname or user@IPv4")
    parser.add_argument("--remote-root", required=True, help="Absolute private directory; no spaces")
    parser.add_argument("--identity", type=Path, required=True, help="Existing private SSH key")
    parser.add_argument("--state-dir", type=Path, required=True, help="Private local audit directory")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--attempts", type=int, default=3, help="1 to 5; default 3")
    parser.add_argument("--timeout", type=int, default=60, help="Per-operation seconds; default 60")
    parser.add_argument("--batch-id", help="Optional SubmissionBatch UUID for log correlation")
    parser.add_argument("--dry-run", action="store_true", help="Read and hash only; no network or writes")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    os.umask(0o077)
    try:
        result = transfer(args)
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

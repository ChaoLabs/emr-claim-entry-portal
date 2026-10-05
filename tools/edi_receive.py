"""Filesystem receiver with private state, executed over SSH by transfer_edi.py.

Python standard library only. No daemon, Django configuration, or installation.
An inbox file means transport complete, never adjudication accepted.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


class TransferError(Exception):
    """A fixed error code safe to write to audit logs."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def private_dir(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise TransferError("unsafe_directory")
    existed = path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise TransferError("directory_must_be_private")
    if not existed:
        sync_dir(path.parent)
    return path


def private_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        os.close(fd)
        raise TransferError("file_must_be_private")
    return fd


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def transfer_lock(path):
    fd = private_open(path, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TransferError("transfer_busy") from None
        yield
    finally:
        os.close(fd)


def audit(path, event, **fields):
    record = {"timestamp_utc": utc_now(), "event": event, **fields}
    existed = path.exists()
    fd = private_open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if not existed:
        sync_dir(path.parent)


def write_json(path, record):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = private_open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    fd = private_open(path, os.O_RDONLY)
    with os.fdopen(fd, encoding="utf-8") as handle:
        try:
            value = json.loads(handle.read(8192))
        except (ValueError, UnicodeError):
            raise TransferError("invalid_receipt") from None
    if not isinstance(value, dict):
        raise TransferError("invalid_receipt")
    return value


def fingerprint(path, copy_to=None):
    """Hash a regular, non-symlink file; optionally snapshot the same bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
            raise TransferError("invalid_payload_file")
        digest = hashlib.sha256()
        size = 0
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise TransferError("payload_too_large")
            digest.update(chunk)
            if copy_to is not None:
                copy_to.write(chunk)
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise TransferError("source_changed")
    return digest.hexdigest(), size


def shared_inbox(path, root):
    """Use an existing operator-managed inbox without changing its permissions."""
    path = Path(path)
    if (not path.is_absolute() or path.resolve() != path
            or path == root or root in path.parents or path in root.parents):
        raise TransferError("unsafe_shared_inbox")
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise TransferError("shared_inbox_unavailable")
    return path


def receive(action, root, digest, size, token, inbox_path=None, file_mode=0o600):
    if (action not in {"prepare", "publish"}
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not re.fullmatch(r"[0-9a-f]{32}", token)
            or not 0 < size <= MAX_BYTES
            or file_mode not in {0o600, 0o640, 0o644}
            or (inbox_path is None and file_mode != 0o600)):
        raise TransferError("invalid_request")
    root = private_dir(root)
    staging = private_dir(root / "staging")
    inbox = private_dir(root / "inbox") if inbox_path is None else shared_inbox(inbox_path, root)
    receipts = private_dir(root / "receipts")
    locks = private_dir(root / "locks")
    log_dir = private_dir(root / "logs")
    if inbox_path is not None:
        # A receipt for the old private inbox must never suppress a delivery
        # to the shared inbox. Bind receipts and locks to the destination.
        destination_id = hashlib.sha256(str(inbox).encode("utf-8")).hexdigest()
        receipts = private_dir(receipts / destination_id)
        locks = private_dir(locks / destination_id)
    # Both names must be on one filesystem for an atomic, no-overwrite link.
    if staging.stat().st_dev != inbox.stat().st_dev:
        raise TransferError("different_filesystems")
    temporary = staging / f"{digest}.{token}.part"
    final = inbox / f"{digest}.edi"
    receipt_path = receipts / f"{digest}.json"
    fields = {"transfer_id": digest, "sha256": digest, "bytes": size}
    version = 1
    if inbox_path is not None:
        version = 2
        fields.update(destination=str(final), file_mode=f"{file_mode:04o}")
    log = log_dir / "receive.jsonl"

    def matches(path):
        return fingerprint(path) == (digest, size)

    def prior_result():
        if receipt_path.exists() or receipt_path.is_symlink():
            receipt = read_json(receipt_path)
            if receipt.get("version") != version or any(receipt.get(k) != v for k, v in fields.items()):
                raise TransferError("receipt_conflict")
            state = receipt.get("state")
            if state not in {"publishing", "published"}:
                raise TransferError("invalid_receipt")
            if final.exists() or final.is_symlink():
                if not matches(final):
                    raise TransferError("destination_conflict")
                if state == "publishing":
                    sync_dir(inbox)
                    receipt.update(state="published", published_at_utc=utc_now())
                    write_json(receipt_path, receipt)
                    audit(log, "publication_reconciled", **fields)
                    return "reconciled"
            elif state == "publishing":
                # A consumer may already have moved the file. Never guess or
                # automatically publish another copy after this ambiguous crash.
                raise TransferError("publication_uncertain")
            audit(log, "already_published", **fields)
            return "already_published"
        if final.exists() or final.is_symlink():
            raise TransferError("destination_conflict")
        return None

    with transfer_lock(locks / f"{digest}.lock"):
        try:
            previous = prior_result()
            if previous:
                return {"status": previous, **fields}
            if action == "prepare":
                fd = private_open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                audit(log, "upload_prepared", upload_token=token, **fields)
                return {"status": "upload_required", **fields}

            fd = private_open(temporary, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if not matches(temporary):
                # Leave rejected bytes in private staging, outside the inbox.
                raise TransferError("checksum_mismatch")
            audit(log, "checksum_verified", upload_token=token, **fields)
            receipt = {"version": version, **fields, "state": "publishing",
                       "started_at_utc": utc_now()}
            write_json(receipt_path, receipt)
            audit(log, "publication_started", **fields)
            # Set read permissions while the complete file is still in private
            # staging. Publication is one atomic, no-overwrite link operation.
            fd = private_open(temporary, os.O_RDONLY)
            try:
                os.fchmod(fd, file_mode)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.link(temporary, final, follow_symlinks=False)
            sync_dir(inbox)
            receipt.update(state="published", published_at_utc=utc_now())
            write_json(receipt_path, receipt)
            audit(log, "published", **fields)
            temporary.unlink()
            sync_dir(staging)
            return {"status": "published", **fields}
        except TransferError as exc:
            audit(log, "receive_failed", error_code=str(exc), **fields)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("root", type=Path)
    parser.add_argument("digest")
    parser.add_argument("size", type=int)
    parser.add_argument("token")
    parser.add_argument("--inbox", type=Path, help="Existing shared inbox outside the private root")
    parser.add_argument("--file-mode", choices=["0600", "0640", "0644"], default="0600")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        result = receive(args.action, args.root, args.digest, args.size, args.token,
                         args.inbox, int(args.file_mode, 8))
    except (TransferError, OSError) as exc:
        code = str(exc) if isinstance(exc, TransferError) else "receiver_filesystem_error"
        print(json.dumps({"status": "error", "code": code}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

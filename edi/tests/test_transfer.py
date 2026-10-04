"""Transport tests use temporary files and local subprocesses; never SSH."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from tools import edi_receive as receiver
from tools import transfer_edi as sender


class LocalTransport:
    """Exercise the real receiver, replacing only the network boundary."""

    def __init__(self, args):
        self.root = Path(args.remote_root)
        self.uploads = 0
        self.actions = []
        self.interrupt_upload = False
        self.lose_ack = False
        self.source_to_change = None

    def request(self, action, digest, size, token):
        self.actions.append(action)
        try:
            result = receiver.receive(action, self.root, digest, size, token)
        except receiver.TransferError as exc:
            raise sender.TransportError(str(exc)) from exc
        if action == "publish" and self.lose_ack:
            self.lose_ack = False
            raise sender.TransportError("network_timeout")
        return result["status"]

    def upload(self, snapshot, digest, token):
        self.uploads += 1
        if self.source_to_change:
            self.source_to_change.write_bytes(b"changed after the snapshot")
        data = snapshot.read_bytes()
        part = self.root / "staging" / f"{digest}.{token}.part"
        if self.interrupt_upload:
            self.interrupt_upload = False
            part.write_bytes(data[:3])
            assert not list((self.root / "inbox").iterdir())
            raise sender.TransportError("scp_failed")
        part.write_bytes(data)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.payload = self.base / "original.edi"
        self.data = b"ISA*FICTIONAL-TEST~ST*837*0001~CLM*TEST~SE*3*0001~IEA*1*1~"
        self.payload.write_bytes(self.data)
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.root = self.base / "receiver"
        self.state = self.base / "sender"
        self.identity = self.base / "test-key"
        self.identity.touch(mode=0o600)
        self.args = sender.argument_parser().parse_args([
            str(self.payload), "--host", "test@vesta.example",
            "--identity", str(self.identity), "--remote-root", str(self.root),
            "--state-dir", str(self.state),
        ])
        self.transport = LocalTransport(self.args)

    def transfer(self):
        return sender.transfer(self.args, lambda args: self.transport, sleep=lambda seconds: None)

    def stage(self, data=None, token=None):
        token = token or uuid.uuid4().hex
        receiver.receive("prepare", self.root, self.digest, len(self.data), token)
        path = self.root / "staging" / f"{self.digest}.{token}.part"
        path.write_bytes(self.data if data is None else data)
        return token, path

    def publish(self, token):
        return receiver.receive("publish", self.root, self.digest, len(self.data), token)

    def test_complete_transfer_and_permissions(self):
        result = self.transfer()
        self.assertEqual(result["status"], "published")
        self.assertEqual(Path(result["remote_file"]).read_bytes(), self.data)
        self.assertEqual(self.transport.uploads, 1)
        self.assertFalse(list((self.root / "staging").iterdir()))
        receipt = receiver.read_json(self.root / "receipts" / f"{self.digest}.json")
        self.assertEqual(receipt["state"], "published")
        for parent in (self.root, self.state):
            for path in [parent, *parent.rglob("*")]:
                self.assertEqual(path.stat().st_mode & 0o077, 0, str(path))
        events = [json.loads(line) for line in Path(result["audit_log"]).read_text().splitlines()]
        self.assertEqual(events[-1]["event"], "transfer_complete")
        self.assertTrue(all(event["timestamp_utc"].endswith("+00:00") for event in events))
        self.assertNotIn("FICTIONAL", Path(result["audit_log"]).read_text())

    def test_repeat_does_not_upload_again(self):
        self.transfer()
        self.assertEqual(self.transfer()["status"], "already_published")
        self.assertEqual(self.transport.uploads, 1)
        self.assertEqual(len(list((self.root / "inbox").iterdir())), 1)

    def test_receipt_prevents_duplicate_after_consumer_moves_file(self):
        result = self.transfer()
        Path(result["remote_file"]).rename(self.base / "processed.edi")
        self.assertEqual(self.transfer()["status"], "already_published")
        self.assertEqual(self.transport.uploads, 1)
        self.assertFalse(list((self.root / "inbox").iterdir()))

    def test_lost_publication_ack_reconciles_without_another_upload(self):
        self.transport.lose_ack = True
        self.assertEqual(self.transfer()["status"], "already_published")
        self.assertEqual(self.transport.uploads, 1)
        self.assertEqual(self.transport.actions, ["prepare", "publish", "prepare"])

    def test_interrupted_scp_is_not_visible_and_can_retry(self):
        self.transport.interrupt_upload = True
        self.assertEqual(self.transfer()["status"], "published")
        self.assertEqual(self.transport.uploads, 2)
        self.assertEqual(len(list((self.root / "inbox").iterdir())), 1)
        self.assertEqual(len(list((self.root / "staging").iterdir())), 1)

    def test_snapshot_is_immutable_during_upload(self):
        self.transport.source_to_change = self.payload
        result = self.transfer()
        self.assertNotEqual(self.payload.read_bytes(), self.data)
        self.assertEqual(Path(result["remote_file"]).read_bytes(), self.data)

    def test_corrupt_upload_is_not_published(self):
        token, part = self.stage(b"X" * len(self.data))
        with self.assertRaisesRegex(receiver.TransferError, "checksum_mismatch"):
            self.publish(token)
        self.assertTrue(part.exists())
        self.assertFalse(list((self.root / "inbox").iterdir()))
        self.assertFalse(list((self.root / "receipts").iterdir()))

    def test_short_upload_is_not_published(self):
        token, _ = self.stage(self.data[:-1])
        with self.assertRaisesRegex(receiver.TransferError, "checksum_mismatch"):
            self.publish(token)
        self.assertFalse(list((self.root / "inbox").iterdir()))

    def test_existing_destination_is_never_overwritten(self):
        token, _ = self.stage()
        final = self.root / "inbox" / f"{self.digest}.edi"
        final.write_bytes(b"existing data")
        with self.assertRaisesRegex(receiver.TransferError, "destination_conflict"):
            self.publish(token)
        self.assertEqual(final.read_bytes(), b"existing data")

    def test_symlink_payload_is_rejected(self):
        link = self.base / "link.edi"
        link.symlink_to(self.payload)
        self.args.file = link
        with self.assertRaises(OSError):
            self.transfer()
        self.assertEqual(self.transport.uploads, 0)

    def test_symlink_root_is_rejected(self):
        self.root.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(receiver.TransferError, "unsafe_directory"):
            self.stage()

    def test_crash_after_publication_before_receipt_is_reconciled(self):
        token, _ = self.stage()
        real_write = receiver.write_json

        def crash(path, record):
            if record["state"] == "published":
                raise OSError("simulated disk error")
            real_write(path, record)

        with patch.object(receiver, "write_json", side_effect=crash):
            with self.assertRaises(OSError):
                self.publish(token)
        response = receiver.receive("prepare", self.root, self.digest, len(self.data), uuid.uuid4().hex)
        self.assertEqual(response["status"], "reconciled")
        self.assertEqual(len(list((self.root / "inbox").iterdir())), 1)

    def test_ambiguous_publication_does_not_redeliver(self):
        token, _ = self.stage()
        with patch.object(receiver.os, "link", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.publish(token)
        with self.assertRaisesRegex(receiver.TransferError, "publication_uncertain"):
            receiver.receive("prepare", self.root, self.digest, len(self.data), uuid.uuid4().hex)
        self.assertFalse(list((self.root / "inbox").iterdir()))

    def test_two_prepared_uploads_publish_only_once(self):
        first, _ = self.stage()
        second, _ = self.stage()
        self.assertEqual(self.publish(first)["status"], "published")
        self.assertEqual(self.publish(second)["status"], "already_published")
        self.assertEqual(len(list((self.root / "inbox").iterdir())), 1)

    def test_concurrent_publisher_fails_with_busy(self):
        token, _ = self.stage()
        with receiver.transfer_lock(self.root / "locks" / f"{self.digest}.lock"):
            with self.assertRaisesRegex(receiver.TransferError, "transfer_busy"):
                self.publish(token)

    def test_dry_run_makes_no_writes_or_network_calls(self):
        self.args.dry_run = True
        with patch.object(subprocess, "Popen", side_effect=AssertionError("network attempted")):
            result = self.transfer()
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(self.state.exists())
        self.assertFalse(self.root.exists())
        self.assertFalse(self.transport.actions)

    def test_path_and_host_shell_tokens_are_rejected(self):
        for field, value in [("host", "-oProxyCommand=bad"),
                             ("host", "test@host;touch /tmp/file"),
                             ("remote_root", "/tmp/$(touch bad)"),
                             ("remote_root", "/tmp/../other"),
                             ("remote_root", "~/inbox")]:
            original = getattr(self.args, field)
            setattr(self.args, field, value)
            with self.subTest(value=value), self.assertRaises(receiver.TransferError):
                self.transfer()
            setattr(self.args, field, original)

    def test_strict_noninteractive_ssh_and_scp_arguments(self):
        network = sender.SSHTransport(self.args)
        reply = {"status": "upload_required", "transfer_id": self.digest,
                 "sha256": self.digest, "bytes": len(self.data)}
        with patch.object(network, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(reply), "")) as run:
            network.request("prepare", self.digest, len(self.data), "a" * 32)
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], "ssh")
            self.assertIn("BatchMode=yes", argv)
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertIn("def receive(", run.call_args.args[1])
        with patch.object(network, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            network.upload(self.payload, self.digest, "a" * 32)
            self.assertIn("-B", run.call_args.args[0])
            self.assertEqual(len(run.call_args.args), 1)

    def test_host_key_error_does_not_retry_or_leak_stderr(self):
        network = sender.SSHTransport(self.args)
        result = subprocess.CompletedProcess([], 255, "", "Host key verification failed. SECRET")
        with patch.object(network, "run", return_value=result) as run:
            with self.assertRaisesRegex(sender.TransportError, "host_key_rejected"):
                sender.transfer(self.args, lambda args: network, sleep=lambda seconds: None)
        self.assertEqual(run.call_count, 1)
        journal = (self.state / "transfers.jsonl").read_text()
        self.assertNotIn("SECRET", journal)
        self.assertIn("host_key_rejected", journal)

    def test_real_subprocess_timeout_terminates_ssh_style_child_group(self):
        network = sender.SSHTransport(self.args)
        self.args.timeout = 0.2
        command = [sys.executable, "-c",
                   "import subprocess,sys,time; "
                   "subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)']); "
                   "time.sleep(30)"]
        with self.assertRaisesRegex(sender.TransportError, "network_timeout"):
            network.run(command)

    def test_retries_are_bounded(self):
        with patch.object(self.transport, "request", side_effect=sender.TransportError("network_timeout")) as request:
            with self.assertRaisesRegex(sender.TransportError, "network_timeout"):
                self.transfer()
        self.assertEqual(request.call_count, 3)
        self.assertEqual(self.transport.uploads, 0)

    def test_receiver_really_runs_as_stdin_script(self):
        script = Path(receiver.__file__).read_text()
        token = uuid.uuid4().hex
        command = [sys.executable, "-", "prepare", str(self.root), self.digest, str(len(self.data)), token]
        result = subprocess.run(command, input=script, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "upload_required")
        part = self.root / "staging" / f"{self.digest}.{token}.part"
        part.write_bytes(self.data)
        command[2] = "publish"
        result = subprocess.run(command, input=script, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "published")


if __name__ == "__main__":
    unittest.main()

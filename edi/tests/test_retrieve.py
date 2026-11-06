"""Return transport tests replace the network boundary, not receipt checks."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import edi_receive as common
from tools import retrieve_835 as returns


class LocalTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.downloads = 0
        self.partial = False
        self.corrupt = False
        self.change_remote = False

    def fingerprint(self):
        self.calls += 1
        return {"sha256": hashlib.sha256(self.payload).hexdigest(), "bytes": len(self.payload),
                "identity": [1, 2, len(self.payload), 5 if self.change_remote and self.calls > 1 else 3, 4]}

    def download(self, path):
        self.downloads += 1
        path.write_bytes(b"truncated" if self.partial else b"corrupt" if self.corrupt else self.payload)
        if self.partial:
            raise returns.TransportError("scp_failed")


class RetrieveReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "received"
        self.args = returns.argument_parser().parse_args([
            "--host", "vesta-demo", "--remote-file", "/srv/X12/835/completed.835",
            "--output-dir", str(self.output),
        ])
        # Bytes need not be valid X12 here: semantic validation belongs to import_835.
        self.payload = b"ST*835*0001~CLP*FICTIONAL-CONTROL*1*100*75*25~SE*3*0001~"
        self.transport = LocalTransport(self.payload)

    def retrieve(self):
        return returns.retrieve(self.args, lambda args: self.transport)

    def test_verified_receipt_is_private_and_audit_contains_no_payload_or_remote_filename(self):
        result = self.retrieve()
        file = Path(result["local_file"])
        self.assertEqual(result["status"], "retrieved")
        self.assertEqual(file.read_bytes(), self.payload)
        self.assertEqual(file.name, hashlib.sha256(self.payload).hexdigest() + ".835")
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        log = (self.output / "returns.jsonl").read_text()
        self.assertNotIn("FICTIONAL-CONTROL", log)
        self.assertNotIn("completed.835", log)
        self.assertEqual(json.loads(log.splitlines()[-1])["event"], "return_retrieved")
        self.assertFalse(list(self.output.glob("return-*")))
        self.assertEqual(self.transport.calls, 2)

    def test_retry_does_not_overwrite_or_download_again(self):
        first = self.retrieve()
        path = Path(first["local_file"])
        before = path.stat().st_mtime_ns
        second = self.retrieve()
        self.assertEqual(second["status"], "already_present")
        self.assertEqual(self.transport.downloads, 1)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_corrupt_existing_destination_is_never_overwritten(self):
        path = Path(self.retrieve()["local_file"])
        path.write_bytes(b"earlier data")
        with self.assertRaisesRegex(returns.TransportError, "destination_conflict"):
            self.retrieve()
        self.assertEqual(path.read_bytes(), b"earlier data")
        self.assertEqual(self.transport.downloads, 1)

    def test_interrupted_download_is_never_visible_and_staging_is_removed(self):
        self.transport.partial = True
        with self.assertRaisesRegex(returns.TransportError, "scp_failed"):
            self.retrieve()
        self.assertFalse(list(self.output.glob("*.835")))
        self.assertFalse(list(self.output.glob("return-*")))
        self.assertIn('"error_code": "scp_failed"', (self.output / "returns.jsonl").read_text())

    def test_checksum_mismatch_is_not_published(self):
        self.transport.corrupt = True
        with self.assertRaisesRegex(returns.TransportError, "checksum_mismatch"):
            self.retrieve()
        self.assertFalse(list(self.output.glob("*.835")))

    def test_changed_remote_identity_is_not_published_even_if_bytes_match(self):
        self.transport.change_remote = True
        with self.assertRaisesRegex(returns.TransportError, "remote_file_changed"):
            self.retrieve()
        self.assertFalse(list(self.output.glob("*.835")))

    def test_dry_run_has_no_network_or_filesystem_writes(self):
        self.args.dry_run = True
        result = returns.retrieve(self.args, lambda args: self.fail("must not construct transport"))
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["network_checked"])
        self.assertFalse(self.output.exists())

    def test_unsafe_remote_paths_and_hosts_are_rejected_before_network(self):
        for path in ["/srv/a;touch.835", "/srv/$(whoami).835", "/srv/../return.835",
                     "/srv//return.835", "/srv/./return.835", "~/return.835",
                     "/srv/return.835.part", "/srv/space name.835", "/srv/a'quote.835"]:
            with self.subTest(path=path):
                self.args.remote_file = path
                with self.assertRaisesRegex(common.TransferError, "invalid_remote_file"):
                    self.retrieve()
        self.args.remote_file = "/srv/return.835"
        for host in ["-oProxyCommand=bad", "user@host;bad", "user@host:22", "$(bad)"]:
            with self.subTest(host=host):
                self.args.host = host
                with self.assertRaisesRegex(common.TransferError, "invalid_host"):
                    self.retrieve()
        self.assertEqual(self.transport.calls, 0)
        self.assertFalse(self.output.exists())

    def test_symlink_output_directory_is_rejected(self):
        target = self.base / "target"
        target.mkdir(mode=0o700)
        self.output.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(common.TransferError, "unsafe_directory"):
            self.retrieve()
        self.assertFalse(list(target.iterdir()))

    def test_symlink_destination_is_rejected_without_touching_target(self):
        self.output.mkdir(mode=0o700)
        other = self.base / "other"
        other.write_bytes(b"untouched")
        destination = self.output / (hashlib.sha256(self.payload).hexdigest() + ".835")
        destination.symlink_to(other)
        with self.assertRaises(OSError):
            self.retrieve()
        self.assertEqual(other.read_bytes(), b"untouched")
        self.assertEqual(self.transport.downloads, 0)

    def test_atomic_publication_race_does_not_overwrite(self):
        real_link = os.link

        def competing_write(source, destination, **kwargs):
            Path(destination).write_bytes(b"other received file")
            return real_link(source, destination, **kwargs)

        with patch.object(returns.os, "link", side_effect=competing_write):
            with self.assertRaisesRegex(returns.TransportError, "destination_conflict"):
                self.retrieve()
        final = self.output / (hashlib.sha256(self.payload).hexdigest() + ".835")
        self.assertEqual(final.read_bytes(), b"other received file")

    def test_remote_script_hashes_regular_files_and_rejects_symlink(self):
        payload = self.base / "return.835"
        payload.write_bytes(self.payload)

        def run(path):
            return subprocess.run([sys.executable, "-", str(path)], input=returns.REMOTE_FINGERPRINT,
                                  text=True, capture_output=True, check=False)

        result = run(payload)
        self.assertEqual(result.returncode, 0)
        parsed = returns.checked_fingerprint(json.loads(result.stdout))
        self.assertEqual(parsed["sha256"], hashlib.sha256(self.payload).hexdigest())
        link = self.base / "link.835"
        link.symlink_to(payload)
        result = run(link)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(str(payload), result.stdout + result.stderr)

    def test_ssh_options_require_known_host_and_do_not_override_config_port(self):
        transport = returns.SSHTransport(self.args)
        fingerprint = self.transport.fingerprint()
        result = subprocess.CompletedProcess([], 0, json.dumps(fingerprint), "")
        with patch.object(transport, "run", return_value=result) as run:
            transport.fingerprint()
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], "ssh")
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertIn("BatchMode=yes", argv)
            self.assertNotIn("-p", argv)
            self.assertEqual(argv[-2], "vesta-demo")
            self.assertEqual(argv[-1], "python3 - /srv/X12/835/completed.835")

    def test_explicit_private_identity_and_port_are_supported(self):
        key = self.base / "key"
        key.touch(mode=0o600)
        self.args.identity = key
        self.args.port = 2222
        returns.validate(self.args)
        transport = returns.SSHTransport(self.args)
        with patch.object(transport, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            transport.download(self.base / "part")
            argv = run.call_args.args[0]
            self.assertIn(str(key), argv)
            self.assertIn("IdentitiesOnly=yes", argv)
            self.assertIn("-P", argv)
            self.assertIn("2222", argv)
            self.assertNotIn("-O", argv)

    def test_malformed_remote_response_is_not_trusted(self):
        value = self.transport.fingerprint()
        for field, bad_value in [("sha256", "not-a-digest"), ("bytes", True),
                                 ("identity", []), ("bytes", common.MAX_BYTES + 1)]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(returns.TransportError, "invalid_remote_fingerprint"):
                    returns.checked_fingerprint({**value, field: bad_value})


if __name__ == "__main__":
    unittest.main()

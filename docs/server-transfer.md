# Janus to Vesta SCP transport

`tools/transfer_edi.py` sends an existing immutable file using system `ssh` and
`scp`. It needs Python 3.12+ on the sender and receiver, with no additional
packages, database tables, daemon, scheduler, or receiver installation.
`tools/edi_receive.py` is transmitted over the authenticated SSH connection
and executed with `python3 -` for each operation. Keep both files together.

This phase delivers files and records transport results. It does not call an
adjudication API, interpret 835 responses, or mark claims accepted. Vercel is
unchanged; run the sender on Janus using the existing virtual environment.

## One-time SSH preparation

Use the existing Janus checkout and Python environment. Replace example host
names with the servers provided by the administrator; no real addresses or
credentials should be committed to this repository.

1. Verify Vesta's SSH host key against an administrator-provided fingerprint or
   a previously trusted connection. Preserve the verified `known_hosts` entry.
2. Use a dedicated SSH key for this transfer. Keep its private half on Janus,
   outside the repository. Reuse an existing dedicated key if one was already
   created; do not overwrite an existing GitHub key.
3. Authorize its public half for your account on Vesta. A passphrase-protected
   key needs an already-unlocked local agent. For unattended service operation,
   use a protected service key and agree account/key restrictions with the
   administrator. Never place a password in a script or Vercel variable.
4. Check the connection in batch mode using the intended key:

```bash
ssh -i "$HOME/.ssh/emr_vesta_ed25519" \
  -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  chao@vesta.example 'hostname'
```

The account must be able to run Python and use SCP/SFTP. Use an account-owned
private directory such as `/home/chao/emr-claim-poc` for fictional POC input.
The receiver creates its folders with mode `0700` and files with mode `0600`.
It rejects preexisting shared or symlink directories rather than changing
unrelated permissions. No `sudo` or `/srv/EDI` access is required for this POC.

## Shared 837P inbox (October 5 handoff)

The confirmed Vesta handoff directories are `/srv/X12/837P` for incoming
claims and `/srv/X12/835` for responses. Tim owns the Claim server deployment
and consumer. This sender publishes a complete `.edi` file in the 837P directory;
it does not start the consumer or create an 835 response.

Use `--remote-inbox` for the shared inbox and keep `--remote-root` as a separate
private state directory. Do not set the root to the shared inbox or copy files
there manually before using this command: publication deliberately refuses
an existing destination file without a matching receipt.

On Janus, reuse the existing checkout, virtual environment, SSH key, and
fictional `test-001.edi`. Replace only the example hostname below with the
previously verified Vesta host:

```bash
.venv/bin/python tools/transfer_edi.py \
  "$HOME/emr-claim-poc/outbox/test-001.edi" \
  --host chao@vesta.example \
  --remote-root /srv/X12/chao-transfer-state \
  --remote-inbox /srv/X12/837P \
  --file-mode 0644 \
  --identity "$HOME/.ssh/emr_vesta_ed25519" \
  --state-dir "$HOME/emr-claim-poc/transfer-state" \
  --dry-run
```

Run the same command without `--dry-run` to deliver it, then repeat once to
verify `already_published`. The initial dry run checks local arguments and
bytes only; the actual transfer checks remote paths and permissions. The final
path is `/srv/X12/837P/<sha256>.edi`, with no extra `inbox/` directory. Keep the
old private-inbox file and receipts as historical evidence of the earlier test.
This handoff reuses the same bytes and does not generate another claim.

The shared directory must already exist, be accessible to the sender, and have
no symlink components. The receiver does not create, chmod, or chown it. The
private root must be separate from the shared inbox, and its `staging/` must be
on the same filesystem as the inbox. A private root under `/srv/X12` provides
the intended layout; a separately mounted inbox will fail with
`different_filesystems` and must be reviewed before delivery.

`--file-mode` defaults to `0600`. The `0644` example deliberately allows the
fictional sample to be read by Tim's separate service account while the admin
configures shared access. It also allows other local users to read that file.
The observed POC directories were writable by all local users; use only
fictional data in that configuration. Before real claim data, the administrator
must restrict the directories to the agreed accounts/group and verify the
service can read files with the selected mode. `0640` reads depend on the actual
file group; the tool does not change ownership or add users to groups.

Staging, receipts, locks, and audit logs remain private. Shared-file permissions
are applied only after verification, before the atomic publication. Existing
private-inbox commands and version-1 receipts keep their original behavior.
Shared deliveries use version-2 receipts under
`<remote-root>/receipts/<sha256-of-inbox-path>/<file-sha256>.json`. These include
the exact destination and file mode. They do not inherit the old private-inbox
receipt, and they continue to suppress duplicates after Tim moves a file into
processing. Keep the same private root and mode on subsequent attempts. A
mode change for a recorded delivery produces `receipt_conflict`; it does not
change the delivered file or send it again.

To inspect the new receiver evidence on Vesta:

```bash
tail -n 5 /srv/X12/chao-transfer-state/logs/receive.jsonl
find /srv/X12/chao-transfer-state/receipts -type f -name '*.json' \
  -exec python3 -m json.tool {} \;
```

If the inbox file has disappeared, consult the receipt and Tim's processing
records before redelivery. A completed transfer confirms delivery only. A
fictional NPI/member may fail Tim's business checks against his reference data.
Agree on `.edi` discovery, startup scans, processing moves, duplicate claim
handling, and 835 naming/correlation with Tim before calling the complete
claims workflow integrated. The `/srv/X12/835` directory is reserved for his
responses and is not modified by this script.

## Send the existing fictional file

From the checkout on Janus, first hash and validate the command without network
access or state writes. This assumes the dedicated key has already been set up:

```bash
.venv/bin/python tools/transfer_edi.py \
  "$HOME/emr-claim-poc/outbox/test-001.edi" \
  --host chao@vesta.example \
  --remote-root /home/chao/emr-claim-poc \
  --identity "$HOME/.ssh/emr_vesta_ed25519" \
  --state-dir "$HOME/emr-claim-poc/transfer-state" \
  --dry-run
```

Repeat the same command without `--dry-run` to transfer it. Expected status:

| Status | Meaning |
| --- | --- |
| `published` | Byte count and SHA-256 verified; inbox file published |
| `already_published` | A durable receipt exists; no new upload is needed |
| `reconciled` | A complete inbox file was found after an interrupted receipt update |
| `error` | Read the fixed `code` value and the sender audit log |

The JSON result reports `transfer_id`, `sha256`, `bytes`, `remote_file`, and
`audit_log`. The transfer ID is the full SHA-256 of the file, and the receiver
uses `<transfer_id>.edi` as the inbox filename. Running the exact command a
second time should report `already_published`. It should not create another
inbox file. Different bytes, even for the same claim, are a different transfer.
This is transport deduplication, not claim/adjudication idempotency.

Optional settings: `--batch-id UUID` adds the generation batch ID to sender
events; `--port` defaults to 22; `--attempts` defaults to 3 and is capped at 5;
`--timeout` defaults to 60 seconds per SSH/SCP operation. Retries wait 1, 2,
4, then 8 seconds. A nonzero process exit means no successful confirmation
was recorded locally. Investigate or retry the same bytes; do not regenerate
an 837P merely because an acknowledgment was lost.

## Completion and crash recovery

1. The sender snapshots the file privately and hashes exactly those bytes.
2. The receiver checks any existing receipt before allowing an upload.
3. SCP writes an attempt-specific `.part` file into `staging/`.
4. The receiver verifies the file size and hash, then durably records
   `publishing`. An atomic hard link creates `inbox/<hash>.edi` without replacing
   an existing name. `staging/` and `inbox/` must use the same filesystem.
5. It durably records `published`, appends an audit event, and removes that
   attempt's staging name. The sender appends `transfer_complete` after the reply.

The consumer may only read `.edi` files in `inbox/`, never `staging/`.
Retain `receipts/`: these files prevent a repeated upload after a consumer moves
or removes an inbox file. Receiver locks serialize publication of the same
transfer. Sender locks allow one invocation at a time per state directory.

A crash between publication and the completed receipt has two outcomes: an
existing valid inbox file can be reconciled; if that file is absent, the tool
stops with `publication_uncertain`. It cannot know whether the file was already
consumed. Check the receiver/consumer records before any manual recovery. Do
not delete receipts to clear an error. The tool does not promise exactly-once
API execution; that requires Tim's idempotency and status-query contract.

## Logs and troubleshooting

Sender: `<state-dir>/transfers.jsonl`. Receiver: `<remote-root>/logs/receive.jsonl`.
Events contain UTC timestamps, the file hash/size, transfer/run IDs, phases,
attempts, durations, fixed error codes, and optional batch UUID. They never
contain EDI content, claim numbers, member names/IDs, passwords, or arbitrary
SSH stderr. Sender routing fields are private operational metadata.

| Error code | Action |
| --- | --- |
| `host_key_rejected` | Recheck the server identity; do not disable host verification |
| `ssh_permission_denied` | Check the selected key, authorized public key, account, and folder access |
| `ssh_failed`, `scp_failed`, `network_timeout` | Bounded retry; check connectivity if it persists |
| `checksum_mismatch` | File remains in staging; inspect the failed attempt before retrying |
| `destination_conflict`, `receipt_conflict` | Preserve both copies and investigate; never overwrite |
| `publication_uncertain` | Review receipt, inbox, and consumer records before any redelivery |
| `directory_must_be_private`, `file_must_be_private` | Check ownership and access on this POC's paths |
| `receiver_filesystem_error` | Check destination space, permissions, and Python availability |
| `shared_inbox_unavailable` | Administrator must create the agreed inbox and provide write/traverse access |
| `unsafe_shared_inbox` | Use a real absolute inbox path, separate from the private state directory |
| `transfer_busy` | Another sender or publisher is active; retry after it completes |

Partial/rejected uploads remain in private staging, and interrupted local runs
may leave private snapshot directories. They are never consumed automatically.
Remove only confirmed obsolete attempts after reviewing their logs; do not
delete unrelated directories. Log rotation, archival, retention, and tamper
evidence are not automated in this small POC.

## Validation

```bash
.venv/bin/python -m unittest edi.tests.test_transfer -v
```

Tests use temporary local files and the real receiver, including its stdin
entry point. They cover lost replies, partial uploads, corruption, duplicates,
consumed files, uncertain publication, conflicts, locking, permissions, and
shell argument handling. They do not contact Janus or Vesta. A real synthetic
transfer and repeat on those hosts are still required before recording deployment
acceptance. Existing Django workflow tests continue to discover this module.

Implementation references: [OpenSSH SCP](https://man.openbsd.org/scp),
[SSH configuration](https://man.openbsd.org/ssh_config), and
[Python filesystem operations](https://docs.python.org/3/library/os.html).

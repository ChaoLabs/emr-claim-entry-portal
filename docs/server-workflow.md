# Janus → Vesta claims POC: staged operational plan

This is a runbook and a list of unresolved contracts. The manually invoked SCP
transport is implemented; there is no installed background service. No server
credentials, private keys, clinical payloads or actual server
addresses belong in this public repository.

## Responsibilities and boundaries

| Component | Owner / host | Status |
| --- | --- | --- |
| CMS-1500 capture and reference validation | Chao / portal | Existing demo |
| 837P generation and batch metadata | Chao / Janus candidate | Integrated CLI prototype |
| Export checks, staff generation and archived download | Chao / portal | Included; generated does not mean sent |
| Returned 835 import and viewer | Chao / portal | Staff upload or CLI import; exact raw archive and claim-number matching |
| Completed 835 retrieval | Chao / approved operator machine | Explicit single-file SCP download with hash checks; live return test pending |
| Provider/member reference data in PostgreSQL | Tim / Vesta | Small dataset shown in local demo; full server load pending |
| SCP transfer and transfer audit trail | Chao / Janus and Vesta | Private-inbox transfer verified; shared 837P target supported by CLI |
| Claim server processing and 835 | Tim / Vesta | Local demo reviewed October 5; Vesta deployment and joint test pending |
| Shared handoff directories | Verbus / Vesta | `/srv/X12/837P` input and `/srv/X12/835` responses confirmed October 5 |

Vercel remains a demonstration, separate from the Janus/Vesta server pipeline.
Do not add SSH passwords or keys to Vercel, run a long-lived SCP worker there,
or assume its database is the Janus PostgreSQL database. This integration does
not provision paid services or change hosting plans.

## 1. Establish server access without changing the machine

Have the administrator rotate any password exposed in messages, provide each
server's SSH host-key fingerprint through a trusted channel, and approve the
least-privilege account and key-based authentication.
Do not disable StrictHostKeyChecking or use ssh-keyscan alone as identity proof.
Do not paste passwords into shell commands, .env files, tickets or this repo.

On each server, gather only non-secret facts:

```bash
hostname
whoami
pwd
uname -a
lsb_release -a
python3 --version
command -v uv
command -v git
command -v ssh
command -v scp
command -v tools.sh
```

The administrator requested `tools.sh` on Vesta. Check where it resolves and
what it does before executing it; its contents and side effects have not been
inspected here. No package installations, sudo, database migrations, file
deletions or service restarts are part of this inspection step.
Treat the supplied version list as reported information, not verified access.
The meeting's Ubuntu version and the later email differ; check the actual host.

## 2. Confirm the production contract before live integration

Record these decisions with Verbus and Tim:

- Janus project checkout, database location and approved filesystem outbox.
- Vesta account, SSH port, verified host key, inbox/outbox and file permissions.
- Whether the receiver watches a ready directory, a completion marker, or an API.
- Whether "one transaction" means one CLM claim, one ST/SE set or another unit.
  Initial proposal: one CLM per ST/SE per file; not yet an agreed requirement.
- Rust API URL/path, auth method, request media type/body, response format,
  timeout, status-query mechanism, idempotency key and retry contract.
- How a transferred file becomes an API request, and who owns that worker.
- 835 return path/API body, correlation with claim and service line, and
  distinction among transport errors, format acknowledgments and adjudication.
- Synthetic samples, retention, permitted log fields and authorized viewers.

Do not infer these values from the presence of `/srv/EDI` in meeting notes:
that was a sample-file location, not confirmation of a writable receiving inbox.

The initial transport POC used a private account-owned inbox. The October 5
meeting agreed to hand off fictional files through the shared
`/srv/X12/837P` directory on Vesta, with responses in `/srv/X12/835`. Use the
shared-inbox procedure in [server-transfer.md](server-transfer.md); private
transfer state remains separate. Tim will deploy and configure the consumer.
Folder-based delivery can proceed without an API endpoint. Consumer file
discovery, processing status, reference-data acceptance, and 835 correlation
still require a joint test. Any direct API integration remains a separate
contract. Directory permissions observed in this POC are for fictional tests;
agree restricted shared access before using real claims.

Tim also plans a private backend repository that can reference this portal as
a Git submodule. That addition belongs in the backend repository after access
is provided; it does not require copying Rust code into this public portal.

## 3. Prepare one fictional file on an isolated local database

After choosing a disposable development database, not the live Neon/Janus DB:

```bash
uv run python manage.py migrate
uv run python manage.py seed_sample_claims
uv run python manage.py seed_trading_partner
uv run python tools/make_test_claims.py
uv run python manage.py generate_837p --claim CLM-TEST-003 --dry-run
uv run python manage.py generate_837p --claim CLM-TEST-003
```

The helper is deliberately not part of Vercel builds and must not run against
real claim data. A dry run prints payload contents, so only use synthetic input.
Never commit generated files. Archive the original bytes securely before transfer;
do not regenerate a different file during a retry.

## 4. Implemented transfer behavior

- Use the exact file's SHA-256 as a stable transfer ID within a destination.
  An optional batch UUID links sender events to generation metadata. Never
  put names/member IDs in transport filenames or logs.
- Copy immutable bytes from an approved outbox with subprocess argument lists
  (no shell string interpolation), SSH key auth, verified host key,
  noninteractive failure, connect/overall timeouts and bounded retry backoff.
- Use a private `.part` file outside the inbox. Verify its byte count and
  SHA-256, then publish by an atomic no-overwrite hard link on the same
  filesystem. Only complete files acquire an inbox `.edi` name.
- Retries reuse the same transfer ID and payload hash. Detect already-published
  files after an uncertain network result; never blindly submit twice.
  A durable receipt prevents redelivery after a consumer moves the file.
  An interrupted publication with neither a final file nor a completed receipt
  stops with `publication_uncertain` for operator review.
- Append structured UTC audit events: ID, phase, attempt, outcome, bytes/hash,
  duration and sanitized error category. Never log raw EDI, passwords,
  patient/member names or arbitrary API error bodies.
- Separate generated, transfer-started, uploaded, checksum-verified,
  published, processing, response-received and reconciled states.
  Upload success does not set the claim or batch to adjudication "accepted".
- Logs and receipts are private and synchronized to disk. Rotation, central
  retention/access, and tamper-evidence are deployment decisions still pending;
  these local logs are not a claim of production compliance.

## 5. Retrieve and view the returned 835

Ask Tim which completed response file corresponds to the demonstration claim. The earlier handoff identified `/srv/X12/835`, but confirm current permissions and the final filename before running retrieval. The helper does not poll directories, invoke the engine, or delete remote files. It requires the existing approved SSH alias/key and a verified host key.

From the existing checkout on Janus or the operator's machine, replace the example alias and path with the confirmed values:

```bash
python3 tools/retrieve_835.py --host vesta --remote-file /confirmed/outgoing/response.835 --output-dir "$HOME/edi-return" --dry-run
python3 tools/retrieve_835.py --host vesta --remote-file /confirmed/outgoing/response.835 --output-dir "$HOME/edi-return"
```

`vesta` above is an example existing SSH configuration alias, not a hostname provisioned by this project. Optional `--identity /path/to/existing/key` and `--port` use existing access. Do not put a password into a command.

The helper compares remote fingerprints before and after download with the local SHA-256. It downloads into a private staging file, refuses conflicting output, and publishes a complete `<sha256>.835` file. The JSON result includes `local_file`; `returns.jsonl` records metadata. A checksum match establishes transfer integrity, not claim correctness or adjudication acceptance. A failed or changing remote file is not exposed as a completed response.

Then choose the import path for the intended database:

- **Hosted portal:** sign into Admin with an active staff account, open **835 responses**, and upload the returned file. This writes to the database configured for that deployment.
- **Configured local/server checkout:** run the following with the actual `local_file` path returned above:

```bash
uv run python manage.py import_835 --file /actual/path/to/returned-file.835
```

An optional `--batch YOUR_BATCH_UUID` associates an explicitly known submission batch after validating claim membership. Do not infer a batch from a reused filename. Re-importing identical content returns the existing archive; a different payload is a separate response.

The bounded importer accepts ASCII 5010 835 files up to 2 MB with one complete interchange; envelope counts and control references must agree. Larger or unsupported files require a reviewed importer extension.

In **835 responses**, review the exact claim-number match, returned claim status code, reported charges/paid amounts, service results, and adjustment codes. Unmatched claims remain visible for operator review. Downloading the original returns the archived bytes. Service results are displayed as reported; the viewer does not assume that identical procedure codes identify a unique original service line. This is a bounded response viewer, not automatic financial reconciliation, payment posting, or fraud adjudication.

Synthetic examples must be identified as synthetic during the demo. Until Tim supplies an actual output and the shared path is tested, describe the implemented return path as ready for joint testing, not as a completed live integration.

## 6. Acceptance tests before turning on a worker

1. Dry run makes no network calls and changes no transfer state.
2. Bad host key, missing key, permission failure and timeout fail closed.
3. Interrupted upload is invisible to the receiver; retry does not duplicate.
4. A corrupt file/checksum mismatch is not published; retain operator evidence for investigation.
5. Restart after publication but before the sender records success reconciles
   the existing transfer rather than resending it.
6. One fictional claim reaches Tim's agreed consumer once; correlate its 835 response and
   per-line adjustments without assuming whole-file accept/reject.
7. Two claims, invalid references, duplicate inputs and partial line-level
   outcomes have documented results agreed with Tim.

Only then schedule the server worker. Do not use a public web request to perform
SCP or long-running adjudication synchronously.

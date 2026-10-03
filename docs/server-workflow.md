# Janus → Vesta claims POC: staged operational plan

This is a runbook and a list of unresolved contracts, not an installed transfer
service. No server credentials, private keys, clinical payloads or actual server
addresses belong in this public repository.

## Responsibilities and boundaries

| Component | Owner / host | Status |
| --- | --- | --- |
| CMS-1500 capture and reference validation | Chao / portal | Existing demo |
| 837P generation and batch metadata | Chao / Janus candidate | Integrated CLI prototype |
| Read-only export checks | Portal / Vercel | Included in this integration |
| FHIR member/provider import into PostgreSQL | Tim / Janus | External work; interface not verified |
| SCP transfer and transfer audit trail | Chao / Janus and Vesta | Next implementation phase |
| Per-claim Rust API adjudication and 835 | Tim / Vesta | Endpoint/schema/auth not supplied |
| Sample files and operational requirements | Verbus | Await confirmed paths and synthetic samples |

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

## 2. Confirm the contract before implementing live transfer

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

## 4. Transfer design to implement after agreement

- Generate a stable opaque transfer ID; retain batch/control IDs and SHA-256
  internally for correlation. Do not put names/member IDs in filenames or logs.
- Copy immutable bytes from an approved outbox with subprocess argument lists
  (no shell string interpolation), SSH key auth, verified host key,
  noninteractive failure, connect/overall timeouts and bounded retry backoff.
- Use a temporary name outside the receiver's ready namespace.
  Verify remote byte count and SHA-256, then publish by an atomic rename on
  the same filesystem or the receiver's agreed completion-marker protocol.
- Retries reuse the same transfer ID and payload hash. Detect already-published
  files after an uncertain network result; never blindly submit twice.
- Append structured UTC audit events: ID, phase, attempt, outcome, bytes/hash,
  duration and sanitized error category. Never log raw EDI, passwords,
  patient/member names or arbitrary API error bodies.
- Separate generated, transfer-started, uploaded, checksum-verified,
  published, processing, response-received and reconciled states.
  Upload success does not set the claim or batch to adjudication "accepted".
- Protect and rotate local logs; agree central retention/access and
  tamper-evidence before describing the audit as production compliant.

## 5. Acceptance tests before turning on a worker

1. Dry run makes no network calls and changes no transfer state.
2. Bad host key, missing key, permission failure and timeout fail closed.
3. Interrupted upload is invisible to the receiver; retry does not duplicate.
4. Corrupt file/checksum mismatch is quarantined, not published.
5. Restart after publication but before the sender records success reconciles
   the existing transfer rather than resending it.
6. One fictional claim reaches the API once; correlate any 835 response and
   per-line adjustments without assuming whole-file accept/reject.
7. Two claims, invalid references, duplicate inputs and partial line-level
   outcomes have documented results agreed with Tim.

Only then schedule the server worker. Do not use a public web request to perform
SCP or long-running adjudication synchronously.

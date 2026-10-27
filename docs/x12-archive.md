# Generated X12 archive

The October 23 meeting requested a permanent database copy of each generated
X12 file as a single character string. `edi.X12Document` supplies that storage
while dashboard generation is being integrated. It is an ordinary retained
database table, not a PostgreSQL temporary table or a queue with an expiry.

## Storage and relationships

The new table is `edi_x12document`. Existing claim and EDI tables remain in place.

| Field | Stored value |
| --- | --- |
| `id` | UUID identifying this archived document |
| `batch_id` | Unique link to the existing `SubmissionBatch` |
| `content` | Complete final X12 file as one string, with spaces, separators, line endings, and trailing newline preserved |
| `sha256` | SHA-256 hex digest of `content.encode("utf-8")` |
| `byte_count` | Length of those UTF-8 bytes, not the number of characters |
| `created_at` | Archive creation timestamp |

The batch already contains the file name, trading partner, control numbers, and
claim count. Its `BatchClaim` rows identify the included claims in wire order.
These relationships avoid copying claim metadata into another table. The
current exporter emits one ST/SE transaction set per file, which can contain
multiple CLM claims; one archive row does not mean one claim.

The `batch` relationship uses `PROTECT`. Ordinary Django deletion of a batch
with an archive is refused. Admin allows viewing documents but not adding,
editing, or deleting them. The list shows metadata, and the detail page exposes
the stored content to authorized Admin users.

These are application controls, not WORM storage or database-level immutability.
Privileged database access or code bypassing the archive interface can change
records. A checksum detects a mismatch when the content and checksum no longer
agree; it does not prove authenticity against an operator who can change both.

## Generation and restoration

A successful `generate_837p` run writes UTF-8 bytes to its local output file and
stores the same final string in `X12Document`. The trailing newline is part of
the stored content for both the default layout and `--one-line`. The command
prints the archive UUID after the database transaction succeeds.

Batch, batch-claim, and document records commit together. If recording fails,
the transaction rolls back and the command removes the file it just created.
Reserved control numbers remain consumed. The filesystem and database are not
a distributed transaction: an abrupt process or host failure can still require
operator reconciliation. Do not configure a transfer watcher on the output
directory; transfer remains a separate manual operation.

`--dry-run` stores no batch or archive and consumes no control numbers. Existing
batches are not automatically backfilled. Regenerating from today's claim data
would not establish what an older file contained. Import of retained historical
source files would need a separate, verified process; none is implemented here.

Use the document UUID from the export output or **Admin > EDI > X12 documents**
to restore the archived file:

```bash
uv run python manage.py restore_x12 --document YOUR_DOCUMENT_UUID --out recovered.edi
```

Replace `YOUR_DOCUMENT_UUID` with the actual UUID. The command checks the stored
SHA-256 and byte count before writing, preserves exact UTF-8 bytes, uses
owner-only permissions on Unix, and refuses an existing path, including a
symlink. It does not reserve control numbers, create a new batch, or send a
file. Choose a new destination path if one already exists.

An archived document records generation, not submission, payer acceptance, or
adjudication. Restoring it does not bypass the existing SCP tool's duplicate
delivery controls. See [server transfer](server-transfer.md) for transfer
receipts and recovery procedures.

## Apply the migration

Use the existing checkout and Python environment. No new database, service, or
dependency is needed for this change. After updating the checkout to the reviewed
revision, run these commands from the project directory:

```bash
uv run python manage.py migrate --plan
uv run python manage.py migrate --noinput
uv run python manage.py showmigrations edi
uv run python manage.py check
```

The new EDI migration 0002 creates the archive table without rewriting claims or
old batches. Django uses the configured `DATABASE_URL`; without it the local
development database is SQLite. Applying a migration to a server's local SQLite
database does not apply it to Vercel's Neon PostgreSQL database. Use the intended
environment's existing configuration and normal backup procedure before changing
its database. Do not copy connection strings into source control or screenshots.

Vercel's existing build command already runs `manage.py migrate --noinput`.
Deploying the reviewed revision will therefore apply the migration to the
database connected to that deployment. Check that deployment's build log and
Admin table list; a successful local test alone does not establish that the
remote migration ran. This change does not enable dashboard generation.

## Review in an isolated development database

Run the automated checks against a development configuration:

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test claims edi --noinput
```

For a manual round trip, use a disposable development database with the
fictional trading partner and `CLM-TEST-003` fixture described in the README.
Create a fresh directory so prior files cannot be overwritten:

```bash
x12_review_dir=$(mktemp -d)
uv run python manage.py generate_837p --claim CLM-TEST-003 --out "$x12_review_dir/original.edi"
```

Copy the printed archive UUID, then run:

```bash
X12_DOCUMENT_ID='replace-with-the-printed-uuid'
uv run python manage.py restore_x12 --document "$X12_DOCUMENT_ID" --out "$x12_review_dir/restored.edi"
cmp "$x12_review_dir/original.edi" "$x12_review_dir/restored.edi"
```

An exit status of zero from `cmp` confirms byte equality. In Admin, verify the
document links to the batch, its complete content is visible, and there are no
add, edit, or delete controls. A repeat restore to the same output path must
fail without replacing the file. A dry run must leave the document count
unchanged. Do not run fictional fixture helpers against a real claims database.

## Handoff to Jason

The implemented storage entry point is:

```python
from edi.models import X12Document

document = X12Document.archive(batch=batch, content=final_text)
```

`batch` must be a saved `SubmissionBatch`; `final_text` must be the complete
serialized file, including the exact newline convention the generator intends
to write. It must be a nonempty, UTF-8-encodable string without NUL characters.
The archive does not strip whitespace, normalize segments, or append a newline.
It computes its own checksum and byte count. Repeating this call
with the same batch and identical content returns the existing document;
supplying different content for that batch raises an error. A newly generated
file, with new control numbers, should have a new batch and document.

The current CLI calls this interface inside the transaction that creates the
batch and claim membership. A later dashboard integration should use the same
transaction boundary and preserve a single final string for file output and
archival.

The following is a proposed handoff, not an agreed JSON contract or an
implemented dashboard/API endpoint:

| Boundary | Proposal to confirm with Jason |
| --- | --- |
| Generator input | Claim data read from Postgres, with explicit claim identifiers, trading partner, and an agreed versioned JSON mapping |
| Generator output | Complete X12 string plus the batch/control-number and claim-order metadata needed by the existing batch model |
| Archive result | Document UUID, batch UUID, SHA-256, and byte count for downstream correlation |
| Dashboard action | Authenticated generation that commits the batch and original payload together, with clear validation errors |

Jason and Chao still need to agree on required JSON fields, versioning,
validation/error shape, and the dashboard invocation. Rust API processing, 835
responses, and automatic file delivery remain separate integration work.

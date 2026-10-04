# EMRTS Electronic Claim Entry Portal

A Django development application for capturing, validating, reviewing, and persisting CMS-1500 professional-claim information.

## CMS-1500 implementation

The application currently includes:

- a CMS-1500-oriented claim-entry form with dynamically repeatable service lines;
- normalized patient, subscriber, payer, policy, coverage, provider, diagnosis, and service-line persistence;
- NPI, ICD-10-CM, and CPT / HCPCS reference validation;
- reference source/version/update metadata visible on the dashboard;
- claim-detail reference-match indicators and audit events;
- Django Admin maintenance for operational and reference records;
- Mermaid ERD, data-model rationale, PostgreSQL-oriented schema, fictional demo data, and automated tests.

The documented reference relationships provide stable inputs for production data loaders and ANSI X12 837P integration without changing the core claim model.

## Technology

- Python 3.12+
- Django 5
- SQLite for zero-configuration development; PostgreSQL supported through environment variables
- `uv` for dependency and command execution
- Mermaid for GitHub-rendered ERD documentation

## Install and run locally

With Git and `uv` installed, run:

```bash
git clone https://github.com/ChaoLabs/emr-claim-entry-portal.git
cd emr-claim-entry-portal
uv sync
uv run python manage.py migrate
uv run python manage.py seed_sample_claims
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

All seeded names, identifiers, and claims are fictional development data. Do not enter real PHI.

## Deploy to Vercel

Vercel deployment is optional and does not change the local SQLite workflow above. The deployed application uses PostgreSQL whenever `DATABASE_URL` is present.

1. Import this GitHub repository into Vercel.
2. Add a PostgreSQL integration such as Neon and connect it to the project so that Vercel provides `DATABASE_URL`.
3. Add `DJANGO_SECRET_KEY` with a newly generated secret and set `DJANGO_DEBUG=False` for Production and Preview.
4. Deploy the project. Vercel detects `config/wsgi.py`; the build script applies migrations and loads the idempotent fictional demo seed.

Generate a secret locally with:

```bash
uv run python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Vercel `*.vercel.app` hosts are allowed automatically. If you add a custom domain, include it in `DJANGO_ALLOWED_HOSTS`. Use an isolated or branched PostgreSQL database for Preview deployments so their migrations and demo data do not affect Production.

The hosted instance remains a development demonstration. Do not enter real PHI or production credentials into claim fields.

## EDI 837P generation

The `edi` app is an experimental exporter for saved claims, integrated from [kzzz12138/cms1500-to-837p-converter](https://github.com/kzzz12138/cms1500-to-837p-converter) at commit `6c429a78e50cb5db36e14ed038a79615d37d0576`. See [integration notes](docs/edi-integration.md) for local corrections and limitations.

It generates an X12-shaped 837P test file, not a certified payer-ready transaction. The file uses version `005010X222A1`. Generation writes a local file; it does not send anything to a payer or a clearinghouse. Claim Detail shows read-only **837P Export Readiness** checks. The separate `tools/transfer_edi.py` CLI can transfer a generated file between approved servers using SCP, checksum verification, durable receipts, and metadata-only audit logs. It is manually invoked; no scheduled worker, web download, API adjudication, or 835 return is implemented.

### Try it locally

Run these commands after the steps in "Install and run locally".

```bash
uv run python manage.py seed_trading_partner
uv run python tools/make_test_claims.py
uv run python manage.py generate_837p --claim CLM-TEST-003 --dry-run
```

`seed_trading_partner` creates a fictional trading partner named "Demo MAC Test". Its usage indicator is `T`, so every file is a test file. You can run this command again. It updates the same record.

The demo claim `CLM-DEMO-001` from `seed_sample_claims` does not pass the checks. Its billing ZIP has 5 digits and its fictional tax ID is not a nine-digit EIN. `tools/make_test_claims.py` adds two more claims. `CLM-TEST-003` passes the prototype checks. `CLM-TEST-002` fails because its payer has no payer ID.

`--dry-run` prints the file on the screen. It does not take control numbers and does not save a batch. To write a test file to disk, run the command without `--dry-run`.

```bash
uv run python manage.py generate_837p --claim CLM-TEST-003
```

The file is saved in the current folder, with owner-only permissions on Unix. Existing files are never overwritten; choose a new output path. Reserved control numbers may have gaps after a failed attempt and are not reused. The default name looks like `837p_T_000000001_20260911065214.edi`.

### Command options

| Option | What it does |
| --- | --- |
| `--partner NAME` | Uses the active trading partner with this name. You need it when more than one partner is active. |
| `--status STATUS` | Picks claims with this status. The default is `ready_for_review`. Use `--status ""` to pick claims of any status. |
| `--claim NUMBER` | Picks a claim by its claim number. You can repeat it. When you use it, `--status` is not used. |
| `--limit N` | Uses only the first N claims, ordered by creation time. N must be positive. |
| `--out PATH` | Writes the file to this path. |
| `--one-line` | Puts all segments on one line. By default each segment is on its own line. |
| `--ignore TAG` | Skips issues whose tag starts with TAG, for example `--ignore "2010AA N403"`. You can repeat it. |
| `--force` | Keeps claims that have issues. Structurally unsupported claims, including multiple coverages or ambiguous billing providers, are still left out. Investigation only; not permission to submit invalid claims. |
| `--dry-run` | Prints the file. It does not take control numbers and does not save a batch. |

### What the command does

1. It loads the claims and collects the data for each claim.
2. It checks each claim. A claim with an issue is left out, unless you use `--ignore` or `--force`.
3. If no claim passes, it stops with an error and writes nothing.
4. It builds the segments for the claims that passed.
5. It takes the next ISA13, GS06 and ST02 numbers for the trading partner.
6. It adds the ISA, GS, ST and BHT segments, the submitter and receiver loops, and the SE, GE and IEA segments.
7. It writes the file. It also saves one `SubmissionBatch` row and one `BatchClaim` row for each claim.
8. It prints a summary. The summary shows included and excluded claims (generation only, not adjudication), the segment count, SE01, the number of HL loops, and the issues grouped by tag.

### Checks before a claim is built

Each issue has a tag. The tag names the 837P loop and element, such as `2010AA N403`.

| Area | What is checked |
| --- | --- |
| Claim | The claim has exactly one primary coverage and one billing provider; COB is not implemented. The claim total equals the sum of the service line charges. |
| Billing provider (2010AA) | The ZIP has 9 digits. The NPI has 10 digits. The tax ID has 9 digits. The street, city and state are not empty. |
| Payer (2010BB) | The payer ID, street, city and state are not empty. The ZIP has 5 or 9 digits. |
| Subscriber (2000B, 2010BA) | The relationship to the patient can be turned into a code. The member ID is not empty. The date of birth, street, city, state and a 5- or 9-digit ZIP are filled in. |
| Diagnoses (2300 HI) | There is at least one diagnosis code. No code appears twice. The diagnosis order starts at 1 and has no gaps. |
| Service lines (2400) | The claim has at least one service line. Each line has a procedure code and a service date. The end date is not before the start date. Each line has at least one diagnosis pointer. Every pointer matches a diagnosis on the claim. |

### Relationship code

An explicit "relationship to patient" on Claim Coverage takes precedence. Only when it is blank does the prototype compare name, birth date and sex as a fallback. Confirm the relationship rather than relying on demographic inference.

| Text | Code |
| --- | --- |
| self | 18 |
| spouse | 01 |
| child, son, daughter | 19 |
| other | G8 |

Any other text cannot be turned into a code, so the claim fails the check. A dependent relationship is emitted in PAT01; subscriber SBR02 is blank for dependents and `18` for self.

### File layout

Each file has one interchange, one functional group and one transaction set. That transaction set can contain multiple CLM claims. For the first server POC, select **one claim per file** with `--claim`; the exact Rust API transaction boundary remains to be agreed with Tim.

The envelope is ISA/GS/ST/BHT through SE/GE/IEA. Inside are submitter (1000A), receiver (1000B), billing provider (2000A), subscriber (2000B), optional dependent patient (2000C), claim (2300) and service-line (2400) loops.

- Claims with the same billing provider share one 2000A loop.
- Compatible claims with the same subscriber, payer, policy and patient/subscriber role share one 2000B loop.
- The 2000C loop is added only when the patient is not the subscriber. When the patient is the subscriber, the 2300 loop sits directly under 2000B.
- Some segments, such as PRV, N3, N4, REF and NM1*82, are added only when the data is present.
- The element separator is `*`, the component separator is `:`, the segment end is `~`, and the repetition separator is `^`.
- Text is changed to upper case. Separator characters inside the data are replaced with spaces.
- ICD-10-CM decimal points are omitted on the wire without modifying the stored claim value.
- Amounts drop extra zeros. For example, `125.00` becomes `125` and `88.40` becomes `88.4`.

### Database tables

| Model | What it stores |
| --- | --- |
| `TradingPartner` | The ISA and GS sender and receiver IDs, the usage indicator (`T` or `P`), and the names and IDs for the submitter and receiver loops. |
| `ControlNumber` | The last ISA13, GS06 and ST02 number used for each trading partner. Each real run adds 1 to each number. |
| `SubmissionBatch` | One row for each generated file. It keeps the file name, control numbers, claim count, segment count and total charge. A new batch has the status `generated`. |
| `BatchClaim` | One row for each claim in a batch, with its position in the file. |

Trading partners can be maintained in Django Admin. Control numbers, batches and batch-claim snapshots are view-only there; generated history cannot be manually relabeled as payer acceptance through Admin. This is operational history, not a complete tamper-proof audit system.

### Helper scripts

| Script | What it does |
| --- | --- |
| `tools/make_test_claims.py` | Adds the fictional claims `CLM-TEST-002` and `CLM-TEST-003`. Use `--remove` to delete them. Claim numbers must be unique, so run `--remove` before you add them again. |
| `tools/export_claims_csv.py` | Writes one CSV row for each service line. The column names follow the 837P elements. Each row has a ready flag and a list of issues. The default output file is `claims_837p_export.csv`. |
| `tools/build_837p_body.py` | Prints the loops from 2000A down. It does not add the envelope, BHT, or the submitter and receiver loops. It does not take control numbers. |
| `tools/test_segments.py` | Compatibility entry point for the isolated Django EDI test suite; no pre-existing demo database required. |

Run a script with `uv run python`, for example `uv run python tools/export_claims_csv.py`.

No upstream `sample/` folder was present at the imported revision. Generated EDI, CSV exports, credentials and server data must not be committed. Never run the fictional-data creation/removal helper against a real claims database.

## Verify

```bash
uv run python manage.py makemigrations --check
uv run python manage.py check
uv run python manage.py test claims edi
```

The workflow tests cover dashboard/detail rendering, dynamic capture of more than six service lines, charge aggregation, successful reference-linked claim capture, rejection of unknown reference values, and validation of CMS-1500 diagnosis pointers.

## Database documentation

- [EDI export ERD](docs/database/edi-erd.md)
- [Janus/Vesta phased workflow](docs/server-workflow.md)
- [SCP transfer setup, commands, and recovery](docs/server-transfer.md)
- [Final CMS-1500 ERD](docs/database/cms1500-erd.md)
- [Data model and design rationale](docs/database/cms1500-data-model.md)
- [PostgreSQL-oriented schema](docs/database/schema.sql)

## Reference-data design

The demo seed loads a tiny, clearly labeled development subset. Production loaders can use official CMS source files without changing the claim schema:

- [NPPES downloadable files](https://download.cms.gov/nppes/NPI_Files.html)
- [ICD-10 files](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- [HCPCS quarterly updates](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update)

Full CPT content requires an appropriately licensed source.

# EDI integration provenance and scope

## Source

Integrated the EDI additions from
[kzzz12138/cms1500-to-837p-converter](https://github.com/kzzz12138/cms1500-to-837p-converter/tree/6c429a78e50cb5db36e14ed038a79615d37d0576),
commit `6c429a78e50cb5db36e14ed038a79615d37d0576`.
The upstream contributors retain authorship of the imported code; this integration
does not relicense it. No license file was present at the compared revision.

Compared with portal commit `38372b8409b7c2e60ce580736efa8e65aafab682`:

| Area | Difference |
| --- | --- |
| Claims model, migrations, forms, views, tests, templates | Identical upstream baseline |
| Python dependencies, lockfile, Vercel build configuration | Identical |
| EDI app | New builders, serializers, validators, envelope, commands and four models |
| Helper scripts | Body preview, CSV export, fictional claim fixtures, segment tests |
| Documentation/settings | New EDI ERD and README section; register the EDI app |

No claims tables or existing migrations were replaced. EDI migration 0001 adds
TradingPartner, ControlNumber, SubmissionBatch and BatchClaim. The existing
Vercel build applies migrations; it does not generate/send EDI or seed a real partner.

The October 23 archive addition introduces one further table, `edi_x12document`,
through EDI migration 0002. It retains the complete generated X12 file as one
string linked to its existing batch. The original import comparison above
describes the earlier integration, not the current table count.

## Integration corrections

- Retain 4–9 digit transaction control numbers instead of truncating at 9999.
  Fail on counter exhaustion instead of recycling old numbers.
- Store batch claim positions in actual CLM wire order.
- Normalize ICD-10-CM dots only in exported codes; preserve snapshots.
- Respect explicit relationships; use PAT01 for dependent relationships and
  blank 2000B SBR02 for dependents. Separate self/dependent subscriber groups.
- Emit group name only when no group number is present.
- Refuse unsupported COB and ambiguous claim-level provider assignments rather
  than silently choosing a record.
- Add basic subscriber-address, units, tax-ID and claim-ID checks.
- Never overwrite an existing EDI file. New Unix files have mode 0600.
  If batch recording fails, roll back records and remove the newly created file.
  Counter reservations remain consumed. This is NOT a distributed transaction:
  process/host failure may still require reconciliation before any transfer.
- Move the original segment tests to isolated Django tests, preserving the
  old helper entry point. Add envelope, command, failure-path, batch-order,
  context, read-only Admin and UI tests.
- Add Claim Detail export checks. The November workflow adds authenticated staff generation/download, while actual transfer remains separate.
- Make generated records view-only in Admin. This does not make database history
  immutable against privileged operators.
- Archive the exact final UTF-8 file contents, including its trailing newline,
  alongside batch records in the same database transaction. Retain SHA-256 and
  byte count for integrity checks. Identical archive retries reuse the same row;
  a different payload for that batch is rejected. Archive records are view-only
  in Admin and protect their batch from ordinary ORM deletion.
- Restore archived files with `restore_x12` rather than regenerating historical
  content from changed claim records. See [X12 archive](x12-archive.md) for the
  storage contract, migration, and review procedure.

## Important limits

This is a prototype, not certified X12 validation or a payer integration.
Passing reference checks on the capture form does not mean all export fields
are complete. Passing export checks does not mean coverage is active, a claim
is clinically valid, a payer accepted it, or money was paid.

The exporter supports one primary coverage per claim. It has no 2320/2330 COB,
999/277CA handling, payer companion-guide certification, Rust API client,
FHIR import, or full financial reconciliation. Staff generation/download, exact
payload storage, manually invoked SCP transport, completed-835 retrieval, and
835 import/viewing are implemented. Archiving a file is not evidence of transfer
or payer acceptance; transport receipts remain separate. A JSON generator
interface with Jason and live engine integration remain to be agreed.
Some source defaults (such as signature/assignment codes and demographic
relationship inference) still require business-rule review.
The development reference subset is not an authoritative production dataset.
`--force` and `--ignore` are diagnostic escape hatches, not submission options.

One file currently has one ST/SE transaction set, potentially containing multiple
CLM claims. Do not call a multi-claim file a single adjudication request. Use
`--claim CLM-TEST-003` for the first fictional single-claim trial, and confirm
Tim's input contract before adding a splitter or API client.

## November relationship and return changes

`ServiceLineDiagnosis` and `ServiceLineModifier` replace fixed scalar columns. The capture model can retain more than four entries, while the current `005010X222A1` encoder rejects more than four pointers/modifiers per line or more than twelve claim diagnoses. The serializer guard also applies when diagnostic CLI flags skip ordinary readiness checks; overflow is never silently dropped.

Returned 835 files are archived independently of submitted 837P documents. The bounded importer checks the supported envelope and transaction structure and stores exact text. The viewer displays reported CLP/SVC/CAS amounts; it is not a full X12 compliance validator, fraud finding, or proof of settled payment. It links claims by exact CLP01/claim-number match and leaves unmatched results visible. Tim's actual sample and the approved handoff contract still need a joint test.

## Reference checks used in this integration

- [X12 diagnosis count and service-line pointers, RFI 1882](https://x12.org/resources/requests-for-interpretation/rfi-1882-icd10-837)
- [X12 duplicate diagnosis pointers, RFI 1366](https://x12.org/resources/requests-for-interpretation/rfi-1366-sv107-duplicate-pointers)
- [CMS claim-field instructions and modifiers](https://www.cms.gov/outreach-and-education/mln/wbt/mln4462429-mln-wbt-1500/1500/lesson05/04/index.html)
- [X12 ST02 uniqueness interpretation for 5010 837](https://x12.org/resources/requests-for-interpretation/rfi-1139-st02-tr-control-number)
- [CMS 837P companion guide](https://www.cms.gov/Medicare/Billing/ElectronicBillingEDITrans/downloads/5010A1837BCG.pdf)
- [Health Net 837P companion guide, SBR02](https://www.healthnetoregon.com/content/dam/centene/healthnet/pdfs/provider/or/837_professional_encounters_guide.pdf)
- [UniCare 837P companion document, diagnosis decimal handling](https://www.provider.unicare.com/docs/gpp/WV-CAID-resources-training-837p-health-care-claim-training-guide.pdf?v=202212202200)

These publicly available examples are not substitutes for the applicable X12
TR3, the receiving partner's contract, or a full compliance assessment.

## Verification

Run with a local development database; tests use a separate disposable test DB:

```bash
uv sync --locked
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test claims edi --noinput
```

Also verify upgrades from the existing claims-only schema in a disposable local
SQLite database. Production PostgreSQL migrations must be checked in the real
deployment logs; a local SQLite test does not prove remote deployment success.

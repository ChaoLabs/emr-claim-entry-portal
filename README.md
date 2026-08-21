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

## Run locally

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py seed_sample_claims
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

All seeded names, identifiers, and claims are fictional development data. Do not enter real PHI.

## Verify

```bash
uv run python manage.py makemigrations --check
uv run python manage.py check
uv run python manage.py test claims
```

The workflow tests cover dashboard/detail rendering, dynamic capture of more than six service lines, charge aggregation, successful reference-linked claim capture, rejection of unknown reference values, and validation of CMS-1500 diagnosis pointers.

## Database documentation

- [Final CMS-1500 ERD](docs/database/cms1500-erd.md)
- [Data model and design rationale](docs/database/cms1500-data-model.md)
- [PostgreSQL-oriented schema](docs/database/schema.sql)

## Reference-data design

The demo seed loads a tiny, clearly labeled development subset. Production loaders can use official CMS source files without changing the claim schema:

- [NPPES downloadable files](https://download.cms.gov/nppes/NPI_Files.html)
- [ICD-10 files](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- [HCPCS quarterly updates](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update)

Full CPT content requires an appropriately licensed source.

# EDI export and response records

## Generated files

```mermaid
erDiagram
    TRADING_PARTNER ||--o{ CONTROL_NUMBER : maintains
    TRADING_PARTNER ||--o{ SUBMISSION_BATCH : generates
    SUBMISSION_BATCH ||--o{ BATCH_CLAIM : contains
    SUBMISSION_BATCH ||--o| X12_DOCUMENT : archives

    TRADING_PARTNER {
        uuid id PK
        string name UK
        boolean is_active
        string isa_sender_qualifier
        string isa_sender_id
        string isa_receiver_qualifier
        string isa_receiver_id
        string usage_indicator
        string gs_sender_code
        string gs_receiver_code
        string submitter_name
        string submitter_id
        string submitter_contact_name
        string submitter_contact_phone
        string receiver_name
        string receiver_id
        datetime created_at
        datetime updated_at
    }

    CONTROL_NUMBER {
        bigint id PK
        uuid trading_partner_id FK
        string level
        integer current_value
        datetime created_at
        datetime updated_at
    }

    SUBMISSION_BATCH {
        uuid id PK
        uuid trading_partner_id FK
        string file_name
        string isa_control_number
        string gs_control_number
        string st_control_number
        integer claim_count
        integer segment_count
        decimal total_charge_amount
        string status
        text notes
        datetime created_at
        datetime updated_at
    }

    BATCH_CLAIM {
        bigint id PK
        uuid batch_id FK
        uuid claim_id
        string claim_number
        integer position
        datetime created_at
        datetime updated_at
    }

    X12_DOCUMENT {
        uuid id PK
        uuid batch_id FK,UK
        text content
        string sha256
        bigint byte_count
        datetime created_at
    }
```

`X12Document` maps to `edi_x12document`. It stores the entire generated file as
one string, including its final newline, with a SHA-256 checksum and UTF-8 byte
count. One archived file can contain multiple claims; `BatchClaim` records the
claim membership and wire order.

The document is optional in this diagram because batches created before the
archive migration remain unchanged. Every successful non-dry-run export through
the updated command creates one document. The one-to-one constraint prevents
duplicate archive rows for a batch, and its `PROTECT` relationship blocks ordinary
ORM deletion of an archived batch. No automatic expiry or historical backfill is
implemented. See [archive behavior and review](../x12-archive.md).

## Returned 835 files

```mermaid
erDiagram
    SUBMISSION_BATCH o|--o{ REMITTANCE_DOCUMENT : "optional provenance"
    REMITTANCE_DOCUMENT ||--o{ REMITTANCE_CLAIM : contains
    CLAIM o|--o{ REMITTANCE_CLAIM : "exact number match"

    REMITTANCE_DOCUMENT {
        uuid id PK
        uuid batch_id FK
        text content
        string sha256 UK
        bigint byte_count
        string source_name
        string imported_by
        datetime imported_at
        json summary
    }

    REMITTANCE_CLAIM {
        bigint id PK
        uuid document_id FK
        uuid claim_id FK
        int position
        string claim_number
        string status_code
        string payer_control_number
        decimal charge_amount
        decimal paid_amount
        decimal patient_responsibility
        json details
    }
```

`RemittanceDocument` retains the exact imported ASCII 835 text and integrity metadata. A duplicate SHA-256 reuses the existing receipt rather than creating duplicate claim results. `RemittanceClaim` stores each CLP result in file order. Its optional claim link uses an exact claim-number match; an unmatched number remains visible for review. The original CLP number remains even if a linked claim is later removed.

The bounded viewer retains service-level SVC/CAS data and financial values in `details`; it does not guess service-line identity from procedure codes or positions. An operator may supply a submission-batch UUID as provenance only when the importer verifies the claim membership. The 835 and the original 837P have separate immutable document records; importing a response never rewrites the submitted X12 or marks a batch paid/accepted.

Application-level read-only controls do not make these tables tamper-proof against direct SQL. Staff login is required for import, viewing, and download. See [server workflow](../server-workflow.md) for retrieval and review.

# CMS-1500 Capture ERD

This document provides the initial Mermaid ERD for the CMS-1500 claim capture database design.

The current schema direction uses UUID primary keys for internal database identity. Business identifiers such as NPI numbers, payer identifiers, ICD-10 codes, CPT codes, and HCPCS codes are stored as data fields rather than primary keys.

## Entity Relationship Diagram

```mermaid
erDiagram
    PATIENTS ||--o{ CLAIMS : has
    INSURED_PARTIES ||--o{ CLAIMS : covers
    PAYERS ||--o{ CLAIMS : receives
    CLAIMS ||--o{ CLAIM_PROVIDERS : includes
    PROVIDERS ||--o{ CLAIM_PROVIDERS : participates
    CLAIMS ||--o{ CLAIM_DIAGNOSES : contains
    CLAIMS ||--o{ SERVICE_LINES : contains
    CLAIMS ||--o{ CLAIM_AUDIT_EVENTS : tracks

    PATIENTS {
        uuid id PK
        string first_name
        string middle_name
        string last_name
        date date_of_birth
        string sex
        string address_line_1
        string address_line_2
        string city
        string state
        string zip_code
        string phone_number
        datetime created_at
        datetime updated_at
    }

    INSURED_PARTIES {
        uuid id PK
        string first_name
        string middle_name
        string last_name
        date date_of_birth
        string sex
        string relationship_to_patient
        string insured_id_number
        string group_number
        string address_line_1
        string address_line_2
        string city
        string state
        string zip_code
        datetime created_at
        datetime updated_at
    }

    PAYERS {
        uuid id PK
        string payer_name
        string payer_type
        string payer_identifier
        string medicare_administrative_contractor
        datetime created_at
        datetime updated_at
    }

    PROVIDERS {
        uuid id PK
        string organization_name
        string first_name
        string last_name
        string npi
        string taxonomy_code
        string tax_id
        string address_line_1
        string address_line_2
        string city
        string state
        string zip_code
        string phone_number
        datetime created_at
        datetime updated_at
    }

    CLAIMS {
        uuid id PK
        string claim_number
        uuid patient_id FK
        uuid insured_party_id FK
        uuid payer_id FK
        string status
        string validation_status
        text validation_message
        date service_start_date
        date service_end_date
        decimal total_charge_amount
        datetime submitted_at
        datetime created_at
        datetime updated_at
    }

    CLAIM_PROVIDERS {
        uuid id PK
        uuid claim_id FK
        uuid provider_id FK
        string provider_role
        datetime created_at
        datetime updated_at
    }

    CLAIM_DIAGNOSES {
        uuid id PK
        uuid claim_id FK
        string diagnosis_code
        integer diagnosis_order
        string description
        datetime created_at
        datetime updated_at
    }

    SERVICE_LINES {
        uuid id PK
        uuid claim_id FK
        date service_from_date
        date service_to_date
        string place_of_service
        string procedure_code
        string modifier_1
        string modifier_2
        string modifier_3
        string modifier_4
        integer diagnosis_pointer_1
        integer diagnosis_pointer_2
        integer diagnosis_pointer_3
        integer diagnosis_pointer_4
        decimal charge_amount
        integer units
        datetime created_at
        datetime updated_at
    }

    CLAIM_AUDIT_EVENTS {
        uuid id PK
        uuid claim_id FK
        string event_type
        text event_description
        string changed_by
        datetime created_at
    }
```

## Design Notes

- A claim belongs to one patient, one insured party, and one payer.
- A claim can include multiple providers through claim_providers.
- A claim can include multiple ICD-10 diagnosis codes.
- A claim can include multiple CMS-1500 service lines.
- Service lines include diagnosis pointers so procedures can be linked back to diagnosis entries.
- Claim audit events support traceability during claim creation, editing, validation, and future submission workflows.
- This ERD is an initial design and may be refined after mentor feedback or implementation testing.

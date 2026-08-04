# CMS-1500 Claim Capture ERD

The following ERD shows the current normalized database design for CMS-1500 professional claim capture.

```mermaid
erDiagram
    PATIENTS ||--o{ CLAIMS : "receives services for"

    INSURED_PARTIES ||--o{ INSURANCE_POLICIES : "holds"
    PAYERS ||--o{ INSURANCE_POLICIES : "issues"

    CLAIMS ||--o{ CLAIM_COVERAGES : "uses"
    INSURANCE_POLICIES ||--o{ CLAIM_COVERAGES : "applies to"

    CLAIMS ||--o{ CLAIM_PROVIDERS : "has"
    PROVIDERS ||--o{ CLAIM_PROVIDERS : "serves as"

    CLAIMS ||--o{ CLAIM_DIAGNOSES : "has"
    CLAIMS ||--o{ SERVICE_LINES : "has"
    CLAIMS ||--o{ CLAIM_AUDIT_EVENTS : "tracks"

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
    }

    INSURED_PARTIES {
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
    }

    PAYERS {
        uuid id PK
        string payer_name
        string payer_type
        string payer_identifier
        string medicare_administrative_contractor
    }

    INSURANCE_POLICIES {
        uuid id PK
        uuid insured_party_id FK
        uuid payer_id FK
        string member_id
        string group_number
        string plan_name
        string policy_type
        date effective_start_date
        date effective_end_date
        boolean is_active
    }

    CLAIMS {
        uuid id PK
        string claim_number
        uuid patient_id FK
        string status
        string validation_status
        text validation_message
        date service_start_date
        date service_end_date
        decimal total_charge_amount
        datetime submitted_at
    }

    CLAIM_COVERAGES {
        uuid id PK
        uuid claim_id FK
        uuid insurance_policy_id FK
        string payer_sequence
        string relationship_to_patient
        boolean assignment_of_benefits
        boolean release_of_information
        string prior_authorization_number
        decimal other_payer_paid_amount
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
    }

    CLAIM_PROVIDERS {
        uuid id PK
        uuid claim_id FK
        uuid provider_id FK
        string provider_role
    }

    CLAIM_DIAGNOSES {
        uuid id PK
        uuid claim_id FK
        string diagnosis_code
        int diagnosis_order
        string description
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
        int diagnosis_pointer_1
        int diagnosis_pointer_2
        int diagnosis_pointer_3
        int diagnosis_pointer_4
        decimal charge_amount
        int units
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

## Key Relationship Update

The insurance relationship is modeled through two tables:

```text
InsuredParty -> InsurancePolicy <- Payer
Claim -> ClaimCoverage -> InsurancePolicy
```

This avoids forcing a claim to have only one direct payer and allows future support for primary, secondary, and tertiary coverage.

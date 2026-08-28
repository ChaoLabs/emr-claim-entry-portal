# CMS-1500 Claim Capture ERD

This logical data model combines normalized CMS-1500 claim and coverage records with focused reference entities for NPI, ICD-10-CM, and CPT / HCPCS validation.

## ERD

```mermaid
erDiagram
    PATIENTS ||--o{ CLAIMS : "is subject of"
    INSURED_PARTIES ||--o{ INSURANCE_POLICIES : holds
    PAYERS ||--o{ INSURANCE_POLICIES : issues
    CLAIMS ||--o{ CLAIM_COVERAGES : uses
    INSURANCE_POLICIES ||--o{ CLAIM_COVERAGES : "covers through"

    CLAIMS ||--o{ CLAIM_PROVIDERS : assigns
    PROVIDERS ||--o{ CLAIM_PROVIDERS : "serves in role"
    CLAIMS ||--o{ CLAIM_DIAGNOSES : contains
    CLAIMS ||--o{ SERVICE_LINES : contains
    PROVIDERS o|--o{ SERVICE_LINES : renders
    CLAIMS ||--o{ CLAIM_AUDIT_EVENTS : records

    REFERENCE_DATA_UPDATES o|--o{ NPI_REFERENCES : loads
    REFERENCE_DATA_UPDATES o|--o{ ICD10_CODES : loads
    REFERENCE_DATA_UPDATES o|--o{ PROCEDURE_CODES : loads
    NPI_REFERENCES o|--o{ PROVIDERS : validates
    ICD10_CODES o|--o{ CLAIM_DIAGNOSES : validates
    PROCEDURE_CODES o|--o{ SERVICE_LINES : validates

    PATIENTS {
        uuid id PK
        string first_name
        string last_name
        date date_of_birth
        string sex
        string address
        string phone_number
    }

    INSURED_PARTIES {
        uuid id PK
        string first_name
        string last_name
        date date_of_birth
        string sex
        string address
    }

    PAYERS {
        uuid id PK
        string payer_name
        string payer_type
        string payer_identifier
        string mac
        string address_line_1
        string address_line_2
        string city
        string state
        string zip_code
        string zip_code_extension
    }

    INSURANCE_POLICIES {
        uuid id PK
        uuid insured_party_id FK
        uuid payer_id FK
        string member_id
        string group_number
        string plan_name
        string policy_type
        date effective_dates
        boolean is_active
    }

    CLAIMS {
        uuid id PK
        uuid patient_id FK
        string claim_number UK
        string status
        string validation_status
        date service_dates
        decimal total_charge_amount
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
    }

    PROVIDERS {
        uuid id PK
        string npi_snapshot
        string npi_reference_id FK
        string provider_name
        string taxonomy_code
        string tax_id
        string address
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
        string diagnosis_code_snapshot
        string icd10_reference_id FK
        int diagnosis_order
        string description
    }

    SERVICE_LINES {
        uuid id PK
        uuid claim_id FK
        uuid rendering_provider_id FK
        string procedure_code_snapshot
        string procedure_reference_id FK
        date service_dates
        string place_of_service
        string modifier_1
        string modifier_2
        string modifier_3
        string modifier_4
        int diagnosis_pointers
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

    REFERENCE_DATA_UPDATES {
        uuid id PK
        string dataset_name
        string source_name
        string source_version
        string status
        int records_loaded
        datetime started_at
        datetime completed_at
        string triggered_by
    }

    NPI_REFERENCES {
        string npi PK
        string entity_type
        string provider_name
        string primary_taxonomy_code
        string location
        date deactivation_date
        boolean is_active
        uuid source_update_id FK
    }

    ICD10_CODES {
        string code PK
        string short_description
        text long_description
        date effective_dates
        boolean is_active
        uuid source_update_id FK
    }

    PROCEDURE_CODES {
        string code PK
        string code_system
        string short_description
        text long_description
        date effective_dates
        boolean is_active
        uuid source_update_id FK
    }
```

## How to read the design

The model has three clear areas:

1. **Reusable identity and coverage:** `patients`, `insured_parties`, `payers`, and `insurance_policies` can be maintained before a claim is entered.
2. **CMS-1500 transaction capture:** `claims` is the aggregate root; coverage, provider roles, diagnoses, service lines, and audit events belong to it.
3. **Reference validation:** three focused code tables validate claim-time values, while one shared update table records source, version, count, status, and timestamps.

## Important modeling decisions

- The original `npi`, `diagnosis_code`, and `procedure_code` strings remain on transactional rows as **claim-time snapshots**. Nullable reference keys add validation and descriptions without rewriting history when an external code set changes.
- A claim can own any number of service-line records. The web capture workflow adds lines dynamically instead of enforcing the paper form's six-line layout limit.
- `service_lines.rendering_provider_id` is a direct relationship because rendering provider information is service-line context (CMS-1500 Item 24J).
- The four diagnosis-pointer columns are retained because they directly represent CMS-1500 Item 24E's bounded positions 1–4. A separate join table would add complexity without improving this bounded relationship.
- `claim_coverages` separates a claim from a reusable insurance policy and supports primary, secondary, and tertiary coverage without duplicating subscriber and payer data.

## Extension points

`reference_data_updates` provides a clean integration point for scheduled downloads and bulk loaders. The normalized claim aggregate provides the structured source needed for 837P transformation, transmission tracking, and acknowledgement processing as those workflows are introduced.

## Official source context

- [CMS Medicare Claims Processing Manual, Chapter 26](https://www.cms.gov/regulations-and-guidance/guidance/manuals/internet-only-manuals-ioms-items/cms018912)
- [CMS NPPES downloadable files](https://download.cms.gov/nppes/NPI_Files.html)
- [CMS ICD-10 files](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- [CMS HCPCS quarterly updates](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update)

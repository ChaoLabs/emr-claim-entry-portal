# CMS-1500 Claim Data Model

This document describes the current normalized database design for the CMS-1500 claim capture portion of the Electronic Claim Entry Portal.

The design intentionally separates patient identity, insured/subscriber identity, payer identity, insurance policy information, claim coverage, providers, diagnoses, service lines, and audit events.

## Core Design Principle

The project originally used a simple structure where a claim directly referenced one insured party and one payer.

After further review, the design was updated because real healthcare claim processing is more complex:

- One insured party can have multiple insurance policies.
- One payer can cover many insured parties through different policies.
- One claim can involve multiple coverage records, such as primary, secondary, or tertiary coverage.
- Member ID and group number belong to a specific insurance policy, not directly to the insured person.
- Relationship to patient belongs to the claim coverage context, not directly to the insured person.

The updated structure is:

```text
InsuredParty -> InsurancePolicy <- Payer
Claim -> ClaimCoverage -> InsurancePolicy
```

This supports real-world insurance relationships and better prepares the system for future ANSI X12 837P generation.

## Main Tables

| Table | Purpose |
|---|---|
| patients | Stores patient demographic information. |
| insured_parties | Stores subscriber / insured person demographic information. |
| payers | Stores payer or insurance company information. |
| insurance_policies | Connects an insured party to a payer through a specific policy or coverage record. |
| claims | Stores the main claim header, status, patient, dates, total charge, and workflow metadata. |
| claim_coverages | Connects a claim to one or more insurance policies and stores payer sequence information. |
| providers | Stores billing, rendering, referring, and facility provider information. |
| claim_providers | Connects providers to a claim by role. |
| claim_diagnoses | Stores diagnosis codes associated with a claim. |
| service_lines | Stores professional service line information. |
| claim_audit_events | Stores claim workflow and audit events. |

## Table Details

### patients

Stores the person receiving the healthcare service.

Important fields:

- id
- first_name
- middle_name
- last_name
- date_of_birth
- sex
- address fields
- phone_number

### insured_parties

Stores the subscriber or insured person. This may be the patient, a parent, spouse, guardian, or another covered person.

Important fields:

- id
- first_name
- middle_name
- last_name
- date_of_birth
- sex
- address fields

Insurance-specific fields are intentionally not stored here.

### payers

Stores payer-level information.

Important fields:

- id
- payer_name
- payer_type
- payer_identifier
- medicare_administrative_contractor

### insurance_policies

Represents a real insurance relationship between an insured party and a payer.

Important fields:

- id
- insured_party_id
- payer_id
- member_id
- group_number
- plan_name
- policy_type
- effective_start_date
- effective_end_date
- is_active

This table resolves the many-to-many relationship between insured parties and payers.

### claims

Stores the main claim header.

Important fields:

- id
- claim_number
- patient_id
- status
- validation_status
- validation_message
- service_start_date
- service_end_date
- total_charge_amount
- submitted_at

The claim does not directly store payer_id or insured_party_id. Coverage information is represented through claim_coverages.

### claim_coverages

Connects a claim to an insurance policy.

Important fields:

- id
- claim_id
- insurance_policy_id
- payer_sequence
- relationship_to_patient
- assignment_of_benefits
- release_of_information
- prior_authorization_number
- other_payer_paid_amount

This table supports primary, secondary, tertiary, and other payer sequences.

### providers

Stores provider information.

Important fields:

- id
- organization_name
- first_name
- last_name
- npi
- taxonomy_code
- tax_id
- address fields
- phone_number

### claim_providers

Connects providers to claims by role.

Supported roles:

- billing
- rendering
- referring
- facility

### claim_diagnoses

Stores diagnosis codes for a claim.

Important fields:

- id
- claim_id
- diagnosis_code
- diagnosis_order
- description

### service_lines

Stores professional service line details.

Important fields:

- id
- claim_id
- service_from_date
- service_to_date
- place_of_service
- procedure_code
- modifiers
- diagnosis pointers
- charge_amount
- units

### claim_audit_events

Stores workflow and audit information.

Important fields:

- id
- claim_id
- event_type
- event_description
- changed_by
- created_at

## Design Rationale

This schema keeps identity, insurance, claim, and workflow data separated.

The most important update is the introduction of insurance_policies and claim_coverages. These two tables allow the system to model realistic insurance scenarios, including multiple policies per insured party and multiple coverages per claim.

This design is also more suitable for future ANSI X12 837P generation because payer sequence, subscriber information, member ID, group number, provider roles, diagnosis codes, and service lines are stored in normalized locations.

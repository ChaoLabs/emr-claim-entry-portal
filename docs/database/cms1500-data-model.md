# CMS-1500 Capture Data Model

This document defines the initial database design direction for capturing CMS-1500 professional claim information in the EMRTS Electronic Claim Entry & Submission Portal.

The current assignment focuses on capturing CMS-1500 information through a web interface and storing the structured data in PostgreSQL. The design should also remain compatible with future ANSI X12 837P generation and Medicare/MAC transmission.

## Design Goals

- Capture the major CMS-1500 information groups in a structured relational database.
- Keep patient, insured, provider, diagnosis, and service-line data separate enough for validation and future mapping.
- Preserve the entered claim information for review, correction, audit, and future resubmission workflows.
- Prepare the schema for future ANSI X12 837P conversion without implementing the converter in this phase.
- Avoid storing real PHI in development or sample data.

## Core Data Groups

| Data Group | Purpose |
| --- | --- |
| Claim | Main claim record, status, payer type, dates, totals, and workflow metadata. |
| Patient | Patient demographic information captured from the CMS-1500 form. |
| Insured / Subscriber | Insurance subscriber information, which may be the patient or another person. |
| Provider | Billing, rendering, referring, or facility provider information. |
| Diagnosis | ICD-10 diagnosis codes associated with the claim. |
| Service Line | CPT/HCPCS service lines, modifiers, charges, units, and diagnosis pointers. |
| Payer | Medicare or other payer information needed for claim routing. |
| Audit Event | Record of claim creation, edits, validation, submission preparation, and status changes. |

## Proposed Initial Tables

| Table | Description |
| --- | --- |
| claims | Main claim header table. Stores claim status, payer, patient relationship, dates, total charge amount, and workflow fields. |
| patients | Stores patient demographic fields such as name, date of birth, sex, address, and contact information. |
| insured_parties | Stores subscriber or insured information for the claim. |
| payers | Stores payer information such as payer name, payer type, and payer identifier. |
| providers | Stores provider records such as name, NPI, taxonomy code, address, and provider role information. |
| claim_providers | Links a claim to one or more providers, such as billing provider, rendering provider, referring provider, or service facility. |
| claim_diagnoses | Stores diagnosis codes for a claim, including ordering and ICD-10 code values. |
| service_lines | Stores individual CMS-1500 service lines, including procedure code, modifiers, dates of service, charge amount, units, place of service, and diagnosis pointers. |
| claim_audit_events | Stores audit history for claim creation, editing, validation, and future submission-related events. |

## Important Field Categories

| Category | Example Fields |
| --- | --- |
| Claim header | claim_number, status, payer_id, patient_id, insured_party_id, date_created, total_charge_amount |
| Patient information | first_name, last_name, middle_name, date_of_birth, sex, address_line_1, city, state, zip_code, phone_number |
| Insured information | relationship_to_patient, insured_id_number, group_number, first_name, last_name, date_of_birth, address |
| Provider information | provider_role, organization_name, first_name, last_name, npi, taxonomy_code, tax_id, address |
| Diagnosis information | diagnosis_code, diagnosis_order, description |
| Service line information | service_from_date, service_to_date, place_of_service, procedure_code, modifier_1, modifier_2, modifier_3, modifier_4, diagnosis_pointer_1, diagnosis_pointer_2, charge_amount, units |
| Workflow information | status, validation_status, validation_message, created_at, updated_at, submitted_at |
| Audit information | event_type, event_description, changed_by, created_at |

## Claim Status Direction

| Status | Meaning |
| --- | --- |
| draft | Claim has been started but is not ready for validation or submission. |
| ready_for_review | Claim capture is complete enough for internal review. |
| validation_failed | Claim failed local validation and needs correction. |
| ready_for_837p | Claim has passed the capture-stage checks and can later be mapped to ANSI X12 837P. |
| submitted | Future status after transmission is implemented. |
| accepted | Future status after payer acknowledgment is implemented. |
| rejected | Future status after payer rejection is implemented. |
| paid | Future status after remittance processing is implemented. |
| denied | Future status after denial information is available. |

## Design Notes

- UUID primary keys should be used for internal database identity.
- Real-world identifiers such as NPI numbers, payer identifiers, ICD-10 codes, CPT codes, and HCPCS codes should be stored as business data fields, not internal primary keys.
- The current phase should focus on claim capture and database design rather than full EDI transaction generation.
- The database should support multiple diagnosis codes and multiple service lines per claim.
- Service lines should support diagnosis pointers because CMS-1500 and 837P workflows link procedures to diagnosis codes.
- The schema should include audit fields because healthcare claim workflows require traceability.
- Development sample data should use fictional patients and fictional claim examples only.

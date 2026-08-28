# CMS-1500 Claim Data Model

## Design goals

This schema supports entry, validation, review, and persistence of CMS-1500 professional-claim data.

Its normalized relationships also provide stable inputs for reference-file automation and ANSI X12 837P integration while keeping claim-capture responsibilities cohesive.

## Table inventory

The final model contains the 11 operational tables already justified by claim capture plus 4 focused reference-data tables.

| Area | Table | Responsibility |
|---|---|---|
| Party | `patients` | Person receiving the service. |
| Party | `insured_parties` | Subscriber or insured person; may differ from the patient. |
| Coverage | `payers` | Reusable insurance-company / payer identity and mailing address. |
| Coverage | `insurance_policies` | Connects an insured party to a payer with member, group, plan, dates, and status. |
| Claim | `claims` | Aggregate root for CMS-1500 capture and review. |
| Claim | `claim_coverages` | Applies one or more policies to a claim by payer sequence. |
| Provider | `providers` | Claim-time billing, rendering, referring, or facility provider data. |
| Provider | `claim_providers` | Assigns a provider role to a claim. |
| Coding | `claim_diagnoses` | Ordered claim diagnoses and their captured code snapshots. |
| Coding | `service_lines` | Repeatable claim lines with dates, POS, procedure snapshot, four optional string modifiers (`modifier_1` through `modifier_4`), diagnosis pointers, charge, units, and rendering provider. |
| Audit | `claim_audit_events` | Append-style record of workflow events. |
| Reference | `npi_references` | Minimal NPPES-derived NPI validation record. |
| Reference | `icd10_codes` | Version-aware ICD-10-CM code and description. |
| Reference | `procedure_codes` | CPT / HCPCS code, system, description, and effective dates. |
| Reference | `reference_data_updates` | Shared audit metadata for a reference refresh. |

## Coverage normalization

```text
InsuredParty -> InsurancePolicy <- Payer
Claim -> ClaimCoverage -> InsurancePolicy
```

Member ID and group number describe a policy, not a person. Payer sequence and relationship to patient describe how that policy is used on a particular claim. Separating those facts avoids duplication and supports multiple coverages without adding payer-specific columns to `claims`.

Payer mailing addresses store address lines, city, state, a required five-digit ZIP code, and an optional four-digit ZIP extension. Keeping the ZIP components separate preserves the required base code while supporting ZIP+4 without making the extension mandatory.

## Snapshot plus reference pattern

The design intentionally stores both a transaction value and an optional reference key:

| Transactional field | Reference key | Reason |
|---|---|---|
| `providers.npi` | `providers.npi_reference_id` | Preserve what was entered while recording the active NPI match. |
| `claim_diagnoses.diagnosis_code` | `claim_diagnoses.icd10_reference_id` | Preserve the submitted diagnosis even after a future code-set refresh. |
| `service_lines.procedure_code` | `service_lines.procedure_reference_id` | Preserve the billed procedure while exposing system, description, and effective dates. |

The references are nullable for migration compatibility and historical records. New form submissions validate supplied values against active references before saving.

## Reference refresh metadata

`reference_data_updates` is intentionally one table rather than separate dataset and import-run hierarchies. It records only what the capture application and dashboard need:

- dataset name;
- official source name, URL, and version;
- pending, completed, or failed status;
- started and completed timestamps;
- record count, trigger identity, and notes.

Reference rows can point back to the update that loaded them. A scheduled or manually triggered loader can populate the same structure and report its result through the dashboard.

Expected source cadence is not hard-coded in the schema: NPPES publishes downloadable files including a monthly full replacement, ICD-10-CM files are released by effective period, and CMS publishes HCPCS Level II quarterly update files. The update history therefore records the version and effective dates instead of assuming every dataset is monthly.

> The repository seed contains a clearly labeled fictional development subset only. It is not represented as a complete or official source import. Full CPT content also requires an appropriately licensed source.

## CMS-1500-specific relationships

- A claim owns any number of `service_lines`. The web form adds and removes line forms dynamically and does not apply the paper form's six-line layout limit.
- `service_lines.rendering_provider_id` supports the line-level rendering provider represented by Item 24J.
- `diagnosis_pointer_1` through `diagnosis_pointer_4` support the bounded Item 24E references. Form validation prevents a pointer from targeting an empty diagnosis position.
- `claim_providers.provider_role` supports billing, rendering, referring, and facility roles without duplicating provider columns on `claims`.

## Patient and payer maintenance

Patient and payer entry before claim entry is a workflow requirement, not a new database requirement. The existing `patients`, `insured_parties`, `payers`, and `insurance_policies` tables are reusable master records and are maintainable through Django Admin. A user-facing lookup/select workflow can reuse those tables without another schema redesign.

## Constraints and indexes

Key protections include:

- unique claim number;
- one provider-role assignment per claim/provider/role;
- one diagnosis order per claim;
- one payer sequence and one policy occurrence per claim;
- conditional policy uniqueness when member or group data exists;
- indexes for NPI, code-system/activity, effective dates, claim status, service dates, member ID, and payer identifier.

## Complexity controls

Reference staging tables, taxonomy child tables, generalized payer-identifier tables, service-line diagnosis joins, and service-line provider joins are not represented because the current business rules do not require independent lifecycles or unbounded relationships for them. Workflow and integration tables can be added when their concrete events, retention rules, and query patterns are defined.

This is the main design trade-off: normalize facts that are reusable or genuinely many-to-many, but keep bounded CMS-1500 fields direct and recognizable.

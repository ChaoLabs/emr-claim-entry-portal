# CMS-1500 Claim Data Model

## Design goals

This schema supports entry, validation, review, and persistence of CMS-1500 professional-claim data.

Its normalized relationships also provide stable inputs for reference-file automation and ANSI X12 837P integration while keeping claim-capture responsibilities cohesive.

## Table inventory

The capture model uses reusable party and coverage records, claim-owned diagnoses and service lines, ordered relationship tables, and focused reference data. EDI archives and returned remittances are documented separately in `edi-erd.md`.

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
| Coding | `service_lines` | Repeatable claim lines with dates, POS, procedure snapshot, charge, units, and rendering provider. |
| Coding | `ServiceLineDiagnosis` | Ordered links from a service line to diagnoses on the same claim; implements the many-to-many relationship. |
| Coding | `ServiceLineModifier` | Ordered modifier values belonging to a service line, with no four-column storage limit. |
| Audit | `claim_audit_events` | Append-style record of workflow events. |
| Reference | `npi_references` | Minimal NPPES-derived NPI validation record. |
| Reference | `icd10_codes` | Version-aware ICD-10-CM code and description. |
| Reference | `procedure_codes` | CPT / HCPCS code, system, description, and effective dates. |
| Reference | `reference_data_updates` | Shared audit metadata for a reference refresh. |

## Coverage normalization

An insurance policy joins the subscriber and payer. Claim Coverage applies that policy to an individual claim.

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
- `ServiceLineDiagnosis` links a service line to actual `ClaimDiagnosis` rows, rather than storing only positional integers. The same diagnosis can support several lines, and a line can have several diagnoses. `position` records their importance for that line.
- `ServiceLineModifier` records each modifier and its position. Users add or remove entries as needed.
- The capture form selects diagnosis codes already entered on this claim. A deleted diagnosis cannot silently retarget a line; validation requires the user to fix the selection.
- Capture request safeguards currently cap each formset/list at 200 entries; these protect server resources and are separate from claim-format limits.
- Storage and capture support more entries than the current export profile. The current `005010X222A1` exporter permits at most 12 claim diagnoses, four diagnosis references per service line, and four modifiers per service line. It reports an export issue for overflow and never truncates saved data. This is an explicit exporter boundary, not a four-item database limit.
- `claim_providers.provider_role` supports billing, rendering, referring, and facility roles without duplicating provider columns on `claims`.

## Patient and payer maintenance

Patient and payer entry before claim entry is a workflow requirement, not a new database requirement. The existing `patients`, `insured_parties`, `payers`, and `insurance_policies` tables are reusable master records and are maintainable through Django Admin. A user-facing lookup/select workflow can reuse those tables without another schema redesign.

## Constraints and indexes

Key protections include:

- unique claim number;
- one provider-role assignment per claim/provider/role;
- one diagnosis order per claim;
- unique service-line/diagnosis pairs, positive and unique per-line positions;
- positive and unique modifier positions, with repeated modifier values rejected;
- same-claim diagnosis linking enforced by capture and model validation; raw SQL and bulk ORM writes must not bypass that validation;
- one payer sequence and one policy occurrence per claim;
- conditional policy uniqueness when member or group data exists;
- indexes for NPI, code-system/activity, effective dates, claim status, service dates, member ID, and payer identifier.

## Migration from fixed fields

Claims migration `0005` creates the two ordered tables, copies each existing pointer and modifier in its original slot order, then removes the eight scalar columns. A pointer is resolved using its own claim's `diagnosis_order`, never another claim's diagnosis. Invalid or repeated legacy pointers and repeated modifiers stop the migration with the service-line ID; they are not silently discarded. Correct those records in the old version and rerun the migration.

Existing claim IDs, diagnosis codes, procedure values, and archived X12 documents remain unchanged. Reversing the migration is refused if an entry beyond position four would be lost. Use a database backup and the forward migration for normal deployment; code rollback alone does not restore a removed schema.

## Scope and format references

This change addresses the November demo feedback: clearer relationships and flexible entry. It does not add a new adjudication engine or fraud-detection model. The exporter still requires a receiving-partner review before live submission.

- [X12 RFI 1882: diagnosis count and service-line pointers in 005010](https://x12.org/resources/requests-for-interpretation/rfi-1882-icd10-837)
- [X12 RFI 1366: duplicate diagnosis pointers](https://x12.org/resources/requests-for-interpretation/rfi-1366-sv107-duplicate-pointers)
- [CMS claim-field instructions: up to four modifiers](https://www.cms.gov/outreach-and-education/mln/wbt/mln4462429-mln-wbt-1500/1500/lesson05/04/index.html)

These references inform this export profile. They do not replace the applicable TR3 or payer-specific requirements.

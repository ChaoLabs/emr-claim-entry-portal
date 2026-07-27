# C4 Model Architecture Notes

This document records the initial C4 Model architecture for the EMRTS Electronic Claim Entry & Submission Portal.

The current assigned scope is the CMS-1500 capture group: building the web interface and PostgreSQL database design needed to capture professional claim information. ANSI X12 837P generation and Medicare/MAC transmission are included as future-facing containers so the documentation remains aligned with the larger project direction.

## Level 1: System Context Diagram

```mermaid
flowchart TB
    staff["Provider Office Staff<br/>Billing Specialist, Front Desk, Office Admin"]
    portal["Electronic Claim Entry & Submission Portal<br/>Web-based CMS-1500 claim entry system"]
    npi["CMS NPI Registry<br/>Provider reference source"]
    converter["ANSI X12 837P Generation<br/>Future project component"]
    medicare["Medicare / MAC<br/>Future electronic claim receiver"]

    staff -->|"Enter and review CMS-1500 claim information"| portal
    portal -->|"Reference provider identifiers when needed"| npi
    portal -.->|"Future validated claim data"| converter
    converter -.->|"Future 837P transaction submission"| medicare
```

## Level 2: Container Diagram

```mermaid
flowchart TB
    staff["Provider Office Staff"]

    subgraph system["Electronic Claim Entry & Submission Portal"]
        web["Web UI<br/>CMS-1500 capture screens"]
        app["Django Application<br/>Claim workflow, validation, and data management"]
        admin["Django Admin<br/>Internal review and management"]
        db[("PostgreSQL Database<br/>Claims, patients, insured parties, providers, diagnoses, service lines")]
        future837p["Future 837P Converter<br/>Maps validated claim data to ANSI X12 837P"]
        futureTx["Future Medicare/MAC Transmission<br/>Submits electronic claim transactions"]
    end

    npi["CMS NPI Registry<br/>External provider reference source"]
    medicare["Medicare / MAC<br/>External payer endpoint"]

    staff -->|"Uses browser"| web
    web -->|"Submits claim entry forms"| app
    admin -->|"Reviews and manages captured data"| app
    app -->|"Stores structured claim data"| db
    app -->|"Optional provider reference lookup"| npi
    app -.->|"Future validated claim payload"| future837p
    future837p -.->|"Future 837P transaction"| futureTx
    futureTx -.->|"Future direct submission"| medicare
```

## Initial Container Responsibilities

| Container | Responsibility |
| --- | --- |
| Web UI | Presents CMS-1500-style claim capture screens for provider office staff. |
| Django Application | Handles claim entry workflow, validation rules, persistence, and admin integration. |
| PostgreSQL Database | Stores structured claim data, patient and insured information, provider information, diagnosis codes, service lines, and audit fields. |
| Django Admin | Provides an internal backend interface for reviewing and managing captured data during development. |
| Future 837P Converter | Converts validated claim data into ANSI X12 837P format in a later project phase. |
| Future Medicare/MAC Transmission | Handles direct Medicare/MAC transmission in a later project phase. |

## Notes

- The current implementation scope is CMS-1500 information capture and PostgreSQL database design.
- The 837P converter and Medicare/MAC transmission containers are included to show how the current work will connect to the larger claim submission workflow later.
- Mermaid diagrams are used so GitHub can render architecture diagrams directly in Markdown and keep documentation close to the code.

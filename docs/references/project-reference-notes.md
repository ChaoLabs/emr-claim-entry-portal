# Project Reference Notes

This document summarizes the initial learning references for the EMRTS Electronic Claim Entry & Submission Portal project.

The notes are intended to keep the repository aligned with the materials shared by Verbus and to support future implementation work for CMS-1500 claim capture, ANSI X12 837P conversion, and Medicare submission workflow.

## Architecture and Documentation References

| Topic | Reference | Project Relevance |
| --- | --- | --- |
| C4 Model | https://c4model.com/ | Used to document the software architecture at different abstraction levels. The Level 2 Container Diagram is especially useful for showing the Web UI, Django application, PostgreSQL database, future 837P converter, and future Medicare/MAC transmission module. |
| Mermaid | https://github.com/mermaid-js/mermaid | Used to create diagrams with Markdown-inspired text definitions so architecture documentation can stay close to the code. |
| Mermaid in GitHub Markdown | https://github.blog/developer-skills/github/include-diagrams-markdown-files-mermaid/ | Used so diagrams can render directly inside GitHub Markdown files without storing separate image files. |

## Healthcare EDI and X12 References

| Topic | Reference | Project Relevance |
| --- | --- | --- |
| Healthcare EDI X12 workflow | https://www.youtube.com/watch?v=sHSLNWORW0Y | Supports understanding how electronic healthcare transactions move between providers, payers, and intermediaries in the claim workflow. |
| Advanced EDI Reading X12 Webinar 2018 | https://www.youtube.com/watch?v=3jr9-j6oAvE | Supports deeper understanding of how to read and interpret X12 transaction files. |
| Basics of EDI | https://www.youtube.com/watch?v=es9bEJbmGMQ | Provides general background on electronic data interchange and why structured transaction formats are used. |
| EDI ANSI X12 Envelope Structure | https://www.youtube.com/watch?v=KjEUUW9FcPA | Supports understanding the envelope hierarchy used in X12 files, including interchange, functional group, and transaction set levels. |

## CMS and Provider Reference

| Topic | Reference | Project Relevance |
| --- | --- | --- |
| CMS NPI Registry | https://npiregistry.cms.hhs.gov/ | Reference source for provider identifiers and provider information. It may be useful for provider lookup, validation support, or future data-entry assistance. |

## Implementation Concepts to Track

| Concept | Current Understanding | Project Impact |
| --- | --- | --- |
| CMS-1500 | Paper professional claim form used to capture patient, insured, provider, diagnosis, and service-line information. | The current group assignment is to build the screen and database structure to capture this information. |
| ANSI X12 837P | Electronic professional healthcare claim transaction format. | Future project phase will convert validated claim data from PostgreSQL into this transaction format. |
| EDI envelope structure | X12 files are organized into envelope layers such as interchange, functional group, and transaction set. | Important for future 837P generation and validation work, even though the current task is focused on CMS-1500 capture. |
| 999 / 277CA / 835 responses | Common healthcare EDI response and remittance transactions used after submission. | These are future workflow concepts for claim acknowledgment, claim status, and payment or denial information. |
| C4 Level 2 Container Diagram | Shows major deployable or runnable units and data stores. | Useful for explaining how the claim entry UI, Django application, database, and future integration components fit together. |
| Mermaid documentation | Text-based diagrams stored in Markdown. | Keeps architecture documentation version-controlled and easier to update as the project evolves. |

## Current Development Focus

The current implementation focus remains narrow and practical:

1. Capture CMS-1500 claim information through a web interface.
2. Store structured claim data in PostgreSQL.
3. Keep the design compatible with future ANSI X12 837P generation.
4. Maintain clear architecture and database documentation in GitHub.

# Database Documentation

This folder contains the logical and physical design notes for CMS-1500 claim capture.

- [`cms1500-erd.md`](cms1500-erd.md): focused service-line/diagnosis Mermaid diagram and full logical ERD.
- [`edi-erd.md`](edi-erd.md): generated X12 archive and returned 835 records.
- [`cms1500-data-model.md`](cms1500-data-model.md): table responsibilities, normalization rationale, reference-validation pattern, and complexity controls.
- [`schema.sql`](schema.sql): logical PostgreSQL representation; its table names are descriptive, not a physical database dump.

The implemented Django migrations remain the executable source of truth. `schema.sql` is provided for database review and discussion.

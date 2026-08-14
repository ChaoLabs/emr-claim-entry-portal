# Database Documentation

This folder contains the logical and physical design notes for CMS-1500 claim capture.

- [`cms1500-erd.md`](cms1500-erd.md): presentation-ready Mermaid ERD and design decisions.
- [`cms1500-data-model.md`](cms1500-data-model.md): table responsibilities, normalization rationale, reference-validation pattern, and complexity controls.
- [`schema.sql`](schema.sql): PostgreSQL-oriented representation aligned with the Django models.

The implemented Django migrations remain the executable source of truth. `schema.sql` is provided for database review and discussion.

# Shelf Audit reporting

`build_report(completed_result, metadata=ReportMetadata(...))` copies the final
selected findings verbatim and preserves their order. It does not call a provider,
rank findings, or infer business metadata. Empty results produce valid reports.
The immutable report dataclasses contain only client-facing data and can be
serialized using `dataclasses.asdict` (dates need formatting for JSON).

Optional `image_references={1: "path/to/crop.png"}` uses one-based report numbers.
References are opaque strings; report preparation performs no image I/O.
Pass `subtitle=None` to omit the default subtitle. Display labels live in
`templates.py`, which contains constants rather than a template engine.

PDF/DOCX rendering, page layout, opportunity crops, and UI integration are future
work. A future renderer should accept a configurable official logo asset path;
the expected repository location is
`shelf_audit/assets/reporting/kendal_king_logo.png`. The original official Kendal
King logo must be provided separately; this package does not create a logo.

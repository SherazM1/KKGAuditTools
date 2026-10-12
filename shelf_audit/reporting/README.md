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

## V1 preview and PDF

After a successful Shelf Audit, the page retains the final `AuditResult` in
session state and displays a small report form below the existing opportunities.
All metadata is optional, including the date (no default date is guessed).
**Create Report** builds the report, previews it, and enables **Download Report
PDF**. Form interactions never enter the Analyze Shelf button's execution branch.
Downloads use `on_click="ignore"`. Starting a new audit clears the previous result
and export, so an unsuccessful replacement cannot leave an old report download.

`preview_renderer.render_preview(report)` returns escaped HTML.
`pdf_renderer.render_pdf(report)` returns PDF bytes using ReportLab, without a
browser or external service. Both read the same immutable report model and share
labels, metadata formatting, colors, and asset loading. PDF rendering uses bundled
Vera fonts, letter pages, proportional logo sizing, and repeated headers/footers.
Small opportunity sections stay together; oversized sections can split. Zero
findings render a successful report with a shared explanatory message.
Dates render as ISO dates. No field content is rewritten or interpreted as markup.

The official supplied PNG is stored unchanged at
`shelf_audit/assets/reporting/kendal_king_logo.png`. Both renderers accept a trusted
local `logo_path` override, or `None` to omit it. Missing or invalid PNGs are omitted
gracefully; no substitute logo is generated. Opportunity image references are
preserved by the model but are not loaded by V1 renderers. Crop selection and image
embedding remain future work, along with DOCX export.

## Tests

Install runtime dependencies from `requirements.txt` and test-only PDF inspection
from `tests/requirements-reporting.txt` (`pypdf`). Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_shelf_audit*.py'
```

Rendering tests cover variable counts, extracted text/order, optional assets,
multi-page and oversized copy, immutable inputs, escaped HTML, deterministic PDF
bytes, provider-free imports, and Streamlit report interactions without audit calls.
Fixtures use synthetic test copy only; no client-specific content is in templates.

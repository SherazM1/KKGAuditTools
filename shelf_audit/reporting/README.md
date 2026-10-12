# Shelf Audit reporting

`build_report(completed_result, metadata=ReportMetadata(...))` copies the final
selected findings verbatim and preserves their order. It does not call a provider,
rank findings, or infer business metadata. Empty results produce valid reports.
The immutable report dataclasses contain only client-facing data and can be
serialized using `dataclasses.asdict` (dates and optional photo bytes need
appropriate encoding for JSON).

Optional `image_references={1: "path/to/crop.png"}` uses one-based report numbers.
References are opaque strings; report preparation performs no image I/O.
Pass `subtitle=None` to omit the default subtitle. Display labels live in
`templates.py`, which contains constants rather than a template engine.

## V1 editable DOCX workflow

After a successful Shelf Audit, the page retains the final `AuditResult` and the
original upload/camera bytes associated with that successful run. The report area
contains only three optional text inputs (**Client**, **Retailer**, **Location**)
and a single **Download Report DOCX** action. Empty values remain blank.

A Streamlit fragment updates document bytes locally when those fields change.
Downloads use `on_click="ignore"`. No report action enters the Analyze Shelf
execution branch or imports a provider. There is no in-app report preview or PDF
action. Starting another audit clears the prior result/photo association; changing
the selected upload alone never substitutes a different photo for a completed run.

`build_report(..., audit_photo=original_bytes)` carries immutable photo bytes
unchanged into the report model. `docx_renderer.render_docx(report)` returns an
editable Word document using python-docx; no Office installation, browser, or
conversion service is required. PNG/JPEG photos are embedded unchanged inside a
3.15 by 1.4 inch maximum box, preserving their aspect ratio. Missing or invalid
photos are omitted without blocking the report. No crop or finding-image paths
are loaded, and the photo requires no second upload or image analysis.

The DOCX renders only Client/Retailer/Location from the metadata model. Extra
optional metadata remains available internally for future formats but is omitted
from this workflow. It contains the official logo, shared title/subtitle, original
photo, verbatim numbered findings, editable Approved By / Signature / Date lines,
and the shared footer. The official supplied PNG remains unchanged at
`shelf_audit/assets/reporting/kendal_king_logo.png`. Missing/invalid logo files are
omitted gracefully, with no generated replacement.

For 0–4 findings, controlled presets estimate the required height and tighten
section spacing, metadata spacing, heading size, body size (minimum 10pt), then
margins. The estimate reserves the approval area. Short sections stay together;
long sections flow normally. Reports with 5+ findings keep readable fonts rather
than forcing one page. Layout uses inline tables and ordinary Word paragraphs.
Actual pagination is performed by the receiving Word-compatible viewer and can
vary with font metrics; estimates are not a guarantee of page count. Rendering
and automated tests do not use or require a Word/LibreOffice pagination engine.

The older `pdf_renderer` and `preview_renderer` remain isolated and tested for
future use; the Shelf Audit UI imports neither of them. Opportunity crop/image
embedding and Graphic Design refinement remain future work.

## Tests

Install runtime dependencies from `requirements.txt` and test-only PDF inspection
from `tests/requirements-reporting.txt` (`pypdf`). Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_shelf_audit*.py'
```

Rendering tests cover variable counts, extracted text/order, original photo bytes
and aspect ratios, optional assets, approval/footer content, layout estimates, long
copy, immutable inputs, provider-free imports, and the three-field Streamlit UI
without audit calls. PDF/preview regression tests are also retained. DOCX page-fit
tests verify layout estimates and absence of forced breaks; they do not claim to
measure actual Word pagination.
Fixtures use synthetic test copy only; no client-specific content is in templates.

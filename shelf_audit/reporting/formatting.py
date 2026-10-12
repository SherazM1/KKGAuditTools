"""Shared presentation data and official asset loading; no audit dependencies."""

from pathlib import Path

from PIL import Image
from io import BytesIO

from .models import ReportMetadata

DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[1] / "assets/reporting/kendal_king_logo.png"
NAVY = "#141638"
BLUE = "#405BA3"


def metadata_rows(metadata: ReportMetadata) -> tuple[tuple[str, str], ...]:
    """Omit absent values; never supply a date or business details implicitly."""
    values = (
        ("Client / Brand", " / ".join(v for v in (metadata.client, metadata.brand) if v)),
        ("Retailer / Location", " / ".join(v for v in (metadata.retailer, metadata.location) if v)),
        ("Audit Date", metadata.audit_date.isoformat() if metadata.audit_date else None),
        ("Account Lead", metadata.account_lead),
        ("Audit Reference", metadata.audit_reference),
        ("Photo Reference", metadata.photo_reference),
        ("Signature", metadata.signature),
        ("Signature Date", metadata.signature_date.isoformat() if metadata.signature_date else None),
    )
    return tuple((label, value) for label, value in values if value)


def load_logo(path: Path | None = DEFAULT_LOGO_PATH) -> bytes | None:
    """Read a trusted local configuration path; absent/invalid assets are optional.

    Opportunity references are deliberately not passed here or read as paths.
    No URLs, remote downloads, or image transformations are performed.
    """
    if path is None:
        return None
    try:
        data = Path(path).read_bytes()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                return None
            image.verify()
        return data
    except (OSError, ValueError, Image.DecompressionBombError):
        return None

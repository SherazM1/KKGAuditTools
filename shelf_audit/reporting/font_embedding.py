"""Private Gotham font helpers for embedded DOCX font support."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

FONT_ASSET_FILES = {
    "Gotham Black": "Gotham-Black.ttf",
    "Gotham Bold": "Gotham-Bold.ttf",
    "Gotham Medium": "Gotham-Medium.ttf",
}


def _asset_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "fonts"


def discover_font_assets() -> dict[str, Path]:
    directory = _asset_dir()
    if not directory.exists():
        return {}
    return {family: path for family, filename in FONT_ASSET_FILES.items() for path in [directory / filename] if path.exists()}


def inspect_font(path: Path) -> dict[str, object]:
    font = TTFont(str(path))
    names = font["name"]
    family_name = names.getBestFamilyName() or names.getBestFullName() or path.stem
    full_name = names.getBestFullName() or family_name
    fs_type = int(getattr(font["OS/2"], "fsType", 0) or 0)
    # The common prohibited-embedding bit is the restricted-license flag; preview/print and editable
    # embedding are still acceptable for a licensed, in-house document.
    embed_allowed = not bool(fs_type & 0x0001)
    return {"family_name": family_name, "full_name": full_name, "fs_type": fs_type, "embed_allowed": embed_allowed}


def _xml_bytes(element: ET.Element) -> bytes:
    ET.register_namespace("w", NS_W)
    ET.register_namespace("r", NS_R)
    ET.register_namespace("rel", NS_PKG_REL)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(element, encoding="utf-8", xml_declaration=False)


def _ensure_relationship(root: ET.Element, relationship_type: str, target: str) -> str:
    for element in root.findall(f"{{{NS_PKG_REL}}}Relationship"):
        if element.attrib.get("Type") == relationship_type and element.attrib.get("Target") == target:
            return element.attrib["Id"]
    rel_id = f"rId{len(root.findall(f'{{{NS_PKG_REL}}}Relationship')) + 1}"
    ET.SubElement(root, f"{{{NS_PKG_REL}}}Relationship", {"Id": rel_id, "Type": relationship_type, "Target": target})
    return rel_id


def _ensure_content_type(root: ET.Element, part_name: str, content_type: str) -> None:
    effective_name = part_name if part_name.startswith("/") else f"/{part_name}"
    for element in root.findall(f"{{{NS_CT}}}Override"):
        if element.attrib.get("PartName") == effective_name:
            element.attrib["ContentType"] = content_type
            return
    ET.SubElement(root, f"{{{NS_CT}}}Override", {"PartName": effective_name, "ContentType": content_type})


def embed_report_fonts(document_bytes: bytes, *, font_paths: dict[str, Path] | None = None) -> bytes:
    available = font_paths or discover_font_assets()
    if not available:
        logger.warning("No Gotham font assets found in %s; DOCX will be generated without embedded fonts.", _asset_dir())
        return document_bytes

    font_info = {family: inspect_font(path) for family, path in available.items()}
    blocked = {family: info for family, info in font_info.items() if not info["embed_allowed"]}
    if blocked:
        blocked_summary = ", ".join(f"{family} (fsType={info['fs_type']})" for family, info in blocked.items())
        logger.warning("Font embedding is blocked by fsType restrictions: %s. The DOCX will be generated without embedded fonts.", blocked_summary)
        return document_bytes

    with zipfile.ZipFile(io.BytesIO(document_bytes), "r") as source:
        members = {name: source.read(name) for name in source.namelist()}

    content_types_xml = members.get("[Content_Types].xml")
    if content_types_xml is None:
        return document_bytes
    content_types = ET.fromstring(content_types_xml)
    for part_name in [f"word/fonts/{path.name}" for path in available.values()]:
        _ensure_content_type(content_types, part_name, "application/vnd.ms-opentype")
    _ensure_content_type(content_types, "/word/fontTable.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml")

    document_rels_xml = members.get("word/_rels/document.xml.rels")
    if document_rels_xml is None:
        document_rels = ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    else:
        document_rels = ET.fromstring(document_rels_xml)
    _ensure_relationship(document_rels, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable", "fontTable.xml")

    font_table = ET.Element(f"{{{NS_W}}}fonts")
    font_table_rels = ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    family_order = ["Gotham Medium", "Gotham Bold", "Gotham Black"]
    rel_index = 1
    for family_name in family_order:
        path = available.get(family_name)
        if path is None:
            continue
        font_entry = ET.SubElement(font_table, f"{{{NS_W}}}font", {f"{{{NS_W}}}name": family_name})
        regular_rel = f"rId{rel_index}"
        bold_rel = f"rId{rel_index + 1}"
        ET.SubElement(font_entry, f"{{{NS_W}}}embedRegular", {f"{{{NS_R}}}id": regular_rel})
        ET.SubElement(font_entry, f"{{{NS_W}}}embedBold", {f"{{{NS_R}}}id": bold_rel})
        ET.SubElement(font_table_rels, f"{{{NS_PKG_REL}}}Relationship", {
            "Id": regular_rel,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
            "Target": f"fonts/{path.name}",
        })
        ET.SubElement(font_table_rels, f"{{{NS_PKG_REL}}}Relationship", {
            "Id": bold_rel,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
            "Target": f"fonts/{path.name}",
        })
        rel_index += 2

    output = io.BytesIO()
    replace_names = {"[Content_Types].xml", "word/_rels/document.xml.rels", "word/fontTable.xml", "word/_rels/fontTable.xml.rels"}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as packaged:
        for name, content in members.items():
            if name in replace_names:
                continue
            packaged.writestr(name, content)
        packaged.writestr("[Content_Types].xml", _xml_bytes(content_types))
        packaged.writestr("word/_rels/document.xml.rels", _xml_bytes(document_rels))
        packaged.writestr("word/fontTable.xml", _xml_bytes(font_table))
        packaged.writestr("word/_rels/fontTable.xml.rels", _xml_bytes(font_table_rels))
        for path in available.values():
            packaged.writestr(f"word/fonts/{path.name}", path.read_bytes())
    return output.getvalue()

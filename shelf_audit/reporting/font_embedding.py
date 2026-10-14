"""Private Gotham font helpers for embedded DOCX font support."""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
import uuid
from pathlib import Path
from lxml import etree as ET

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
    "Gotham Book": "Gotham-Book.ttf",
}


def _asset_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "fonts"


def discover_font_assets() -> dict[str, Path]:
    directory = _asset_dir()
    if not directory.exists():
        return {}
    return {family: path for family, filename in FONT_ASSET_FILES.items() for path in [directory / filename] if path.exists()}


def inspect_font(path: Path) -> dict[str, object]:
    with TTFont(str(path)) as font:
        names = font["name"]
        family_name = names.getBestFamilyName() or names.getBestFullName()
        if not family_name:
            raise ValueError(f"Font has no internal family/full name: {path}")
        full_name = names.getBestFullName() or family_name
        fs_type = int(font["OS/2"].fsType)
    # Reject restricted-license and bitmap-only embedding for these outline fonts.
    # Preview/print and editable embedding are allowed; retain the complete font.
    embed_allowed = not bool(fs_type & (0x0002 | 0x0200))
    return {"family_name": family_name, "full_name": full_name, "fs_type": fs_type, "embed_allowed": embed_allowed}


def _obfuscate_font(data: bytes, font_key: str) -> bytes:
    """OOXML: XOR the first 32 bytes with reversed GUID bytes, repeated twice.

    UUID.bytes uses the textual GUID order; bytes_le is incorrect here.
    The complete font is retained, respecting the OS/2 no-subsetting flag.
    """
    if len(data) < 32:
        raise ValueError("Embedded font must contain at least 32 bytes")
    key = uuid.UUID(font_key).bytes[::-1]
    return bytes(value ^ key[index % 16] for index, value in enumerate(data[:32])) + data[32:]


def _xml_bytes(element: ET.Element) -> bytes:
    ET.register_namespace("w", NS_W)
    ET.register_namespace("r", NS_R)
    ET.register_namespace("rel", NS_PKG_REL)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(element, encoding="utf-8", xml_declaration=False)


def _ensure_relationship(root: ET.Element, relationship_type: str, target: str) -> str:
    for element in root.findall(f"{{{NS_PKG_REL}}}Relationship"):
        if element.attrib.get("Type") == relationship_type and element.attrib.get("Target") == target:
            return element.attrib["Id"]
    used_ids = {element.get("Id") for element in root}
    index = 1
    while f"rId{index}" in used_ids:
        index += 1
    rel_id = f"rId{index}"
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
    available = discover_font_assets() if font_paths is None else font_paths
    if not available:
        logger.warning("No Gotham font assets found in %s; DOCX will be generated without embedded fonts.", _asset_dir())
        return document_bytes

    font_info = {family: inspect_font(path) for family, path in available.items()}
    blocked = {family: info for family, info in font_info.items() if not info["embed_allowed"]}
    if blocked:
        blocked_summary = ", ".join(f"{family} (fsType={info['fs_type']})" for family, info in blocked.items())
        logger.warning("Skipping font faces blocked by fsType restrictions: %s.", blocked_summary)
        available = {family: path for family, path in available.items() if family not in blocked}
        if not available:
            return document_bytes

    with zipfile.ZipFile(io.BytesIO(document_bytes), "r") as source:
        members = {name: source.read(name) for name in source.namelist()}

    content_types_xml = members.get("[Content_Types].xml")
    if content_types_xml is None:
        return document_bytes
    content_types = ET.fromstring(content_types_xml)
    _ensure_content_type(content_types, "/word/fontTable.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml")

    document_rels_xml = members.get("word/_rels/document.xml.rels")
    if document_rels_xml is None:
        document_rels = ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    else:
        document_rels = ET.fromstring(document_rels_xml)
    _ensure_relationship(document_rels, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable", "fontTable.xml")

    font_table = ET.fromstring(members["word/fontTable.xml"]) if "word/fontTable.xml" in members else ET.Element(f"{{{NS_W}}}fonts")
    font_table_rels = ET.fromstring(members["word/_rels/fontTable.xml.rels"]) if "word/_rels/fontTable.xml.rels" in members else ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    family_order = ["Gotham Medium", "Gotham Book", "Gotham Bold", "Gotham Black"]
    embedded_parts = {}
    for family_name in family_order:
        path = available.get(family_name)
        if path is None:
            continue
        internal_name = str(font_info[family_name]["family_name"])
        font_entry = next((entry for entry in font_table if entry.get(f"{{{NS_W}}}name") == internal_name), None)
        if font_entry is None:
            font_entry = ET.SubElement(font_table, f"{{{NS_W}}}font", {f"{{{NS_W}}}name": internal_name})
        # Replace only this face's references; preserve unrelated font entries.
        for entry in list(font_entry):
            if entry.tag.startswith(f"{{{NS_W}}}embed"):
                old_id = entry.get(f"{{{NS_R}}}id")
                font_entry.remove(entry)
                for rel in list(font_table_rels):
                    if rel.get("Id") == old_id:
                        old_part = "word/" + rel.get("Target", "")
                        members.pop(old_part, None)
                        for override in list(content_types):
                            if override.get("PartName") == "/" + old_part:
                                content_types.remove(override)
                        font_table_rels.remove(rel)
        data = path.read_bytes()
        font_key = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:kkg:embedded-font:" + hashlib.sha256(data).hexdigest())).upper() + "}"
        part_name = f"word/fonts/{path.stem}.odttf"
        embedded_parts[part_name] = _obfuscate_font(data, font_key)
        _ensure_content_type(content_types, part_name, "application/vnd.openxmlformats-officedocument.obfuscatedFont")
        rel_id = _ensure_relationship(font_table_rels, NS_R + "/font", f"fonts/{path.stem}.odttf")
        # Explicit faces: Medium is regular; Bold/Black are selected with w:b.
        role = "embedBold" if family_name in ("Gotham Bold", "Gotham Black") else "embedRegular"
        ET.SubElement(font_entry, f"{{{NS_W}}}{role}", {
            f"{{{NS_R}}}id": rel_id, f"{{{NS_W}}}fontKey": font_key,
            f"{{{NS_W}}}subsetted": "false",
        })

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
        for name, data in embedded_parts.items():
            packaged.writestr(name, data)
    return output.getvalue()

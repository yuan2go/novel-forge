from __future__ import annotations

import hashlib
import posixpath
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from defusedxml.ElementTree import fromstring

from .contracts import IngestionFailure, safe_relative_path
from .segmentation import heading


def _target(base: str, href: str) -> tuple[str, str]:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query:
        raise IngestionFailure("EPUB_EXTERNAL_RESOURCE_REFUSED", href[:128])
    name = (
        posixpath.normpath(
            posixpath.join(posixpath.dirname(base), unquote(parsed.path))
        )
        if parsed.path
        else base
    )
    return safe_relative_path(name), unquote(parsed.fragment)


def _xml(archive: ZipFile, name: str):
    return fromstring(
        archive.read(name), forbid_dtd=False, forbid_entities=True, forbid_external=True
    )


def _toc_volume_scopes(root: Any, base: str, limit: int) -> dict:
    """Preserve explicit navigation ancestry; labels alone never group volumes."""
    result = {}

    def visit(node: Any, parents: list, depth: int) -> None:
        kind = node.tag.rsplit("}", 1)[-1]
        scope = parents
        if kind in {"li", "navPoint"}:
            link = node.find("{*}a") if kind == "li" else node.find("{*}content")
            label = link if kind == "li" else node.find("{*}navLabel/{*}text")
            if link is not None:
                target = _target(base, link.attrib["href" if kind == "li" else "src"])
                title = "".join(label.itertext()).strip() if label is not None else ""
                found = heading(title, limit)
                if found and found[0] == "VOLUME":
                    scope = [
                        *parents,
                        {
                            "identity": target[0] + "#" + (target[1] or "0"),
                            "display_name": title,
                            "level": depth,
                            "basis": "EXPLICIT_TOC_HIERARCHY.v1",
                        },
                    ]
                if target in result and result[target] != scope:
                    raise IngestionFailure(
                        "EPUB_VOLUME_SCOPE_REVIEW_REQUIRED", str(target)
                    )
                result[target] = scope
        for child in node:
            visit(child, scope, depth + (1 if kind in {"li", "navPoint"} else 0))

    visit(root, [], 1)
    return result


def _text(raw: bytes, profile: Any) -> tuple:
    soup = BeautifulSoup(raw, "html.parser")
    for selector in (
        *[
            s
            for s in profile.html_remove_selectors
            if s not in {"header", "footer", "nav", "noscript"}
        ],
        "script",
        "style",
        "iframe",
        "object",
    ):
        for node in soup.select(selector):
            node.decompose()
    roots = soup.select(profile.html_body_selector)
    if not roots:
        raise IngestionFailure("EPUB_BODY_MISSING")
    if any(
        root.find_parent() in roots or any(parent in roots for parent in root.parents)
        for root in roots
    ):
        raise IngestionFailure("EPUB_BODY_SELECTOR_OVERLAP")
    parts, anchors, classifications = [], {}, {}
    offset = 0
    heading_levels = {}
    for root in roots:
        for node in [root, *root.descendants]:
            if isinstance(node, Tag):
                if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    heading_levels[offset] = int(node.name[1])
                frame = (
                    node
                    if node.name in {"header", "footer", "nav", "noscript"}
                    else node.find_parent(["header", "footer", "nav", "noscript"])
                    if node.get("id")
                    else None
                )
                if frame is not None:
                    classifications[offset] = frame.name
                for identity in {
                    str(node[key]) for key in ("id", "name") if node.get(key)
                }:
                    if identity in anchors:
                        raise IngestionFailure("EPUB_ANCHOR_DUPLICATE", identity[:128])
                    anchors[identity] = offset
            elif (
                isinstance(node, NavigableString)
                and not isinstance(node, Comment)
                and node.strip()
            ):
                text = str(node).strip()
                parts.append(text + "\n")
                offset += len(text) + 1
    return (
        "".join(parts),
        anchors,
        bool(soup.find("img") or soup.find("image")),
        classifications,
        heading_levels,
    )


def logical_records(
    path: Path, file: dict, profile: Any, budget: Any
) -> Iterator[dict]:
    from .parsers import _mapped
    import unicodedata

    normal = profile.normalization
    assert normal is not None
    scoped_volumes = profile.version == "corpus-parser.v5"
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) > budget.max_files
            or sum(i.file_size for i in entries) > budget.max_expanded_bytes
        ):
            raise IngestionFailure("EPUB_EXPANSION_LIMIT")
        names = set()
        for item in entries:
            name = safe_relative_path(item.filename.rstrip("/"))
            if (
                name in names
                or item.flag_bits & 1
                or (item.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise IngestionFailure("EPUB_MEMBER_INVALID")
            names.add(name)
            if (
                item.file_size > min(budget.max_file_bytes, budget.memory_bytes // 8)
                or item.file_size
                > max(1, item.compress_size) * budget.max_archive_ratio
            ):
                raise IngestionFailure("EPUB_RESOURCE_LIMIT")
        container = _xml(archive, "META-INF/container.xml")
        roots = container.findall(".//{*}rootfile")
        if len(roots) != 1:
            raise IngestionFailure("EPUB_PACKAGE_AMBIGUOUS")
        opf_name = safe_relative_path(roots[0].attrib["full-path"])
        opf = _xml(archive, opf_name)
        items = {
            i.attrib["id"]: i.attrib for i in opf.findall(".//{*}manifest/{*}item")
        }
        cover_ids = {
            m.attrib["content"]
            for m in opf.findall(".//{*}meta")
            if m.attrib.get("name") == "cover" and m.attrib.get("content") in items
        }
        cover_resources = {_target(opf_name, items[i]["href"])[0] for i in cover_ids}
        nontext_resources = []
        spine = []
        for i in opf.findall(".//{*}spine/{*}itemref"):
            item = items.get(i.attrib["idref"])
            if item is None:
                raise IngestionFailure("EPUB_SPINE_ITEM_MISSING", i.attrib["idref"])
            href, _ = _target(opf_name, item["href"])
            if href not in names:
                raise IngestionFailure("EPUB_RESOURCE_MISSING", href)
            spine.append((href, i.attrib.get("linear", "yes") != "no"))
        order = {name: n for n, (name, _) in enumerate(spine)}
        if len(order) != len(spine):
            raise IngestionFailure("EPUB_SPINE_DUPLICATE")
        toc = []
        toc_scopes = {}
        for item in items.values():
            name, _ = _target(opf_name, item["href"])
            if "nav" in item.get("properties", "").split():
                nav = _xml(archive, name)
                for section in nav.findall(".//{*}nav"):
                    if (
                        "toc"
                        not in section.attrib.get(
                            "{http://www.idpf.org/2007/ops}type", ""
                        ).split()
                    ):
                        continue
                    if scoped_volumes:
                        toc_scopes.update(
                            _toc_volume_scopes(section, name, normal.heading_max_chars)
                        )
                    for link in section.findall(".//{*}a"):
                        toc.append(
                            (
                                *_target(name, link.attrib["href"]),
                                "".join(link.itertext()).strip(),
                            )
                        )
        if not toc:
            ncx = next(
                (
                    i
                    for i in items.values()
                    if i.get("media-type") == "application/x-dtbncx+xml"
                ),
                None,
            )
            if ncx:
                name, _ = _target(opf_name, ncx["href"])
                navigation = _xml(archive, name)
                if scoped_volumes:
                    toc_scopes = _toc_volume_scopes(
                        navigation, name, normal.heading_max_chars
                    )
                for node in navigation.findall(".//{*}navPoint"):
                    content = node.find("{*}content")
                    label = node.find("{*}navLabel/{*}text")
                    if content is not None:
                        toc.append(
                            (
                                *_target(name, content.attrib["src"]),
                                label.text or "" if label is not None else "",
                            )
                        )
        if len(toc) > budget.max_units_per_work or any(t[0] not in order for t in toc):
            raise IngestionFailure("EPUB_TOC_RESOURCE_INVALID")
        if any(order[a[0]] > order[b[0]] for a, b in zip(toc, toc[1:])):
            raise IngestionFailure("EPUB_TOC_ORDER_CONFLICT")
        continuations = {
            (r.left_href, r.right_href): r for r in profile.epub_continuations
        }
        for (left, right), declaration in continuations.items():
            if (
                declaration.checksum != file["checksum"]
                or left not in order
                or right not in order
                or order[right] != order[left] + 1
            ):
                raise IngestionFailure("EPUB_CONTINUATION_SCOPE_INVALID")
        current = None
        volume_stack = []
        ordinal = 0
        last_href = ""
        toc_open = False

        def finish() -> dict:
            nonlocal ordinal
            ordinal += 1
            row = _mapped(
                {"text": current["text"]},
                profile.model_copy(update={"fields": {"text": "text"}}),
                ordinal,
                file,
            )
            if row is None:
                raise IngestionFailure(
                    "EPUB_FILTERED_LOGICAL_UNIT",
                    "logical chapter filters require an explicit scoped review",
                )
            row.update(
                text=current["text"],
                title=current["title"],
                unit_kind=current["kind"],
                declared_number=current["number"],
                order=ordinal,
                chapter_id=current["key"],
                volume=current.get("volume_id", ""),
            )
            row["source_locator"].update(
                offset_kind="EPUB_LOGICAL_CHAPTER",
                precision="EXTRACTED_FRAGMENT_RANGES",
                original_byte_offset=None,
                fragments=current["fragments"],
                join_rule="LF_BETWEEN_FRAGMENTS.v1",
                nontext_resources=list(nontext_resources),
            )
            if scoped_volumes:
                row["source_locator"]["volume_scope"] = current["volume_scope"]
            return row

        for spine_index, (href, linear) in enumerate(spine):
            raw = archive.read(href)
            resource_xml = _xml(archive, href)
            text, anchors, images, classifications, heading_levels = _text(raw, profile)
            member_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
            starts = {}
            ordered_toc = []
            for name, fragment, title in toc:
                if name != href:
                    continue
                if fragment and fragment not in anchors:
                    raise IngestionFailure(
                        "EPUB_TOC_ANCHOR_MISSING", href + "#" + fragment
                    )
                offset = anchors[fragment] if fragment else 0
                ordered_toc.append(offset)
                found = heading(title, normal.heading_max_chars)
                starts[offset] = (
                    found or ("EXTRA", None, title),
                    fragment,
                    "TOC_ANCHOR",
                )
            if ordered_toc != sorted(ordered_toc) or len(set(ordered_toc)) != len(
                ordered_toc
            ):
                raise IngestionFailure("EPUB_TOC_ANCHOR_ORDER_CONFLICT")
            offset = 0
            for line in text.splitlines(keepends=True):
                found = heading(line, normal.heading_max_chars)
                if found:
                    if offset in starts and starts[offset][0][2] != found[2]:
                        raise IngestionFailure("EPUB_TOC_TITLE_CONFLICT", href)
                    starts.setdefault(offset, (found, "", "VERIFIED_HEADING"))
                offset += len(line)
            if not text.strip():
                linked_images = {
                    _target(
                        href,
                        n.attrib.get(
                            "{http://www.w3.org/1999/xlink}href",
                            n.attrib.get("src", ""),
                        ),
                    )[0]
                    for n in resource_xml.iter()
                    if n.tag.rsplit("}", 1)[-1] in {"image", "img"}
                }
                declared_cover = (
                    bool(linked_images) and linked_images <= cover_resources
                )
                if linear and (not images or not declared_cover):
                    raise IngestionFailure(
                        "EPUB_IMAGE_TEXT_UNAVAILABLE"
                        if images
                        else "EPUB_EMPTY_LINEAR_RESOURCE",
                        href,
                    )
                nontext_resources.append(
                    {
                        "href": href,
                        "member_hash": member_hash,
                        "spine_ordinal": spine_index + 1,
                        "category": "DECLARED_COVER_IMAGE"
                        if declared_cover
                        else "NONLINEAR_RESOURCE",
                        "linked_images": sorted(linked_images),
                    }
                )
                last_href = href
                toc_open = False
                continue
            for position, category in classifications.items():
                starts[position] = (
                    ("AUTHOR_NOTE", None, category),
                    "",
                    "SEMANTIC_NON_BODY_RESOURCE",
                )
            offsets = sorted({0, len(text), *starts})
            for left, right in zip(offsets, offsets[1:]):
                fragment_text = text[left:right]
                if not fragment_text.strip():
                    continue
                declared = starts.get(left)
                if not linear:
                    declared = (("AUTHOR_NOTE", None, href), "", "NONLINEAR_RESOURCE")
                can_continue = (
                    left == 0
                    and current is not None
                    and current["kind"] in {"CHAPTER", "EXTRA"}
                    and linear
                    and (
                        toc_open
                        or (last_href, href) in continuations
                        or not current["text"][current["heading_end"] :].strip()
                    )
                )
                if declared or not can_continue:
                    if current:
                        yield finish()
                    info, anchor, basis = declared or (
                        ("UNSTRUCTURED", None, href),
                        "",
                        "REVIEW_REQUIRED",
                    )
                    explicit_scope = (
                        toc_scopes.get((href, anchor))
                        if basis == "TOC_ANCHOR"
                        else None
                    )
                    if scoped_volumes and explicit_scope:
                        volume_stack = [dict(v) for v in explicit_scope]
                    elif scoped_volumes and info[0] == "VOLUME":
                        level = heading_levels.get(left)
                        if level is None:
                            raise IngestionFailure(
                                "EPUB_VOLUME_SCOPE_REVIEW_REQUIRED",
                                href + "#" + (anchor or str(left)),
                            )
                        while volume_stack and volume_stack[-1]["level"] >= level:
                            volume_stack.pop()
                        volume_stack.append(
                            {
                                "identity": href + "#" + (anchor or str(left)),
                                "display_name": info[2],
                                "level": level,
                                "basis": "EXPLICIT_HEADING_HIERARCHY.v1",
                                "member_hash": member_hash,
                            }
                        )
                    current = {
                        "text": "",
                        "title": info[2],
                        "kind": info[0],
                        "number": info[1],
                        "key": href + "#" + (anchor or str(left)),
                        "fragments": [],
                        "heading_end": 0,
                        "volume_id": volume_stack[-1]["identity"]
                        if volume_stack
                        else "",
                        "volume_scope": [dict(v) for v in volume_stack],
                    }
                    toc_open = basis == "TOC_ANCHOR" and info[0] in {"CHAPTER", "EXTRA"}
                else:
                    basis = (
                        "TOC_READING_INTERVAL"
                        if toc_open
                        else "SCOPED_CONTINUATION"
                        if (last_href, href) in continuations
                        else "HEADING_AWAITS_BODY"
                    )
                    anchor = ""
                normalized = fragment_text.replace("\r\n", "\n").replace("\r", "\n")
                if normal.unicode_form == "NFC":
                    normalized = unicodedata.normalize("NFC", normalized)
                prefix = (
                    "\n"
                    if current["text"] and not current["text"].endswith("\n")
                    else ""
                )
                start = len(current["text"]) + len(prefix)
                current["text"] += prefix + normalized
                if len(current["text"].encode()) > normal.max_unit_bytes:
                    raise IngestionFailure(
                        "BODY_UNIT_REVIEW_REQUIRED",
                        "logical chapter exceeds frozen bound",
                    )
                if len(current["fragments"]) >= budget.max_files:
                    raise IngestionFailure("EPUB_FRAGMENT_LIMIT")
                current["fragments"].append(
                    {
                        "href": href,
                        "spine_ordinal": spine_index + 1,
                        "member_hash": member_hash,
                        "acquisition_hash": file["checksum"],
                        "fragment": anchor,
                        "selector": profile.html_body_selector,
                        "extracted_unicode_start": left,
                        "extracted_unicode_end": right,
                        "logical_unicode_start": start,
                        "logical_unicode_end": len(current["text"]),
                        "logical_utf8_start": len(current["text"][:start].encode()),
                        "logical_utf8_end": len(current["text"].encode()),
                        "separator": prefix,
                        "normalization_changed": fragment_text != normalized,
                        "text_hash": "sha256:"
                        + hashlib.sha256(normalized.encode()).hexdigest(),
                        "basis": basis,
                        "evidence": continuations[(last_href, href)].evidence
                        if basis == "SCOPED_CONTINUATION"
                        else None,
                    }
                )
                if scoped_volumes:
                    current["fragments"][-1]["volume_scope"] = current["volume_scope"]
                if not current["heading_end"] and declared:
                    first, sep, _ = normalized.partition("\n")
                    if first.strip() == current["title"]:
                        current["heading_end"] = len(first) + len(sep)
            last_href = href
        if current:
            yield finish()

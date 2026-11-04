"""XMP sidecars: tags and the capture date beside a library file, never inside it.

Immich and digiKam read hierarchical tags from ``digiKam:TagsList`` first, and Immich uses the
first tag field it finds without merging, so every tag goes there: ``Collections/...``,
``Sources/...`` and any keywords the photo already carried. ``dc:subject`` repeats them as flat
keywords for other apps. The original's bytes never change, so its hash still matches.
"""

from collections.abc import Iterable
from xml.sax.saxutils import escape, quoteattr

NAMESPACES = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "digiKam": "http://www.digikam.org/ns/1.0/",
    "exif": "http://ns.adobe.com/exif/1.0/",
}


def _unique(values: Iterable[str]) -> list[str]:
    seen, kept = set(), []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            kept.append(value)
    return kept


def _items(container: str, values: list[str]) -> str:
    lines = "".join(f"\n     <rdf:li>{escape(value)}</rdf:li>" for value in values)
    return f"<rdf:{container}>{lines}\n    </rdf:{container}>"


def sidecar(
    *,
    collections: Iterable[str] = (),
    sources: Iterable[str] = (),
    keywords: Iterable[str] = (),
    taken: str | None = None,
    offset: str | None = None,
) -> str:
    """The sidecar's XML. The same inputs always give the same bytes, so a rebuild can tell
    whether anything changed."""
    collections, sources, keywords = sorted(set(collections)), sorted(set(sources)), list(keywords)
    tags = _unique(
        [f"Collections/{c}" for c in collections] + [f"Sources/{s}" for s in sources] + keywords
    )
    subjects = _unique([c.rsplit("/", 1)[-1] for c in collections] + keywords)
    date = f"\n    exif:DateTimeOriginal={quoteattr(taken + (offset or ''))}" if taken else ""
    body = []
    if tags:
        body.append(f"   <digiKam:TagsList>\n    {_items('Seq', tags)}\n   </digiKam:TagsList>")
    if subjects:
        body.append(f"   <dc:subject>\n    {_items('Bag', subjects)}\n   </dc:subject>")
    namespaces = "".join(
        f"\n    xmlns:{prefix}={quoteattr(uri)}"
        for prefix, uri in NAMESPACES.items()
        if prefix not in ("x", "rdf")
    )
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        f'<x:xmpmeta xmlns:x="{NAMESPACES["x"]}">\n'
        f' <rdf:RDF xmlns:rdf="{NAMESPACES["rdf"]}">\n'
        f'  <rdf:Description rdf:about=""{namespaces}{date}>\n'
        + "\n".join(body)
        + ("\n" if body else "")
        + "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>\n'
    )

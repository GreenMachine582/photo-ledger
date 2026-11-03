"""Keywords a photo already carries, read so its sidecar keeps them. Read-only.

Immich reads a sidecar's tags ahead of the photo's own, so a keyword left out of the sidecar
would stop showing. IPTC keywords and XMP ``dc:subject`` are both read. The XMP is scanned with
a bounded pattern rather than a full XML parser, as it comes from a file and a parser would
expand any entities it declared.
"""

import html
import re
from pathlib import Path

from PIL import Image, IptcImagePlugin

#: The most XMP that's scanned, so an oversized packet can't stall a build.
_MAX_XMP = 1 << 20
_SUBJECT = re.compile(rb"<dc:subject\b[^>]*>(.*?)</dc:subject>", re.DOTALL)
_ITEM = re.compile(rb"<rdf:li\b[^>]*>([^<]{1,500})</rdf:li>")


def _iptc(image: Image.Image) -> list[str]:
    info = IptcImagePlugin.getiptcinfo(image) or {}
    values = info.get((2, 25))
    if values is None:
        return []
    if isinstance(values, bytes):
        values = [values]
    return [value.decode("utf-8", "replace") for value in values]


def _xmp(image: Image.Image) -> list[str]:
    packet = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if isinstance(packet, str):
        packet = packet.encode("utf-8")
    if not packet:
        return []
    found = []
    for block in _SUBJECT.findall(packet[:_MAX_XMP]):
        for item in _ITEM.findall(block):
            found.append(html.unescape(item.decode("utf-8", "replace")))
    return found


def embedded_keywords(path: Path) -> list[str]:
    """The photo's own keywords, in order and without repeats. ``[]`` when it can't be read."""
    try:
        with Image.open(path) as image:
            values = _iptc(image) + _xmp(image)
    except (OSError, SyntaxError, ValueError):
        return []
    seen, kept = set(), []
    for value in (v.strip() for v in values):
        if value and value not in seen:
            seen.add(value)
            kept.append(value)
    return kept

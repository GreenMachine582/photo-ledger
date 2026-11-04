"""XMP sidecars and the keywords read from photos."""

import io
import xml.etree.ElementTree as ET

import make_fixtures

from photo_ledger.exports.xmp import NAMESPACES, sidecar
from photo_ledger.library.keywords import embedded_keywords

RDF = f"{{{NAMESPACES['rdf']}}}"


def parse(text):
    """Our own output only: parsing a sidecar read from elsewhere would need a safe parser."""
    return ET.fromstring(text.split("?>", 1)[1].rsplit("<?xpacket", 1)[0])


def items(root, tag):
    found = root.find(f".//{tag}")
    return [] if found is None else [li.text for li in found.iter(f"{RDF}li")]


def test_tags_dates_and_subjects():
    text = sidecar(
        collections=["Holidays/2019/Japan", "Best of 2019"],
        sources=["old-pc", "backup"],
        keywords=["Fuji", "Japan"],
        taken="2019-04-02T10:30:00",
        offset="+09:00",
    )
    root = parse(text)
    digikam = f"{{{NAMESPACES['digiKam']}}}TagsList"
    assert items(root, digikam) == [
        "Collections/Best of 2019",
        "Collections/Holidays/2019/Japan",
        "Sources/backup",
        "Sources/old-pc",
        "Fuji",
        "Japan",
    ]
    assert items(root, f"{{{NAMESPACES['dc']}}}subject") == ["Best of 2019", "Japan", "Fuji"]
    description = root.find(f".//{RDF}Description")
    assert (
        description.get(f"{{{NAMESPACES['exif']}}}DateTimeOriginal") == "2019-04-02T10:30:00+09:00"
    )


def test_the_same_inputs_give_the_same_bytes():
    first = sidecar(collections=["b", "a"], sources=["y", "x"])
    assert first == sidecar(collections=["a", "b"], sources=["x", "y"])


def test_special_characters_are_escaped():
    text = sidecar(collections=['Tom & Jerry <"2019">'], keywords=["a&b"])
    root = parse(text)
    tags = items(root, f"{{{NAMESPACES['digiKam']}}}TagsList")
    assert tags == ['Collections/Tom & Jerry <"2019">', "a&b"]
    assert "&amp;" in text and '<"2019">' not in text


def test_an_empty_sidecar_is_still_valid():
    root = parse(sidecar())
    assert root.find(f".//{RDF}Description") is not None
    assert "DateTimeOriginal" not in sidecar()


def test_keywords_come_from_the_photos_xmp(tmp_path):
    packet = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/'
        b'22-rdf-syntax-ns#"><rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        b"<dc:subject><rdf:Bag><rdf:li>Fuji</rdf:li><rdf:li>Tom &amp; Jerry</rdf:li>"
        b"<rdf:li>Fuji</rdf:li></rdf:Bag></dc:subject></rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    buffer = io.BytesIO()
    make_fixtures.draw(7).save(buffer, "JPEG", xmp=packet)
    path = tmp_path / "tagged.jpg"
    path.write_bytes(buffer.getvalue())
    assert embedded_keywords(path) == ["Fuji", "Tom & Jerry"]


def test_a_photo_without_keywords_or_unreadable_gives_none(tmp_path):
    plain = tmp_path / "plain.jpg"
    plain.write_bytes(make_fixtures.jpeg_bytes(make_fixtures.draw(3)))
    assert embedded_keywords(plain) == []
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    assert embedded_keywords(broken) == []

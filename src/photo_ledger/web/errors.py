"""Readable reasons for a form or link FastAPI couldn't read, such as an empty required field.

The app shows them the way it shows its own refusals: a notice page, or a toast back on the page
an htmx form came from. Each reason is fixed text naming the field. The submitted value is never
repeated back.
"""

from fastapi.exceptions import RequestValidationError

#: What each form field is called on the page. Path ids are part of a link, not something typed.
FIELD_LABELS = {
    "label": "Label",
    "path": "Folder",
    "name": "Name",
    "priority": "Keeper priority",
    "confirm": "the confirmation",
    "similar_threshold": "Similar threshold",
    "value": "the date",
    "collection": "Collection",
    "source": "Collection",
    "target": "Collection",
    "action": "the decision",
    "tree": "the folder list",
}
LINK_IDS = {"source_id", "scan_id", "collection_id", "content_id", "pair_id", "file_id"}


def _field(loc: tuple) -> str:
    name = str(loc[-1]) if loc else ""
    if name in LINK_IDS:
        return "the link"
    return FIELD_LABELS.get(name) or name.replace("_", " ").capitalize() or "A field"


def _reason(error: dict) -> str:
    field = _field(tuple(error.get("loc", ())))
    kind = error.get("type", "")
    if field == "the link":
        return "That link isn't valid. Go back and try again."
    if kind == "missing":
        return f"Fill in {field}."
    if kind in {"int_parsing", "int_type", "int_from_float"}:
        return f"{field[0].upper() + field[1:]} must be a whole number."
    if kind in {"bool_parsing", "bool_type"}:
        return f"{field[0].upper() + field[1:]} must be yes or no."
    return f"{field[0].upper() + field[1:]} isn't valid."


def describe(exc: RequestValidationError) -> str:
    """One sentence per problem, without repeats."""
    reasons = dict.fromkeys(_reason(error) for error in exc.errors())
    return " ".join(reasons) or "That form couldn't be read. Go back and try again."

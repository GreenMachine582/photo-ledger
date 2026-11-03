[← Back to README](../README.md)

# 🧪 Testing

This repo is public, so real photos never appear in it. `scripts/make_fixtures.py` (M1) generates test images: exact copies,
resized and re-encoded versions, reused filenames, conflicting dates and truncated files.

| Layer | What it proves |
|---|---|
| GTH wiring | `tests/test_app.py` exercises the `register_*` calls and macros used, not just their installation |
| Local protections | `tests/test_security.py` covers hosts, origins, CORS and the CSRF round trip |
| Scanning | An interrupted scan resumes, changed files reconcile, and an offline source marks nothing missing |
| Detection | Reports match a hand-checked sample, and rescanning the same files creates no new pairs |
| Review | Decisions survive a restart, and a rescan queues only new pairs |
| File actions | A plan applied and undone restores the fixtures exactly, including across volumes, and a simulated crash halfway never reports the plan as complete |

Tests only ever touch `tmp_path`.

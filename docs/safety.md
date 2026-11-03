[← Back to README](../README.md)

# 🛡️ Safety

## File safety

Only `actions/executor.py` may change a source folder, and undo goes through it too. Nothing is ever deleted. SQLite and
the filesystem can't commit together, so a journal entry is written before and after each operation.

| Safeguard | Requirement |
|---|---|
| Before moving | The file must exist and match its expected BLAKE3 hash, or that action stops |
| Destination | Never overwrite an existing file |
| Same volume | Use an atomic rename where supported |
| Across volumes | Copy, verify the hash, then remove the original |
| Quarantine | Off by default. Configured per source, on any device, and suggested on the same volume because that's faster |
| Interrupted plan | On next start, `recovery.py` finds unfinished actions and checks both paths before continuing or rolling back |
| Undo | Verify the quarantined file, and never overwrite a file created since |

By default, nothing leaves an original backup: approved keepers are copied into the destination library. Moving rejected
copies to quarantine is opt-in for each source, with its own path, which can be on another device.

A quarantine on another device makes reverts slower, not riskier. Moves and undo both copy, verify the hash, then
remove, so an interruption always leaves a verified copy to recover from. The quarantine device must be connected and
have enough space, and the dry run checks both first. If the device is offline, undo names the device it needs.

## Local-only protections

The app binds to `127.0.0.1`, but any website you visit can make your browser send requests to it.

| Protection | Where |
|---|---|
| `Host` must be `127.0.0.1` or `localhost`, which stops DNS rebinding | `TrustedHostMiddleware` |
| State-changing requests from another `Origin` are refused | `web/security.py` |
| State-changing routes need a CSRF token | `register_csrf` and `require_csrf` |
| No cross-origin access | CORS has no allowed origins |
| No arbitrary paths | The image route serves only registered files |

The CSRF cookie is `Secure`. Chromium sends it to `127.0.0.1` over plain HTTP, which this project relies on.

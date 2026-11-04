[← Back to README](../README.md)

# 🛡️ Safety

## File safety

Only `actions/executor.py` may change a source folder or a quarantine, and undo and recovery go through it too. Nothing
is ever deleted: a file leaves its folder only as the last step of a verified move, and the only other file the
executor removes is its own unfinished `.photo-ledger-partial` copy. SQLite and the filesystem can't commit together, so
a journal entry is written before and after each operation.

| Safeguard | Requirement |
|---|---|
| Dry run | Read-only. Checks that both ends are online, each file is unchanged (size and date, or its hash with `--verify`), no destination exists or is shared, and there's room on each volume a copy crosses to. A plan only applies after a clean one |
| Before moving | Both ends must be online, so no folder is ever created on the wrong drive. The file must exist and match its expected BLAKE3 hash, or that action stops and its file stays put |
| Destination | Never overwrite an existing file |
| Same volume | A rename that never replaces: `os.rename` on Windows, a hard link then unlink elsewhere |
| Across volumes | Copy to a `.photo-ledger-partial` file, fsync, verify the hash, rename it into place without replacing, then remove the original |
| Journal | Each action is `started` before its file operation and `done` or `failed` after it. A plan is `applied` only when every action is done, and is `incomplete` otherwise |
| Quarantine | Off by default. Turned on per source with `source quarantine <label> <folder>`, on any device, and suggested on the same volume because that's faster. The folder must already exist and sit outside every source, and no source can be mapped inside it |
| Interrupted plan | `recovery.py` runs before `apply`, `undo` and `serve`. For each `started` action it removes any partial copy, then checks both paths: original verified and no destination means retry, destination verified and no original means done, both verified means finish the move, and anything else is marked failed with both files left alone. An action whose source or quarantine is unplugged waits |
| Undo | A plan of its own, with `restore` actions in reverse order through the same executor. Each quarantined file is verified first, and a file created since at the original path is never overwritten. If the quarantine is offline, undo names it |
| Forgetting a source | Its journal rows are removed only from plans that were undone, and from the undo plans that reversed them. A source in a plan that could still be undone or recovered can't be forgotten |

By default, nothing leaves an original backup: approved keepers are copied into the destination library. The library
must sit outside every source and quarantine. Each picture is copied the verified way: a partial file, fsync, a hash
check, then a rename that never replaces. The original is never removed, so building has no undo and needs none. Files
already in the library stay put: a picture rejected afterwards is reported, never deleted. The only library files the
build ever replaces are its own XMP sidecars, and only while each still has the hash it was written with. A date fix
changes only the library copy's file date, which leaves its content hash unchanged. Moving rejected
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

The CSRF cookie is `Secure`. Chromium, Firefox and Edge all send it to `127.0.0.1` over plain HTTP, which this project
relies on.

# Glacier Bookmark Sync v1 — implementation boundary

Status: E2E codec and isolated backend CAS store IN DEVELOPMENT. NOT deployed,
NOT connected to the live Glacier Sync API or user-facing automatic sync.

Existing Glacier /v1/vault/private and /v1/vault/work routes contain **website
account cards**, not bookmarks. Never reuse them for browser bookmarks or Cookies.

## Encrypted portable bookmark envelope

- Independent format: glacier-bookmarks-v1
- Cleartext *inside* AES-256-GCM: schema=1, space=private|work and array of
  bookmarks with profile/title/url/at (timestamp in milliseconds).
- PBKDF2-HMAC-SHA256 (400,000 iterations), 16-byte random salt, 12-byte
  random nonce, 256-bit key, AAD glacier-bookmarks-v1:<space>.
- Outer envelope: format, kdf, salt, nonce, ciphertext (unpadded URL-safe
  base64). Backend never receives the passphrase or decrypts the contents.
- Only safe HTTP(S) URLs, no embedded URL credentials or localhost.
- Android encrypted bookmark store can hold 160 bookmarks in TOTAL, counting
  private and work together. No import may silently evict local records.
- Test fixture fixed salt/nonce is for deterministic tests ONLY; production
  encryption always uses independent fresh randomness.

## Future VPS auth wiring — NOT YET DONE

The server must expose a SEPARATE authenticated bookmark resource:
GET /v1/bookmarks/private and /v1/bookmarks/work return a per-account,
per-space version + encrypted envelope. PUT on the same endpoints accepts
expected_version and encrypted envelope, and performs transactional CAS;
HTTP 409 on concurrent modification, never overwrite. The stable user ID
MUST come from the existing verified login session, never request JSON.

The isolated SQLite backend at vps-control/glacier_bookmark_cas_store.py
implements encrypted-only rows and per-user/per-space atomic versions.
A separate optional adapter in vps-control/glacier_bookmark_api_router.py
provides GET/PUT route handlers only after injection of a verified existing
Glacier session identity dependency. Neither module is mounted on the VPS.
Neither module implements authentication. Do not mount it without
first inspecting and correctly integrating the live Glacier Sync session
verifier and database ownership; do not create an unauthenticated shortcut.

Clients must first obtain explicit first-sync consent and keep independent
encrypted version/fingerprint baselines for bookmarks. Refuse cloud version
rollback, simultaneous edits, account mismatch, corrupted envelopes,
redirected HTTPS, offline VLESS and any proposed destructive auto-import.
Bookmark deletions require tombstone semantics before bidirectional sync.

## Cookie and website login sessions — NOT INCLUDED

Cookie values, session IDs and device tokens are login credentials. They
must not be copied to another device automatically. Qt WebEngine offers
asynchronous CookieStore APIs, while GeckoView's public StorageController
does not provide a matching generic cookie import/export API. Per-site
consent, device-binding review, and secure API feasibility must precede
any optional session transfer. Existing saved account-card synchronization
is NOT equivalent to Cookie or logged-in website session synchronization.

## Release gate

1. Python on Windows/macOS and Android 15 must decrypt the same synthetic
   fixture, reject wrong spaces/passwords/tampering and re-encrypt randomly.
2. Backend CAS tests demonstrate atomic write conflicts, account and space
   isolation and ciphertext-only storage.
3. Android import previews preserve bookmarks, history/download metadata
   and total capacity; no silent truncation.
4. Existing account vault routes, local user databases, public APK/DMG/EXE
   installers and signed update feeds must remain unchanged.
5. Implement the actual authenticated VPS endpoints and client consent/UI,
   then pass new end-to-end and genuine device tests before public release.

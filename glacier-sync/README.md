# Glacier Sync — private cross-device account vault

Implementation lives in `server.py`. **This commit does not deploy a service,
register a DNS name, or create a public account.** Do not advertise it as a
working service until deployment and client integration are verified.

## Architecture

- Account login: username and password. Password is salted/scrypt-hashed in SQLite;
  plaintext password must not be logged.
- Devices: first registered device is the owner. New devices can authenticate
  but receive a pending token. Only owner approves new devices, revokes devices
  and changes which account spaces they can access.
- Device permissions: new approved devices receive `private` only. Grant `work`
  separately. Revocation immediately invalidates that device's sessions.
- Vault: per-user, per-space ciphertext only, with optimistic version checks
  (conflicting uploads get HTTP 409). Server never handles the user's vault
  passphrase, decrypted passwords or site cookies.
- Wire: `glacier-vault-v1`, PBKDF2-HMAC-SHA256 with 400000 rounds, random
  16-byte salt, AES-256-GCM random 12-byte nonce, AAD
  `glacier-sync-v1:<space>`, URL-safe unpadded Base64.
- Sessions: random bearer token; hashed at rest; expires after 30 days.
  Stored client-side using Windows DPAPI, macOS Keychain-protected encryption,
  or Android Keystore. No long-lived server signing key is committed.
- The first version exposes two sync spaces: `private`, `work`. Desktop's
  default workspace maps to `private`; other desktop workspaces map to `work`.
  Website login cookies remain independently isolated by each WebEngine profile.
  Distinct non-default desktop workspaces share the *work* vault, not cookies.
- **No automatic website login or automatic password autofill.** Code retrieval
  uses an explicitly configured HTTPS API only after the user clicks.
- **No automatic background synchronization.** Upload and download are
  user-initiated, replace the chosen space after confirmation, and require the
  vault passphrase. Other spaces remain unchanged.

## Deployment prerequisites

1. On a controlled VPS create dedicated system user `glacier-sync`, directory
   `/opt/glacier-sync` (the three checked-in service files and `server.py`)
   and persistent `/var/lib/glacier-sync`.
2. Python 3.12 virtual environment: `python3 -m venv .venv`, then
   `./.venv/bin/pip install -r requirements.txt`.
3. Create `/etc/glacier-sync/secrets.env` readable only by root/service
   operator. Set `GLACIER_SYNC_INVITE=<unique-random-32+-character-secret>`
   and `GLACIER_SYNC_DB=/var/lib/glacier-sync/sync.sqlite3`.
   Do not paste the invite in public logs or commit it to Git.
4. Install `glacier-sync.service` to systemd. Put a working authenticated
   HTTPS reverse proxy in front; `nginx.example.conf` is a reference, not
   a preconfigured public hostname. Bind Uvicorn to 127.0.0.1 only.
5. Configure DNS and TLS for your own domain, then use its `https://` origin
   in each Glacier client. Clients refuse redirects and send requests via
   configured local VLESS/SOCKS5 only.
6. Create an account using the private invite and its first owner device.
   Authorize additional devices via the owner device UI. Each device needs
   the user's *vault encryption passphrase* for decryption; that passphrase
   must be distinct from the server's registration invite.

## API summary

`POST /v1/register`, `POST /v1/login`, `GET /v1/session`,
`POST /v1/session/activate`, `POST /v1/logout`,
`GET /v1/devices`, `POST /v1/devices/{id}/approve`,
`DELETE /v1/devices/{id}`, `PUT /v1/devices/{id}/grants`,
`GET /v1/spaces`, `GET/PUT /v1/vault/{private|work}`.

The encrypted vault is not equivalent to remotely synchronized website login
sessions; websites can independently require re-authentication on another device.

## Important operational risks and remaining work

- Password reset/recovery is intentionally unavailable without an owner/admin
  workflow. Back up the service database and store user recovery secrets safely.
- There is no email verification, audited security assurance, support for
  passkeys, or automated device-to-device key exchange in v1.
- On-device vault passphrase is not retained: explicit entry is required to
  read/write the cloud vault; losing it makes the cloud ciphertext unreadable.
- Newly approved devices should always be reviewed on the owner device.
- The provided code is **not** a completed or deployed production identity
  service. Before any real credentials are stored, audit account lifecycle,
  rate limiting, cryptography interoperability and deployment controls.

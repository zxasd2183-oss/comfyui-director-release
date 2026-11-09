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

## Fixed Glacier account origin

The production service origin is **https://sync.borealos.cn**. Create an A record for `sync` pointing to the existing Guangzhou VPS public IPv4; do not proxy requests via a third-party CDN during initial TLS deployment. Issue the certificate for `sync.borealos.cn` before enabling the Nginx vhost. The service is NOT deployed merely by creating DNS or committing this repository.

## VPS 111.230.226.74 — DNS and six-domain HTTPS are already configured

The existing `/etc/nginx/conf.d/zz-new-domains.conf` is configured with
per-host TLS server blocks on **8443**. The `sync.borealos.cn` block serves
`/var/www/placeholder` until activated. **Do not replace this Nginx file
or issue a separate certificate:** the existing certificate already includes
all six hostnames. Use the safe sync-only deployment from the matching repo
branch on the VPS:

```bash
sudo bash glacier-sync/deploy-111.sh
```

It installs the restricted backend on `127.0.0.1:18991`, preserves the
registration invite across installs, installs
`/etc/nginx/snippets/glacier-sync.conf`, then adds precisely one include
to the **existing** sync 8443 server block. It backs up the Nginx file and
refuses to patch an unknown layout or an existing `location` block. On
Nginx syntax failure, the old config is restored; the backend remains
installed but not publicly routed. An unexpected placeholder `location`
requires manually replacing that location with the snippet include *only
inside the sync TLS server*; never overwrite the other five blocks.

External API verification: `https://sync.borealos.cn/health` must return
`{"status":"ok","service":"glacier-sync","version":1}`. The site root
may return HTTP 404 by design; success is checked at `/health`.

## After DNS points to the VPS

In a fresh clone of this repository on the VPS (use branch
`fix/glacier-browser-windows-v0201-input`), deploy the isolated sync backend:

```bash
sudo bash glacier-sync/install-vps.sh
```

The installer creates a private registration invite, stores it at
`/etc/glacier-sync/secrets.env`, installs the service at
`127.0.0.1:18991`, then requires a successful local `/health` response.
It does **not** alter existing Director/Jipite Nginx configuration.

Next, use the site's existing TLS manager to issue a certificate for
`sync.borealos.cn`, and adapt `glacier-sync/nginx.example.conf` to the
currently deployed listener/SNI scheme. Run `nginx -t` before any reload.
Do not copy the example's `listen 443` unexamined if your VPS uses a
custom HTTPS listener or multiplexed ports.

Final external health check: `https://sync.borealos.cn/health` should
return JSON containing `"status":"ok"`. Never put the private invite,
account passwords or encryption passphrases in a public issue or chat.

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

## Automatic sync and device proof

- Device IDs are **public identifiers**, not authorization credentials. Each device
  is provisioned with a random 256-bit secret. The server stores its hash only;
  the encrypted local client session holds the secret. A known device must prove
  possession of this secret when restoring a previously approved login.
- Desktop and Android can opt into per-space automatic synchronization after
  **one explicit initial manual upload/download per space** establishes a baseline.
- The locally remembered E2E passphrase is optional and only stored inside
  Windows DPAPI / macOS Keychain-backed / Android Keystore encryption. Turning
  off automatic sync clears the remembered passphrase.
- Periodic sync runs no more often than the selected cadence (3 minutes), plus
  a debounced local edit trigger. Remote vault contents remain E2E encrypted.
- Each space tracks remote revision and its local account fingerprint. Changes
  on both sides produce a **conflict**; no automatic overwrite occurs.
- Remote data only replaces local accounts if the local fingerprint still
  matches what was present at the beginning of the network request.
- There is currently no general-purpose conflict merge or browser settings
  synchronization; manual resolution remains necessary when both sides edited
  the same space. The first production release must be validated end to end.

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

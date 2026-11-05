# Glacier Browser v0.18 — one-time signed updater key migration

> The v0.14–v0.17 public key cannot be used with a newly generated private
> key. Do not try to "fix" the old key by changing or disabling signature
> verification. Legacy signed update channels and the old Mac VPS mirror remain
> unchanged.

## What happens

1. On your own trusted Windows/Mac computer, the setup script generates ONE new
   32-byte Ed25519 private key (no server or assistant sees the private value).
2. The private key is saved locally in `~/.config/glacier-browser/signing-v2`
   and uploaded into GitHub Actions Secrets as
   `GLACIER_UPDATE_SIGNING_PRIVATE_HEX` using authenticated GitHub CLI.
3. The public half alone is installed in GitHub Actions Variables as
   `GLACIER_UPDATE_SIGNING_PUBLIC_HEX`.
4. The script commits public fingerprint trigger files to the v0.18 migration
   branch, causing both guarded platform builds to start.
5. Windows and Mac v0.18 installers embed the new public key and share a new
   `v2-...` key ID. Both build workflows fail closed on missing public key.
6. When BOTH v0.18 releases have been verified and published, Actions signs
   v2 channel manifests. If the automatic trigger is delayed, the hourly
   publisher checks again. Legacy channels are not touched.
7. **Install v0.18 manually on each computer ONE LAST TIME.** v0.17 cannot
   authenticate a v0.18 release without its lost private key. Later versions
   can auto-check, auto-download if opted in, verify signatures and hash, and
   ask you to confirm installation.

## Prerequisites

- You own/administer `zxasd2183-oss/comfyui-director-release`.
- Python 3.10+ and the cryptography package installed on your computer.
- GitHub CLI (`gh`) installed and `gh auth login` completed.
- The PC must have write permission to repository Actions Secrets, Variables,
  and to `build/glacier-browser-v0-18-key-migration` branch.

## Windows PowerShell

```powershell
winget install --id GitHub.cli --exact
py -m pip install cryptography
gh auth login
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/glacier_rotate_update_key.py" -OutFile "$env:TEMP\glacier_rotate_update_key.py"
py "$env:TEMP\glacier_rotate_update_key.py"
```

If `py` is not recognized, install Python 3.12 (for example using
`winget install --id Python.Python.3.12 --exact`) first and reopen PowerShell.

## macOS Terminal

```bash
brew install gh
gh auth login
python3 -m venv "$HOME/.config/glacier-browser/migrate-venv"
"$HOME/.config/glacier-browser/migrate-venv/bin/python" -m pip install cryptography
curl -fL 'https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/glacier_rotate_update_key.py' -o /tmp/glacier_rotate_update_key.py
"$HOME/.config/glacier-browser/migrate-venv/bin/python" /tmp/glacier_rotate_update_key.py
```

## Security and verification

- NEVER paste the private key, the GitHub Actions Secret, or a screenshot of
  its value into ChatGPT or an issue. The script doesn't print it.
- Keep a secure offline backup of the user-only private-key file. GitHub Secrets
  cannot reveal their values after upload.
- The repository variable contains only the PUBLIC key; it is safe to inspect.
- The current migration script does NOT read or modify your VLESS node, your
  Windows DPAPI store, or your Mac Keychain data.
- Keeping signing material in GitHub Secrets trades full offline isolation for
  unattended release signing. Review repository write permissions and workflows.
- Windows v0.18 uses the new `glacier-browser-updates-v2` signed channel via
  the existing VLESS updater.
- macOS v0.18 uses the same new channel on GitHub via a mandatory
  `socks5h://127.0.0.1:<port>` VLESS connection, not the old VPS mirror.
- Both require pinned Ed25519 signatures and exact version-bound release URLs,
  SHA-256 and size checks. Updates fail closed without a working VLESS proxy.
- Installation is **not silent**: Windows requires install confirmation;
  macOS opens a verified DMG and requires Finder replacement confirmation.
- Neither test installer is Authenticode/Apple Developer ID signed or notarized.

## Inspect build and update pipelines

- Migration security smoke: `.github/workflows/glacier-browser-v018-migration-smoke.yml`
- Mac v0.18: `.github/workflows/glacier-browser-macos-arm64.yml`
- Windows v0.18: `.github/workflows/glacier-browser-windows-v018.yml`
- Signed publisher: `.github/workflows/glacier-browser-signed-updates.yml`
- New v2 channel branch: `glacier-browser-updates-v2`

If the local provisioning script fails, do not create another key randomly.
Preserve the existing local backup and review its error message. Re-running
the script reuses the same local key; it refuses to overwrite a different
GitHub public key.

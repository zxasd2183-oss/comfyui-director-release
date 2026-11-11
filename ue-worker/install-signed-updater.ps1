# Bootstrap a privileged *pull-only*, Ed25519-pinned UE Worker updater.
# One-time LOCAL admin operation. No inbound port, arbitrary commands, or SSH changes.
#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$PinnedPublicKeyHex
)
$ErrorActionPreference = 'Stop'
$taskName = 'Director-UE-Signed-Updater'
$workerTask = 'Director-UE-Worker-V02'
$workerDir = Join-Path $env:ProgramData 'DirectorUEWorker'
$updaterDir = Join-Path $env:ProgramData 'DirectorUEUpdater'
$source = Join-Path $PSScriptRoot 'ue_signed_updater.py'
$token = Join-Path $workerDir 'worker.token'

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw 'Updater source missing from reviewed checkout.'
}
if (-not (Test-Path -LiteralPath $token -PathType Leaf)) {
    throw 'Existing UE Worker bearer token missing.'
}
$existingTask = Get-ScheduledTask -TaskName $workerTask -ErrorAction Stop
if ([string]$existingTask.Principal.UserId -match '(?i)SYSTEM|Administrators|S-1-5-18') {
    throw 'UE Worker must continue running as its dedicated non-admin account.'
}
$python = if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    (& (Get-Command py.exe).Source -3 -c 'import sys; print(sys.executable)' | Select-Object -Last 1)
} else {
    (& (Get-Command python.exe -ErrorAction Stop).Source -c 'import sys; print(sys.executable)' | Select-Object -Last 1)
}
$python = [string]$python
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Existing Python interpreter missing.'
}
& $python -c 'import cryptography, sys; assert sys.version_info >= (3, 10)'
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.10+ with cryptography required. No automatic package install.'
}
& $python -m py_compile $source
if ($LASTEXITCODE -ne 0) { throw 'Updater Python code failed syntax verification.' }

$secret = [IO.File]::ReadAllText($token).Trim()
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:19010/v1/status' -Headers @{
        Authorization = 'Bearer ' + $secret
    } -TimeoutSec 5
} finally {
    Remove-Variable secret -ErrorAction SilentlyContinue
}
if (-not $status.ok -or [string]$status.worker_version -ne '0.5.0') {
    throw 'First deploy and verify UE Worker V0.5.0 before bootstrapping signed updates.'
}

if (Test-Path -LiteralPath $updaterDir) {
    $existing = Join-Path $updaterDir 'trusted-public-key.hex'
    if (-not (Test-Path -LiteralPath $existing -PathType Leaf)) {
        throw 'Existing updater directory lacks pinned trust key; refusing overwrite.'
    }
    $oldKey = [IO.File]::ReadAllText($existing).Trim()
    if ($oldKey -cne $PinnedPublicKeyHex) {
        throw 'Pinned public key differs: key replacement requires separate offline security review.'
    }
    $oldCode = Join-Path $updaterDir 'ue_signed_updater.py'
    if (Test-Path -LiteralPath $oldCode) {
        throw 'Updater already installed: reinstall is deliberately denied.'
    }
} else {
    New-Item -ItemType Directory -Path $updaterDir -ErrorAction Stop | Out-Null
}

# Seal the privileged updater's code, trusted key and state to SYSTEM/admins.
& icacls.exe $updaterDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to restrict updater ACL.' }
$publicPath = Join-Path $updaterDir 'trusted-public-key.hex'
if (-not (Test-Path -LiteralPath $publicPath)) {
    [IO.File]::WriteAllText($publicPath, $PinnedPublicKeyHex, [Text.Encoding]::ASCII)
}
$installedPath = Join-Path $updaterDir 'installed-version.txt'
if (Test-Path -LiteralPath $installedPath) {
    if ([IO.File]::ReadAllText($installedPath).Trim() -cne '0.5.0') {
        throw 'Installer sees incompatible existing installed-version state.'
    }
} else {
    [IO.File]::WriteAllText($installedPath, '0.5.0', [Text.Encoding]::ASCII)
}
Copy-Item -LiteralPath $source -Destination (Join-Path $updaterDir 'ue_signed_updater.py') -ErrorAction Stop

$oldScheduled = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($oldScheduled) {
    throw 'A task with this name already exists; refusing to replace privileged task.'
}
$actionText = '"{0}" "{1}"' -f $python, (Join-Path $updaterDir 'ue_signed_updater.py')
& schtasks.exe /Create /SC MINUTE /MO 5 /TN $taskName /TR $actionText /RU SYSTEM /RL HIGHEST /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to register privileged updater task.'
}
$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ([string]$registered.Principal.UserId -notmatch '(?i)SYSTEM|S-1-5-18') {
    throw 'Updater task principal is not SYSTEM.'
}
Write-Host 'Signed UE updater installed. Poll interval: 5 minutes.'
Write-Host 'Pinned Ed25519 public key SHA256 fingerprint:'
$pubBytes = [Convert]::FromHexString($PinnedPublicKeyHex)
$hash = [Security.Cryptography.SHA256]::HashData($pubBytes)
Write-Host ([Convert]::ToHexString($hash).ToLowerInvariant())
Write-Host 'Worker/SSH/token unchanged. No update runs until a valid signed channel is published.'

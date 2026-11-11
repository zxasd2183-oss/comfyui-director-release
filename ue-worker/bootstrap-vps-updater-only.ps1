# Bootstrap ONLY the VPS signed Hub updater after Windows trust is installed.
# Does not touch the existing Windows Worker updater, keys, tasks, or UE files.
#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$')]
    [string]$VpsSshTarget
)
$ErrorActionPreference = "Stop"
$publicFile = Join-Path $env:ProgramData "DirectorUEUpdater\trusted-public-key.hex"
if (-not (Test-Path -LiteralPath $publicFile -PathType Leaf)) {
    throw "Windows updater trust key not installed; do not generate a replacement"
}
$public = [IO.File]::ReadAllText($publicFile).Trim()
if ($public -cnotmatch "^[a-f0-9]{64}$") {
    throw "Installed public key has invalid format"
}
$root = Join-Path $PSScriptRoot "..\vps-control"
$files = @("ue_hub_signed_updater.py", "install-ue-hub-signed-updater.sh")
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $file) -PathType Leaf)) {
        throw "Missing reviewed VPS bootstrap source: $file"
    }
}
$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$scp = (Get-Command scp.exe -ErrorAction Stop).Source
$folder = "/tmp/director-ue-bootstrap-" + [guid]::NewGuid().ToString("N")
try {
    & $ssh $VpsSshTarget ("umask 077; mkdir -m 0700 " + $folder)
    if ($LASTEXITCODE -ne 0) { throw "VPS secure bootstrap folder creation failed" }
    & $scp (Join-Path $root $files[0]) (Join-Path $root $files[1]) ($VpsSshTarget + ":" + $folder + "/")
    if ($LASTEXITCODE -ne 0) { throw "VPS reviewed bootstrap file transfer failed" }
    & $ssh -tt $VpsSshTarget ("sudo bash " + $folder + "/install-ue-hub-signed-updater.sh " + $public)
    if ($LASTEXITCODE -ne 0) { throw "VPS updater installer rejected prerequisites or failed" }
    & $ssh $VpsSshTarget "systemctl is-enabled director-ue-hub-signed-update.timer"
    if ($LASTEXITCODE -ne 0) { throw "VPS updater timer not enabled" }
    Write-Host "SUCCESS: VPS Hub signed pull updater installed using existing Windows-pinned public key."
    Write-Host "No new Worker installation, signing key generation, GitHub OAuth, UE render, or GPU power action."
} finally {
    # Best-effort cleanup must never mask installation success/failure.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $ssh $VpsSshTarget ("rm -rf -- " + $folder) 2>$null | Out-Null
    } catch {
        # Temporary source-only path may remain for manual review.
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

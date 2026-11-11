# One-time Windows bootstrap for pinned Ed25519 automatic UE updates.
# Optionally installs the independently signed VPS Hub updater over existing SSH.
#Requires -RunAsAdministrator
param([string]$VpsSshTarget = "")
$ErrorActionPreference = "Stop"
$repo = "zxasd2183-oss/comfyui-director-release"
$pinnedV052 = "3f0416d38d3f760f28e9b3e66325f0cc403bf937"
$updaterTask = "Director-UE-Signed-Updater"
$tokenFile = Join-Path $env:ProgramData "DirectorUEWorker\worker.token"
$tmp = $null

function Need($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Missing required tool: $name" }
    return $cmd.Source
}
# PowerShell 5.1 turns native stderr into terminating errors when
# ErrorActionPreference is Stop. Collect exit codes explicitly, preserve argv
# (including paths with spaces), and never emit GitHub CLI diagnostics.
function Invoke-Gh([string[]]$Args) {
    $prior = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $lines = @(& $gh @Args 2>$null)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prior
    }
    return @{ ExitCode = $code; Output = ($lines -join "`n") }
}
function Live-Worker-Version {
    $secret = [IO.File]::ReadAllText($tokenFile).Trim()
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:19010/v1/status" -Headers @{Authorization=("Bearer " + $secret)} -TimeoutSec 7
    } finally {
        Remove-Variable secret -ErrorAction SilentlyContinue
    }
    if (-not $status.ok) { throw "Worker health unavailable" }
    return [string]$status.worker_version
}
$git = Need "git.exe"
$gh = Need "gh.exe"
$py = Need "py.exe"
$auth = Invoke-Gh -Args @("auth", "status")
if ($auth.ExitCode -ne 0) { throw "Run gh auth login with repository access first" }
& $py -3 -c "import cryptography, sys; assert sys.version_info >= (3,10)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ and cryptography are required before bootstrap" }
if (Get-ScheduledTask -TaskName $updaterTask -ErrorAction SilentlyContinue) {
    throw "A signed updater task already exists; refusing to replace its pinned key"
}
$version = Live-Worker-Version
if ($version -notin @("0.5.1","0.5.2")) {
    throw "Expected Worker V0.5.1 or V0.5.2, got $version"
}
if ((Get-ScheduledTask -TaskName "Director-UE-Worker-V02" -ErrorAction Stop).State -ne "Running") {
    throw "Existing UE Worker must be running"
}

try {
    if ($version -eq "0.5.1") {
        # Separate pinned CI-tested checkout contains a V0.5.2 Worker.
        # Current integration agent.py is V0.7, so do NOT install-v052
        # from the integration checkout.
        $tmp = Join-Path $env:TEMP ("director-ue-v052-" + [guid]::NewGuid().ToString("N"))
        & $git clone --quiet --depth 1 --branch feature/ue-v052-preview-image-read ("https://github.com/" + $repo + ".git") $tmp
        if ($LASTEXITCODE -ne 0) { throw "Could not fetch V0.5.2 source" }
        $actual = (& $git -C $tmp rev-parse HEAD | Select-Object -Last 1).Trim()
        if ($actual -cne $pinnedV052) {
            throw "Pinned V0.5.2 commit differs; refuse unreviewed administrative code"
        }
        & (Join-Path $tmp "ue-worker\install-v052.ps1")
        if ((Live-Worker-Version) -ne "0.5.2") {
            throw "Guarded V0.5.2 Worker install failed health verification"
        }
        Write-Host "V0.5.2 baseline healthy (9 signed release code files)"
    }

    # No silent key rotation. Existing public key can be reused by new nodes.
    $keyResult = Invoke-Gh -Args @("variable", "get", "DIRECTOR_UE_SIGNING_PUBLIC_HEX", "--repo", $repo)
    $key = if ($keyResult.ExitCode -eq 0) { [string]$keyResult.Output } else { "" }
    $key = $key.Trim()
    if ($key -and $key -notmatch "^[a-f0-9]{64}$") {
        throw "Existing repository public key malformed"
    }
    if (-not $key) {
        # PowerShell 5.1 mangles a multi-line here-string passed via -c.
        # Execute a temporary reviewed Python source file instead. The script
        # contains no keys; generated private bytes exist only in memory.
        $generator = Join-Path $env:TEMP ("director-ue-keygen-" + [guid]::NewGuid().ToString("N") + ".py")
        try {
            [IO.File]::WriteAllText($generator, @'
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key=Ed25519PrivateKey.generate()
prv=key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex()
pub=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
print(json.dumps({"private":prv,"public":pub}))
'@, [Text.Encoding]::UTF8)
            $raw = & $py -3 $generator
            if ($LASTEXITCODE -ne 0) { throw "Ed25519 key generation failed" }
        } finally {
            Remove-Item -LiteralPath $generator -Force -ErrorAction SilentlyContinue
        }
        $pair = $raw | ConvertFrom-Json
        $key = [string]$pair.public
        if ($key -notmatch "^[a-f0-9]{64}$") { throw "Invalid keypair" }
        $folder = Join-Path $env:LOCALAPPDATA "DirectorUEKeys"
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        $backup = Join-Path $folder "ue-signing-private-dpapi.txt"
        if (Test-Path $backup) { throw "Encrypted key backup exists; inspect before changing keys" }
        ConvertTo-SecureString ([string]$pair.private) -AsPlainText -Force | ConvertFrom-SecureString | Set-Content $backup -NoNewline
        $envFile = Join-Path $folder ("gh-secret-" + [guid]::NewGuid().ToString("N") + ".env")
        try {
            Set-Content -LiteralPath $envFile -Value ("DIRECTOR_UE_SIGNING_PRIVATE_HEX=" + [string]$pair.private) -Encoding ascii -NoNewline
            $secretWrite = Invoke-Gh -Args @("secret", "set", "--repo", $repo, "--env-file", $envFile)
            if ($secretWrite.ExitCode -ne 0) { throw "Could not store GitHub Actions signing secret" }
            $variableWrite = Invoke-Gh -Args @("variable", "set", "DIRECTOR_UE_SIGNING_PUBLIC_HEX", "--repo", $repo, "--body", $key)
            if ($variableWrite.ExitCode -ne 0) { throw "Could not store GitHub Actions public key" }
        } finally {
            Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
            Remove-Variable pair,raw -ErrorAction SilentlyContinue
        }
        Write-Host "Dedicated UE signing key configured in GitHub. Private key not printed."
    } else {
        $secretList = Invoke-Gh -Args @("secret", "list", "--repo", $repo, "--json", "name")
        if ($secretList.ExitCode -ne 0 -or -not ((($secretList.Output | ConvertFrom-Json).name) -contains "DIRECTOR_UE_SIGNING_PRIVATE_HEX")) {
            throw "Pinned public key exists but corresponding GitHub secret is not provisioned"
        }
        Write-Host "Existing signing key reused without rotation."
    }

    & (Join-Path $PSScriptRoot "install-signed-updater.ps1") -PinnedPublicKeyHex $key
    if (-not (Get-ScheduledTask -TaskName $updaterTask -ErrorAction SilentlyContinue)) {
        throw "Windows pinned updater task did not register"
    }
    # Prove the SYSTEM task really starts. Merely registering it does not
    # prove Python dependencies, GitHub connectivity or signed-channel trust.
    $receipt = Join-Path $env:ProgramData "DirectorUEWorker\signed-update-status.json"
    Start-ScheduledTask -TaskName $updaterTask -ErrorAction Stop
    $verified = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Path -LiteralPath $receipt -PathType Leaf) {
            $check = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
            if ($check.status -in @("no_signed_channel","already_current","upgraded")) {
                $verified = $true
                break
            }
            if ($check.status -eq "failed") {
                throw "Signed updater initial check failed: $($check.code)"
            }
        }
    }
    if (-not $verified) {
        throw "SYSTEM updater task registered but did not produce a healthy signed-channel receipt"
    }
    Write-Host "SUCCESS: Windows updater executed as SYSTEM and reported $($check.status)"
    if ($VpsSshTarget) {
        if ($VpsSshTarget -notmatch "^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$") {
            throw "VpsSshTarget must be an exact user@host; no command flags"
        }
        $ssh = Need "ssh.exe"
        $scp = Need "scp.exe"
        $files = Join-Path $PSScriptRoot "..\vps-control"
        & $ssh $VpsSshTarget "mkdir -m 0700 -p /tmp/director-ue-once"
        if ($LASTEXITCODE -ne 0) { throw "VPS bootstrap folder unavailable" }
        & $scp (Join-Path $files "ue_hub_signed_updater.py") (Join-Path $files "install-ue-hub-signed-updater.sh") ($VpsSshTarget + ":/tmp/director-ue-once/")
        if ($LASTEXITCODE -ne 0) { throw "VPS code transfer failed" }
        & $ssh $VpsSshTarget ("sudo bash /tmp/director-ue-once/install-ue-hub-signed-updater.sh " + $key)
        if ($LASTEXITCODE -ne 0) { throw "VPS signed updater bootstrap failed" }
        Write-Host "SUCCESS: VPS Hub signed updater installed; 5-minute checks."
    } else {
        Write-Host "VPS updater not configured: optional -VpsSshTarget user@host"
    }
    Write-Host "Code deployment remains blocked until signed reviewed releases are published from main."
} finally {
    if ($tmp -and (Test-Path -LiteralPath $tmp)) {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

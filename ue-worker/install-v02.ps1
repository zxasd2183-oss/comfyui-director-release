# Upgrade the existing Director UE Worker without changing SSH/VPS.
# Requires elevated PowerShell. Creates a non-admin account for Unreal code.
# On failure, tries to restart the original V0.1 scheduled task.
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$files = @("agent.py", "ue_jobs.py", "unreal_build_episode.py")
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $src $name))) {
        throw "Missing bundled trusted source file: $name"
    }
}
$dest = Join-Path $env:ProgramData "DirectorUEWorker"
$root = "C:\DirectorVirtualStudio"
$token = Join-Path $dest "worker.token"
if (-not (Test-Path -LiteralPath $token)) { throw "V0.1 token missing; refusing rotation" }

# Resolve the actual runtime rather than assuming py.exe resolves the same
# interpreter for every Windows account.
$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    $python = (& $launcher.Source -3 -c "import sys;print(sys.executable)" | Select-Object -Last 1)
} else {
    $python = (& (Get-Command python.exe -ErrorAction Stop).Source -c "import sys;print(sys.executable)" | Select-Object -Last 1)
}
$python = [string]$python
if (-not (Test-Path -LiteralPath $python)) { throw "No accessible Python runtime" }
& $python -c "import sys;assert sys.version_info >= (3,10)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required" }

$serviceName = "DirectorUEWorker"
$account = "$env:COMPUTERNAME\$serviceName"
$existing = Get-LocalUser -Name $serviceName -ErrorAction SilentlyContinue
if ($existing -and $existing.Enabled -eq $false) {
    throw "Existing dedicated runner account disabled; refusing to reconfigure"
}
if (-not $existing) {
    $random = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($random) } finally { $rng.Dispose() }
    $password = [Convert]::ToBase64String($random)
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    New-LocalUser -Name $serviceName -Password $secure -PasswordNeverExpires `
        -Description "Unprivileged Director UE Editor runner" | Out-Null
} else {
    # Existing service-user password is not available from Windows.
    # Do not reset it silently or weaken its credential controls.
    throw "Runner account already exists; supply a controlled task update procedure"
}

New-Item -ItemType Directory -Path $dest -Force | Out-Null
New-Item -ItemType Directory -Path $root -Force | Out-Null

$backup = Join-Path $dest ("backup-v01-" + (Get-Date -Format "yyyyMMddHHmmss"))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in @("agent.py")) {
    $old = Join-Path $dest $name
    if (Test-Path -LiteralPath $old) {
        Copy-Item -LiteralPath $old -Destination (Join-Path $backup $name)
    }
}
# Trusted code cannot be modified by the unprivileged worker account.
foreach ($name in $files) {
    Copy-Item -LiteralPath (Join-Path $src $name) -Destination (Join-Path $dest $name) -Force
}
& icacls.exe $dest /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${account}:(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to restrict worker program directory" }
& icacls.exe $token /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" "${account}:R" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to grant read-only token access" }
& icacls.exe $root /grant "${account}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to grant workspace access" }

$taskName = "Director-UE-Worker-V02"
$action = New-ScheduledTaskAction -Execute $python `
    -Argument ('-u "' + (Join-Path $dest "agent.py") + '"') `
    -WorkingDirectory $dest
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 30 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

$oldTask = Get-ScheduledTask -TaskName "Director-UE-Worker" -ErrorAction SilentlyContinue
if ($oldTask) { Stop-ScheduledTask -TaskName "Director-UE-Worker" -ErrorAction SilentlyContinue }
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -User $account -Password $password -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $healthy = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $secret = [IO.File]::ReadAllText($token).Trim()
            $result = Invoke-RestMethod -Uri "http://127.0.0.1:19010/v1/status" `
                -Headers @{Authorization="Bearer $secret"} -TimeoutSec 2
            if ($result.ok -and $result.worker_version -eq "0.2.0") {
                $healthy = $true; break
            }
        } catch { }
    }
    if (-not $healthy) { throw "V0.2 worker not healthy; preserving V0.1 fallback" }
    if ($oldTask) {
        Disable-ScheduledTask -TaskName "Director-UE-Worker" | Out-Null
    }
    Write-Host "Director UE Worker V0.2 is active under limited account $account."
    Write-Host "No SSH settings, existing token, VPS, Nginx or GPU power controls changed."
} catch {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    foreach ($name in @("agent.py")) {
        $copy = Join-Path $backup $name
        if (Test-Path -LiteralPath $copy) {
            Copy-Item -LiteralPath $copy -Destination (Join-Path $dest $name) -Force
        }
    }
    if ($oldTask) {
        Enable-ScheduledTask -TaskName "Director-UE-Worker" | Out-Null
        Start-ScheduledTask -TaskName "Director-UE-Worker"
    }
    throw
} finally {
    Remove-Variable password -ErrorAction SilentlyContinue
}

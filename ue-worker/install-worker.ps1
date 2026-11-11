# Run once in elevated Windows PowerShell on the dedicated UE GPU.
# Keeps the existing reverse SSH tunnel and all existing Windows services intact.
# Requires installed Python 3.10+; never downloads or installs executables.
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$src = Join-Path $PSScriptRoot "agent.py"
if (-not (Test-Path -LiteralPath $src)) { throw "agent.py missing" }
$py = Get-Command py.exe -ErrorAction SilentlyContinue
$pythonArgs = "-3 -u"
if (-not $py) {
    $py = Get-Command python.exe -ErrorAction Stop
    $pythonArgs = "-u"
}
$python = $py.Source
$pythonCheckArgs = if ($pythonArgs -eq "-3 -u") { @("-3", "-c", "import sys; assert sys.version_info >= (3, 10)") } else { @("-c", "import sys; assert sys.version_info >= (3, 10)") }
& $python @pythonCheckArgs
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required" }
$dest = Join-Path $env:ProgramData "DirectorUEWorker"
$token = Join-Path $dest "worker.token"
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Copy-Item -LiteralPath $src -Destination (Join-Path $dest "agent.py") -Force

# Explicitly restrict token and service files to SYSTEM and local admins.
& icacls.exe $dest /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to set Windows ACL on $dest" }

if (-not (Test-Path -LiteralPath $token)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $value = ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
    [IO.File]::WriteAllText($token, $value, [Text.Encoding]::ASCII)
}
& icacls.exe $token /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to restrict token ACL" }

$action = New-ScheduledTaskAction -Execute $python -Argument (
    "$pythonArgs " + '"' + (Join-Path $dest "agent.py") + '"'
) -WorkingDirectory $dest
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 30 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Director-UE-Worker" -Action $action `
    -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Director-UE-Worker"
Write-Host "UE Worker installed. Private token is in $token (never paste it into chat)."
Write-Host "The worker is loopback-only on 127.0.0.1:19010."
Write-Host "Next: provision SAME token to VPS as /etc/director-ue-worker.token via trusted SSH."

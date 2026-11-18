# One-time setup INSIDE the owner's existing Windows RDP login.
# Creates ONLY a user-session task (no stored password, no SYSTEM execution).
# Director Worker remains the separate least-privileged API service.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$session = (Get-Process -Id $PID -ErrorAction Stop).SessionId
if (-not [Environment]::UserInteractive -or $session -le 0) {
    throw "Run this from your active, unlocked Windows RDP desktop"
}
if ($identity.Name -match '(?i)\\DirectorUEWorker$' -or
    $identity.Name -match '(?i)\\SYSTEM$') {
    throw "An existing human Windows login is required, not the Worker/SYSTEM"
}
if (-not ([Security.Principal.WindowsPrincipal] $identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run PowerShell as Administrator in the SAME RDP user account"
}
$programDir = Join-Path $env:ProgramData "DirectorUEWorker"
$runner = Join-Path $programDir "ue_process.py"
$agent = Join-Path $programDir "agent.py"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf) -or
    -not (Test-Path -LiteralPath $agent -PathType Leaf)) {
    throw "Signed Director Worker files are missing"
}
$installed = Get-Content -LiteralPath $agent -Raw
if ($installed -notmatch '"worker_version":\s*"2\.3\.7"') {
    throw "Install signed Worker 2.3.7 before enabling interactive execution"
}
# The signed Worker bundle is protected from ordinary users. Allow the
# particular RDP account to READ trusted Python code without revealing the
# batch Worker's bearer token. The token's ACL must block inheritance.
$workerToken = Join-Path $programDir "worker.token"
if (-not (Test-Path -LiteralPath $workerToken -PathType Leaf)) {
    throw "Existing private Worker token not found"
}
if (-not (Get-Acl -LiteralPath $workerToken).AreAccessRulesProtected) {
    throw "Worker token ACL inherits parent access; refusing user grant"
}
$workspace = "C:\DirectorVirtualStudio"
if (-not (Test-Path -LiteralPath $workspace -PathType Container)) {
    throw "Director workspace unavailable"
}
$accountRx = "*$($identity.User.Value):(OI)(CI)RX"
& icacls.exe $programDir /grant $accountRx | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Account read access to signed scripts failed" }
$accountModify = "*$($identity.User.Value):(OI)(CI)M"
& icacls.exe $workspace /grant $accountModify | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Account access to existing project failed" }
$python = $null
$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    $python = & $launcher.Source -3 -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) { $python = $null }
}
if (-not $python) { $python = (Get-Command python.exe -ErrorAction Stop).Source }
$python = [string]($python | Select-Object -Last 1)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Installed Python executable not found"
}
& $python -c "import sys; assert sys.version_info >= (3,12)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 or newer is required" }
$taskName = "Director-UE-Interactive-Hero"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Task already exists. Refusing to overwrite an existing identity."
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('-B "' + $runner + '" --interactive-hero-runner') -WorkingDirectory $programDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$principal = New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
# Only a fixed reviewed script, task name and windows account. No task
# parameters, user credentials or remote executable/command fields exist.
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Director: allowlisted Epic MetaHuman rig in this logged-in user's session" -ErrorAction Stop | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ([string]$registered.Principal.UserId -ne [string]$identity.User.Value -or
    [string]$registered.Principal.LogonType -ne "Interactive") {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    throw "Interactive Windows principal verification failed; task disabled"
}
Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
Write-Host "Director interactive hero runner registered under $($identity.Name)"
Write-Host "Windows RDP session=$session, account SID matches task principal."
Write-Host "No passwords stored. Main Worker and UE assets untouched."
Write-Host "Read worker.interactive_hero_runner for live readiness."

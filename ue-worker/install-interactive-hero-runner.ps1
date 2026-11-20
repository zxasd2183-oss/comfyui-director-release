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
if ($installed -notmatch '"worker_version":\s*"2\.3\.(7|8)"') {
    throw "Install signed Worker 2.3.7 or 2.3.8 before enabling interactive execution"
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
# Task Scheduler can persist a principal as ACCOUNT\Name even when
# New-ScheduledTaskPrincipal was given a SID. Compare resolved SIDs, not
# string representations. COM task logon type 3 = InteractiveToken.
function Get-DirectorTaskSid([string]$rawId) {
    if ([string]::IsNullOrWhiteSpace($rawId)) { return $null }
    if ($rawId -match '^S-1-[0-9-]+$') { return $rawId }
    try {
        $name = New-Object System.Security.Principal.NTAccount($rawId)
        return $name.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch [System.Security.Principal.IdentityNotMappedException] {
        return $null
    }
}
function Test-DirectorHeroTask([string]$name, [string]$expectedSid,
                                [string]$expectedPython,
                                [string]$expectedRunner,
                                [string]$expectedProgramDir,
                                [string]$expectedUserName) {
    $scheduler = New-Object -ComObject Schedule.Service
    $scheduler.Connect()
    $definition = $scheduler.GetFolder('\').GetTask($name).Definition
    $taskSid = Get-DirectorTaskSid ([string]$definition.Principal.UserId)
    if ($taskSid -ne $expectedSid) { return 'principal_account_mismatch' }
    if ([int]$definition.Principal.LogonType -ne 3) {
        return 'principal_not_interactive_token'
    }
    if ([int]$definition.Principal.RunLevel -ne 0) {
        return 'principal_elevation_mismatch'
    }
    if ([int]$definition.Actions.Count -ne 1) {
        return 'unexpected_action_count'
    }
    $actual = $definition.Actions.Item(1)
    if ([int]$actual.Type -ne 0 -or
        [string]$actual.Path -ine $expectedPython -or
        [string]$actual.Arguments -cne ('-B "' + $expectedRunner + '" --interactive-hero-runner') -or
        [string]$actual.WorkingDirectory -ine $expectedProgramDir) {
        return 'unexpected_task_action'
    }
    if ([int]$definition.Triggers.Count -ne 1) {
        return 'unexpected_trigger_count'
    }
    $trigger = $definition.Triggers.Item(1)
    if ([int]$trigger.Type -ne 9 -or
        (Get-DirectorTaskSid ([string]$trigger.UserId)) -ne $expectedSid) {
        return 'unexpected_logon_trigger'
    }
    if ([string]$definition.RegistrationInfo.Description -cne
        "Director: allowlisted Epic MetaHuman rig in this logged-in user's session") {
        return 'unexpected_task_description'
    }
    return 'verified'
}

$taskName = "Director-UE-Interactive-Hero"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$createdNow = $false
if (-not $existing) {
    $action = New-ScheduledTaskAction -Execute $python -Argument ('-B "' + $runner + '" --interactive-hero-runner') -WorkingDirectory $programDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
    # Only a fixed reviewed script, task name and windows account. No task
    # parameters, user credentials or remote executable/command fields exist.
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Director: allowlisted Epic MetaHuman rig in this logged-in user's session" -ErrorAction Stop | Out-Null
    $createdNow = $true
}
# Repair ONLY the previously created exact task, even if it was disabled
# by the old false-negative SID/string comparison. Never overwrite an
# unknown task, rotate a credential, modify any Worker task, or elevate.
$verification = Test-DirectorHeroTask $taskName $identity.User.Value $python $runner $programDir $identity.Name
if ($verification -cne 'verified') {
    if ($createdNow) {
        Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    }
    throw "Interactive hero task verification failed ($verification). Existing task unchanged."
}
$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($registered.State -eq 'Disabled') {
    Enable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
}
Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
Write-Host "Director interactive hero runner registered under $($identity.Name)"
Write-Host "Windows RDP session=$session, account SID matches task principal."
Write-Host "No passwords stored. Main Worker and UE assets untouched."
Write-Host "Read worker.interactive_hero_runner for live readiness."

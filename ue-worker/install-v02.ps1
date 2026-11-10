# Upgrade the dedicated Windows UE Worker; no SSH or VPS changes.
# Administrative bootstrap only. UE itself runs as non-admin DirectorUEWorker.
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$files = @("agent.py", "ue_jobs.py", "unreal_build_episode.py")
$helper = Join-Path $src "WindowsBootstrap.ps1"
if (-not (Test-Path -LiteralPath $helper)) {
    throw "WindowsBootstrap.ps1 missing: use the complete V0.2 checkout"
}
. $helper

foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $src $name))) {
        throw "Missing bundled trusted file: $name"
    }
}
$dest = Join-Path $env:ProgramData "DirectorUEWorker"
$root = "C:\DirectorVirtualStudio"
$token = Join-Path $dest "worker.token"
$oldTaskName = "Director-UE-Worker"
$taskName = "Director-UE-Worker-V02"
$serviceName = "DirectorUEWorker"
$account = "$env:COMPUTERNAME\$serviceName"
if (-not (Test-Path -LiteralPath $token)) {
    throw "Original V0.1 token not found; refusing to rotate or recreate it"
}
if (-not (Test-Path -LiteralPath (Join-Path $dest "agent.py"))) {
    throw "Original UE Worker files missing"
}
# Fail closed if a real UE commandlet is currently producing assets.
if (@(Get-CimInstance Win32_Process -Filter "Name = 'UnrealEditor-Cmd.exe'").Count -gt 0) {
    throw "Unreal Editor commandlet is running; postpone worker upgrade until job completes"
}

$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    $python = (& $launcher.Source -3 -c "import sys; print(sys.executable)" | Select-Object -Last 1)
} else {
    $python = (& (Get-Command python.exe -ErrorAction Stop).Source -c "import sys; print(sys.executable)" | Select-Object -Last 1)
}
$python = [string]$python
if (-not (Test-Path -LiteralPath $python)) { throw "Python interpreter not accessible" }
& $python -c "import sys; assert sys.version_info >= (3,10)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ required" }
foreach ($name in @("agent.py", "ue_jobs.py", "unreal_build_episode.py")) {
    & $python -m py_compile (Join-Path $src $name)
    if ($LASTEXITCODE -ne 0) { throw "Python syntax validation failed: $name" }
}

$existingUser = Get-LocalUser -Name $serviceName -ErrorAction SilentlyContinue
if ($existingUser -and (-not $existingUser.Enabled)) {
    throw "Existing DirectorUEWorker account disabled; refusing to bypass policy"
}
$newTaskBefore = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingUser -and (-not $newTaskBefore)) {
    throw "Existing runner account without V0.2 task; refusing credential reset"
}
if ($newTaskBefore) {
    if (-not $existingUser) { throw "V0.2 task exists without expected user" }
    $principalId = [string]$newTaskBefore.Principal.UserId
    if (($principalId -ine $account) -and
        ($principalId -ine $existingUser.SID.Value)) {
        throw "V0.2 task principal differs from expected unprivileged account"
    }
}
$oldTask = Get-ScheduledTask -TaskName $oldTaskName -ErrorAction SilentlyContinue
$oldTaskWasEnabled = ($null -ne $oldTask -and $oldTask.State -ne "Disabled")
$newTaskWasEnabled = ($null -ne $newTaskBefore -and $newTaskBefore.State -ne "Disabled")
$oldAction = if ($newTaskBefore) { $newTaskBefore.Actions } else { $null }
$oldTrigger = if ($newTaskBefore) { $newTaskBefore.Triggers } else { $null }
$oldSettings = if ($newTaskBefore) { $newTaskBefore.Settings } else { $null }

New-Item -ItemType Directory -Path $dest -Force | Out-Null
New-Item -ItemType Directory -Path $root -Force | Out-Null
$backup = Join-Path $dest ("backup-pre-v02-" + (Get-Date -Format "yyyyMMddHHmmss"))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
foreach ($name in $files) {
    $previous = Join-Path $dest $name
    if (Test-Path -LiteralPath $previous) {
        Copy-Item -LiteralPath $previous -Destination (Join-Path $backup $name) -Force
    }
}

$createdAccount = $false
$createdTask = $false
$plainPassword = $null
try {
    if (-not $existingUser) {
        $randomBytes = New-Object byte[] 48
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
        $plainPassword = [Convert]::ToBase64String($randomBytes)
        $securePassword = ConvertTo-SecureString $plainPassword -AsPlainText -Force
        New-LocalUser -Name $serviceName -Password $securePassword -PasswordNeverExpires -Description "Director UE non-admin editor runner" | Out-Null
        $createdAccount = $true
        $existingUser = Get-LocalUser -Name $serviceName -ErrorAction Stop
    }
    # Check and grant this single principal's missing batch-logon right;
    # never overwrite another user's privilege entries.
    Grant-DirectorUEBatchLogon -AccountName $serviceName

    # Stop only the two known worker tasks. SSH tunnel is independent.
    if ($newTaskBefore) { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue }
    if ($oldTask) { Stop-ScheduledTask -TaskName $oldTaskName -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    # A stopped scheduled task can leave an orphaned Python process. Kill it
    # only if its SID + command line conclusively match the known worker.
    Stop-DirectorUEPortListener -AgentPath (Join-Path $dest "agent.py") -RunnerSid $existingUser.SID.Value

    foreach ($name in $files) {
        Copy-Item -LiteralPath (Join-Path $src $name) -Destination (Join-Path $dest $name) -Force
    }
    & icacls.exe $dest /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${account}:(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Worker code ACL failed" }
    & icacls.exe $token /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" "${account}:R" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Worker token ACL failed" }
    & icacls.exe $root /grant "${account}:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Workspace ACL failed" }

    $action = New-ScheduledTaskAction -Execute $python -Argument ('-u "' + (Join-Path $dest "agent.py") + '"') -WorkingDirectory $dest
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 30 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    if ($newTaskBefore) {
        # Retain the existing protected credential rather than requesting,
        # logging, or resetting the account password on every upgrade.
        Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
        Enable-ScheduledTask -TaskName $taskName | Out-Null
    } else {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User $account -Password $plainPassword -Force | Out-Null
        $createdTask = $true
    }
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop

    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        try {
            $secret = [IO.File]::ReadAllText($token).Trim()
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:19010/v1/status" -Headers @{Authorization = "Bearer $secret"} -TimeoutSec 2
            if ($status.ok -and $status.worker_version -eq "0.2.0") {
                $healthy = $true
                break
            }
        } catch { }
    }
    if (-not $healthy) { throw "V0.2 health probe failed; initiating rollback" }
    if ($oldTask) {
        Disable-ScheduledTask -TaskName $oldTaskName | Out-Null
    }
    Write-Host "UE Worker V0.2 healthy; dedicated account=$account. Backup: $backup"
    Write-Host "SSH tunnel, original bearer token and VPS service configuration unchanged."
} catch {
    $failure = $_
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($createdTask) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } elseif ($newTaskBefore) {
        try {
            Set-ScheduledTask -TaskName $taskName -Action $oldAction -Trigger $oldTrigger -Settings $oldSettings | Out-Null
        } catch {
            Write-Warning "Could not restore previous V0.2 task properties"
        }
    }
    try {
        Stop-DirectorUEPortListener -AgentPath (Join-Path $dest "agent.py") -RunnerSid $existingUser.SID.Value
    } catch {
        Write-Warning "Port 19010 still needs manual inspection"
    }
    foreach ($name in $files) {
        $original = Join-Path $backup $name
        $target = Join-Path $dest $name
        if (Test-Path -LiteralPath $original) {
            Copy-Item -LiteralPath $original -Destination $target -Force
        } else {
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        }
    }
    if ($newTaskBefore -and $newTaskWasEnabled) {
        Enable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
        Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    } elseif ($oldTask -and $oldTaskWasEnabled) {
        Enable-ScheduledTask -TaskName $oldTaskName -ErrorAction SilentlyContinue | Out-Null
        Start-ScheduledTask -TaskName $oldTaskName -ErrorAction SilentlyContinue
    }
    if ($createdAccount -and $createdTask) {
        # Do not delete a user that may have begun owning project assets.
        Write-Warning "Dedicated user retained for inspection after failed setup."
    }
    throw $failure
} finally {
    Remove-Variable plainPassword -ErrorAction SilentlyContinue
    Remove-Variable securePassword -ErrorAction SilentlyContinue
}

# Windows-only bootstrap helpers for Director UE Worker.
# Administrative use only; no SSH/VPS/network configuration changes.

function Grant-DirectorUEBatchLogon {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$AccountName)
    $principal = Get-LocalUser -Name $AccountName -ErrorAction Stop
    $sid = $principal.SID.Value
    if (-not $sid.StartsWith("S-1-5-21-")) {
        throw "Unexpected local account SID"
    }
    $folder = Join-Path $env:TEMP ("director-ue-rights-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
    $original = Join-Path $folder "rights-before.inf"
    $updated = Join-Path $folder "rights-after.inf"
    $verified = Join-Path $folder "rights-verified.inf"
    $database = Join-Path $folder "security.sdb"
    try {
        & secedit.exe /export /cfg $original /areas USER_RIGHTS /quiet | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "secedit export failed" }
        $lines = @(Get-Content -LiteralPath $original -Encoding Unicode -ErrorAction Stop)
        $sectionIndex = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*\[Privilege Rights\]\s*$') {
                $sectionIndex = $i
                break
            }
        }
        if ($sectionIndex -lt 0) { throw "Missing Privilege Rights section" }

        $required = "*" + $sid
        # A direct deny takes precedence over a grant; refuse to bypass policy.
        foreach ($line in $lines) {
            if ($line -match '^\s*SeDenyBatchLogonRight\s*=\s*(.*)$') {
                $denied = @($Matches[1].Split(',') | ForEach-Object { $_.Trim() })
                if ($denied -contains $required -or $denied -contains $sid) {
                    throw "Account explicitly denied batch logon by local policy"
                }
            }
        }

        $found = $false
        for ($i = $sectionIndex + 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*\[') { break }
            if ($lines[$i] -match '^\s*SeBatchLogonRight\s*=\s*(.*)$') {
                $found = $true
                $entries = @($Matches[1].Split(',') |
                    ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
                if (($entries -notcontains $required) -and ($entries -notcontains $sid)) {
                    $entries += $required
                    $lines[$i] = "SeBatchLogonRight = " + ($entries -join ",")
                } else {
                    Write-Host "SeBatchLogonRight already assigned."
                    return
                }
                break
            }
        }
        if (-not $found) {
            $before = @($lines[0..$sectionIndex])
            $after = if ($sectionIndex -lt $lines.Count - 1) {
                @($lines[($sectionIndex + 1)..($lines.Count - 1)])
            } else { @() }
            $lines = @($before) + @("SeBatchLogonRight = $required") + @($after)
        }

        # Only add this user's SID to exported batch-logon rights.
        Set-Content -LiteralPath $updated -Value $lines -Encoding Unicode
        & secedit.exe /configure /db $database /cfg $updated /areas USER_RIGHTS /quiet | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "secedit configure failed" }
        & secedit.exe /export /cfg $verified /areas USER_RIGHTS /quiet | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "secedit verification export failed" }
        $resultLines = @(Get-Content -LiteralPath $verified -Encoding Unicode)
        $grantLines = @($resultLines | Where-Object { $_ -match '^\s*SeBatchLogonRight\s*=' })
        if ($grantLines.Count -ne 1) { throw "Could not verify batch-logon right" }
        $members = @((($grantLines[0] -split '=', 2)[1]).Split(',') |
            ForEach-Object { $_.Trim() })
        if (($members -notcontains $required) -and ($members -notcontains $sid)) {
            throw "Batch-logon grant was not persisted"
        }
        Write-Host "SeBatchLogonRight granted and verified for $AccountName."
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Stop-DirectorUEPortListener {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$AgentPath,
        [Parameter(Mandatory = $true)][string]$RunnerSid
    )
    $expectedPath = [IO.Path]::GetFullPath($AgentPath)
    $expectedArg = [regex]::Escape($expectedPath)
    $allowedOwners = @("S-1-5-18", $RunnerSid)
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 19010 -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) { return }
        foreach ($connection in $listeners) {
            if ($connection.LocalAddress -ne "127.0.0.1") {
                throw "TCP 19010 has a non-loopback listener; refusing to touch it"
            }
            $processId = [int]$connection.OwningProcess
            $process = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $processId)
            if (-not $process) { throw "Could not inspect port owner" }
            $command = [string]$process.CommandLine
            $ownerResult = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
            $ownerSid = [string]$ownerResult.Sid
            $matchesAgent = ($command -match ('(?i)(^|\s|")' + $expectedArg + '("|\s|$)'))
            if ((-not $matchesAgent) -or ($allowedOwners -notcontains $ownerSid)) {
                throw "Unrecognized process on 127.0.0.1:19010 (PID $processId); refusing to kill"
            }
            Stop-Process -Id $processId -Force -ErrorAction Stop
        }
        Start-Sleep -Milliseconds 500
    }
    if (@(Get-NetTCPConnection -State Listen -LocalPort 19010 -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "Worker port 19010 did not become free"
    }
}

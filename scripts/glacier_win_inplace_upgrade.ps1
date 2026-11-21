# Windows GitHub-hosted clean runner ONLY; no production data or user devices.
$ErrorActionPreference = 'Stop'
$folder = Join-Path $env:RUNNER_TEMP 'glacier-official-upgrade'
$oldDir = Join-Path $folder 'old'
$newDir = Join-Path $folder 'new'
New-Item -ItemType Directory -Force -Path $oldDir, $newDir | Out-Null
gh release download glacier-v0.20.34 --repo $env:GITHUB_REPOSITORY --pattern 'GlacierBrowser-v0.20.34-Windows-Setup-x64.exe' --dir $oldDir
if ($LASTEXITCODE -ne 0) { throw 'Could not download official Windows 0.20.34' }
gh release download glacier-v0.20.35 --repo $env:GITHUB_REPOSITORY --pattern 'GlacierBrowser-v0.20.35-Windows-Setup-x64.exe' --dir $newDir
if ($LASTEXITCODE -ne 0) { throw 'Could not download official Windows 0.20.35' }
$old = Join-Path $oldDir 'GlacierBrowser-v0.20.34-Windows-Setup-x64.exe'
$new = Join-Path $newDir 'GlacierBrowser-v0.20.35-Windows-Setup-x64.exe'
if ((Get-Item $old).Length -ne 175970856 -or (Get-Item $new).Length -ne 176328874) { throw 'Windows installer file size mismatch' }
if ((Get-FileHash $old -Algorithm SHA256).Hash.ToLowerInvariant() -cne '7954c7551d43446b6c6acffd9b07d90bb4bf086aa44e351f288bd26aeacbcb5f') { throw 'Windows old SHA256 mismatch' }
if ((Get-FileHash $new -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'd90c43d727f0dad3e89eb97af7b4e1ae5b6df1ddb8cbd2dac04f5eb4894a724e') { throw 'Windows new SHA256 mismatch' }
$app = Join-Path $env:LOCALAPPDATA 'Programs\GlacierBrowser\GlacierBrowser.exe'
$data = Join-Path $env:LOCALAPPDATA 'GlacierBrowser'
$marker = Join-Path $data '.glacier-ci-upgrade-marker'
function Install-Glacier([string]$installer) {
    # Inno may launch GlacierBrowser after silent installation. Waiting for the
    # entire descendant process tree would hang on its setup/login window.
    # Wait for Setup's own process ONLY, then stop the CI-launched browser.
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $installer
    $psi.Arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    if ($null -eq $p) { throw 'Could not start Inno Setup process' }
    if (-not $p.WaitForExit(360000)) {
        $p.Kill($true)
        throw 'Inno Setup exceeded bounded six-minute wait'
    }
    if ($p.ExitCode -ne 0) { throw "Inno Setup failed with code $($p.ExitCode)" }
    Get-Process -Name GlacierBrowser -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Install-Glacier $old
if (-not (Test-Path -LiteralPath $app)) { throw 'Old Glacier executable not installed' }
$oldExe = (Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $data -Force | Out-Null
[IO.File]::WriteAllText($marker,'synthetic-qa-data-preserve-2026')
Install-Glacier $new
if (-not (Test-Path -LiteralPath $app)) { throw 'New Glacier executable missing after upgrade' }
$newExe = (Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash
if ($oldExe -ceq $newExe) { throw 'Glacier executable did not change during upgrade' }
if ([IO.File]::ReadAllText($marker) -cne 'synthetic-qa-data-preserve-2026') { throw 'Windows local profile marker lost during upgrade' }
Add-Type -AssemblyName System.Drawing
$icon = [System.Drawing.Icon]::ExtractAssociatedIcon($app)
if ($null -eq $icon -or $icon.Width -lt 16) { throw 'Windows executable icon missing' }
Write-Host 'PASS original installer SHA256; native Windows 0.20.34 -> 0.20.35 Inno upgrade, icon, and synthetic local profile retained'

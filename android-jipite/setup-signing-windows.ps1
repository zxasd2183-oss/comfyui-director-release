#Requires -Version 5.1
<#
  Jipite Android: one-time owner-controlled signing setup on Windows.
  Run on YOUR trusted Windows PC. No signing passwords or keystore bytes are
  sent to ChatGPT, stdout, GitHub source, or GitHub workflow artifacts.
  Required local commands: JDK 17+ keytool; authenticated GitHub CLI (gh).
  The PKCS12 key stays at $HOME\JipitePrivate\jipite-signing.p12. Back it up!
#>
[CmdletBinding()]
param(
    [string] $Repository = 'zxasd2183-oss/comfyui-director-release'
)
$ErrorActionPreference = 'Stop'
$Alias = 'jipite'
$ClientId = '76fb73a5-fc82-4217-893a-6070eedd16be'
$Package = 'cn.borealos.jipite'
$KeyDirectory = Join-Path $HOME 'JipitePrivate'
$KeyFile = Join-Path $KeyDirectory 'jipite-signing.p12'
$CertFile = Join-Path $KeyDirectory 'jipite-public-cert.der'

function Require-Command([string] $Name, [string] $Guidance) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { throw "Missing $Name. $Guidance" }
    return $cmd.Source
}
function Check-LastExit([string] $Task) {
    if ($LASTEXITCODE -ne 0) { throw "$Task failed. No release APK was claimed." }
}
function Set-GitHubSecret([string] $Gh, [string] $Name, [string] $Value, [string] $Repo) {
    # Write the value directly to gh stdin, without exposing it on command line.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Gh
    $info.Arguments = "secret set $Name --repo $Repo"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardOutput = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    if (-not $process.Start()) { throw "Could not run gh secret set for $Name" }
    try {
        $process.StandardInput.Write($Value)
        $process.StandardInput.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Could not save GitHub secret $Name. Check gh access to $Repo."
        }
    } finally { $process.Dispose() }
}

$keytool = Require-Command 'keytool' 'Install JDK 17 or later and reopen PowerShell.'
$gh = Require-Command 'gh' 'Install GitHub CLI, then reopen PowerShell.'
# gh auth status writes a normal "not logged in" message to stderr.
# With $ErrorActionPreference='Stop', PowerShell 5.1 turns that into a
# terminating NativeCommandError. Catch it so first-run login can proceed.
$githubLoggedIn = $false
try {
    & $gh auth status --hostname github.com 2>$null | Out-Null
    $githubLoggedIn = ($LASTEXITCODE -eq 0)
} catch {
    $githubLoggedIn = $false
}
if (-not $githubLoggedIn) {
    Write-Host 'Please sign in to your GitHub account in the browser.'
    & $gh auth login --hostname github.com --web
    Check-LastExit 'GitHub sign-in'
}

New-Item -ItemType Directory -Path $KeyDirectory -Force | Out-Null
Write-Host 'Private keystore location:' $KeyFile
Write-Host 'Enter a strong NEW password (or the existing keystore password).'
$secure = Read-Host 'Signing password (never sent to ChatGPT)' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
$secure.Dispose()
if ([string]::IsNullOrEmpty($password) -or $password.Length -lt 12) {
    throw 'Use a signing password with at least 12 characters.'
}
$env:JIPITE_SIGNING_STORE_PASSWORD = $password
$env:JIPITE_SIGNING_KEY_PASSWORD = $password
try {
    if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) {
        Write-Host 'Creating one long-lived private Android signing key.'
        & $keytool -genkeypair -storetype PKCS12 -keystore $KeyFile -alias $Alias `
            -keyalg EC -groupname secp256r1 -validity 3650 `
            -dname 'CN=Jipite Android Approval' `
            -storepass:env JIPITE_SIGNING_STORE_PASSWORD `
            -keypass:env JIPITE_SIGNING_KEY_PASSWORD -noprompt
        Check-LastExit 'Key generation'
    } else {
        Write-Host 'Existing keystore found; preserving it for update compatibility.'
    }
    & $keytool -exportcert -alias $Alias -keystore $KeyFile `
        -storepass:env JIPITE_SIGNING_STORE_PASSWORD -file $CertFile | Out-Null
    Check-LastExit 'Public certificate export'

    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $signature = [Convert]::ToBase64String(
            $sha1.ComputeHash([System.IO.File]::ReadAllBytes($CertFile)))
    } finally { $sha1.Dispose() }
    Write-Host ''
    Write-Host 'Microsoft Android package (PUBLIC):' $Package
    Write-Host 'Microsoft Android signature hash (PUBLIC):' $signature
    Write-Host 'Microsoft client ID (PUBLIC):' $ClientId
    $publicFile = Join-Path $KeyDirectory 'Microsoft-Android-public-registration.txt'
    @(
        "Package name: $Package",
        "Signature hash: $signature",
        "Client ID: $ClientId"
    ) | Set-Content -Path $publicFile -Encoding UTF8

    # All sensitive values are handed directly to GitHub Actions Secrets.
    $encoded = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($KeyFile))
    Set-GitHubSecret $gh 'JIPITE_KEYSTORE_BASE64' $encoded $Repository
    $encoded = $null
    Set-GitHubSecret $gh 'JIPITE_SIGNING_STORE_PASSWORD' $password $Repository
    Set-GitHubSecret $gh 'JIPITE_SIGNING_KEY_PASSWORD' $password $Repository
    & $gh variable set JIPITE_SIGNING_KEY_ALIAS --repo $Repository --body $Alias
    Check-LastExit 'GitHub signing alias variable'
    & $gh variable set JIPITE_MS_CLIENT_ID --repo $Repository --body $ClientId
    Check-LastExit 'GitHub Microsoft app variable'
    Write-Host 'Secure GitHub signing configuration saved.'
    & $gh workflow run build-jipite-apk.yml --repo $Repository --ref main -f mode=connected
    Check-LastExit 'Connected APK workflow dispatch'
    Write-Host ''
    Write-Host 'Connected Release workflow dispatched:'
    Write-Host "https://github.com/$Repository/actions/workflows/build-jipite-apk.yml"
    Write-Host 'In Microsoft Entra > App registrations > Jipite > Authentication > Add a platform > Android,'
    Write-Host "enter package $Package and the PUBLIC signature hash printed above."
    Write-Host 'Do not paste the signing password, private P12, or base64 keystore into chat.'
    Write-Host ('Back up the private key securely: ' + $KeyFile)
    Write-Host ('A copy of the public registration values was saved at: ' + $publicFile)
} finally {
    Remove-Item Env:JIPITE_SIGNING_STORE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:JIPITE_SIGNING_KEY_PASSWORD -ErrorAction SilentlyContinue
    $password = $null
    $secure = $null
}

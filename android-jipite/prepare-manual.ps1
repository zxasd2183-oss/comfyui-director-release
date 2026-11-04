# Jipite V0.6 manual approval (no Xiaomi/FCM push) - Windows setup.
# 1. Build manualDebug once with Android Studio to create debug.keystore.
# 2. .\prepare-manual.ps1 -ShowHashOnly
#    Register Android package + printed hash in Microsoft Entra.
# 3. .\prepare-manual.ps1 -MicrosoftClientId "YOUR-APP-GUID" -Build
# Runs locally only. Never touches cloud GPU or mobile pairing secrets.
[CmdletBinding()]
param(
    [switch]$ShowHashOnly,
    [string]$MicrosoftClientId = "",
    [switch]$Build
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Keystore = Join-Path $HOME ".android\debug.keystore"
$ConfigPath = Join-Path $Root "app\src\main\res\raw\msal_config.json"
$ManifestPath = Join-Path $Root "app\src\main\AndroidManifest.xml"
$Package = "cn.borealos.jipite"

$keytool = Get-Command keytool -ErrorAction SilentlyContinue
if ($null -eq $keytool) {
    throw "keytool was not found. Install Android Studio/JDK 17, add JDK bin to PATH."
}
if (-not (Test-Path -LiteralPath $Keystore -PathType Leaf)) {
    throw "Debug keystore not found. Open android-jipite in Android Studio and build manualDebug once; rerun."
}
if (-not (Test-Path -LiteralPath $ConfigPath) -or -not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Android project structure missing."
}

# Exact Microsoft SHA-1 Base64 signing hash from the local debug certificate.
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("jipite-debug-cert-" + [guid]::NewGuid().ToString("N") + ".der")
try {
    & $keytool.Source -exportcert -alias androiddebugkey -keystore $Keystore -storepass android -file $tmp -noprompt | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tmp)) {
        throw "Could not export Android debug cert."
    }
    $certBytes = [IO.File]::ReadAllBytes($tmp)
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try {
        $hash = [Convert]::ToBase64String($sha.ComputeHash($certBytes))
    } finally { $sha.Dispose() }
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
Write-Host "Android package: $Package"
Write-Host "Microsoft Android Signature hash (debug cert): $hash"
Write-Host "Use the same package and hash when adding Android platform in Microsoft Entra."

if ($ShowHashOnly) { return }

$parsedClientId = [guid]::Empty
if (-not [guid]::TryParse($MicrosoftClientId, [ref]$parsedClientId) -or
    $parsedClientId -eq [guid]::Empty) {
    throw "Provide -MicrosoftClientId from YOUR Microsoft app registration."
}
$conf = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$conf.client_id = $parsedClientId.ToString()
$conf.redirect_uri = "msauth://" + $Package + "/" + [Uri]::EscapeDataString($hash)
$conf.broker_redirect_uri_registered = $false
$conf | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
$pathPattern = 'android:path="/[^"]*"'
if ($manifest -notmatch $pathPattern) {
    throw "MSAL BrowserTabActivity redirect Android path not found."
}
$rawPath = [System.Security.SecurityElement]::Escape("/" + $hash)
$manifest = [regex]::Replace($manifest, $pathPattern, ('android:path="' + $rawPath + '"'), 1)
Set-Content -LiteralPath $ManifestPath -Value $manifest -Encoding UTF8

Write-Host "Microsoft personal account login configured for manualDebug."
Write-Host "No Xiaomi AppId, AppSecret, FCM or Google services required."
Write-Host "Do not commit local registration values without reviewing git diff."
if ($Build) {
    Push-Location $Root
    try {
        $gradle = Get-Command gradle -ErrorAction SilentlyContinue
        if ($null -eq $gradle) {
            throw "Gradle not in PATH; build manualDebug from Android Studio."
        }
        & $gradle.Source ':app:assembleManualDebug' '--no-daemon'
        if ($LASTEXITCODE -ne 0) { throw "manualDebug failed. Check Gradle output." }
        $apk = Join-Path $Root 'app\build\outputs\apk\manual\debug\app-manual-debug.apk'
        if (-not (Test-Path -LiteralPath $apk)) { throw "APK output missing." }
        Write-Host "Local APK:" $apk
        Write-Host "The owner's VPS mobile API must be installed for real enrollment/approvals."
    } finally { Pop-Location }
} else {
    Write-Host "Next: Android Studio > Build Variants > manualDebug > Build APK(s)."
}

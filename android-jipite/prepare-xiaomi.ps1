# Prepare official mainland Xiaomi Mi Push AAR and Microsoft MSAL for Debug APK.
# PowerShell 5.1+ / Windows 10+; no cloud GPU calls; no AppSecret on laptop/APK.
#
# Example (ONE line):
# .\prepare-xiaomi.ps1 -AarPath "C:\Downloads\MiPush_SDK_Client_6.x.x.aar" -MicrosoftClientId "GUID" -MicrosoftSigningHash "BASE64_HASH" -MiAppId "XIAOMI_APP_ID" -MiAppKey "XIAOMI_APP_KEY" -Build
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$AarPath,
  [Parameter(Mandatory=$true)][string]$MicrosoftClientId,
  [Parameter(Mandatory=$true)][string]$MicrosoftSigningHash,
  [Parameter(Mandatory=$true)][string]$MiAppId,
  [Parameter(Mandatory=$true)][string]$MiAppKey,
  [switch]$Build
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Package = 'cn.borealos.jipite'
$AarDestination = Join-Path $Root 'app\libs\MiPush_SDK_Client.aar'
$MsalConfig = Join-Path $Root 'app\src\main\res\raw\msal_config.json'
$ManifestPath = Join-Path $Root 'app\src\main\AndroidManifest.xml'
$MiResource = Join-Path $Root 'app\src\xiaomi\res\values\mipush.xml'

if (-not (Test-Path -LiteralPath $AarPath -PathType Leaf)) {
  throw 'Official mainland Mi Push SDK AAR not found; download it from Xiaomi developer console.'
}
$parsedClientId = [guid]::Empty
if (-not [guid]::TryParse($MicrosoftClientId, [ref]$parsedClientId)) {
  throw 'Microsoft ClientId must be a GUID from your app registration.'
}
if ($MicrosoftSigningHash -notmatch '^[A-Za-z0-9+/]{20,128}={0,2}$') {
  throw 'Provide your REAL Android signing SHA1 Base64 hash (unescaped) registered with Microsoft.'
}
if ($MiAppId -notmatch '^[A-Za-z0-9_-]{4,128}$' -or $MiAppKey -notmatch '^[A-Za-z0-9_-]{4,256}$') {
  throw 'Mi AppId/AppKey must come from Xiaomi developer console (NOT the server AppSecret).'
}
if (-not (Test-Path -LiteralPath $MsalConfig) -or -not (Test-Path -LiteralPath $ManifestPath)) {
  throw 'Android project structure not found.'
}

# Verify AAR is a genuine Android archive structure, not an .apk or arbitrary download.
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $AarPath).Path)
try {
  $entries = @($zip.Entries | ForEach-Object { $_.FullName })
  if (-not ($entries -contains 'AndroidManifest.xml') -or -not ($entries -contains 'classes.jar')) {
    throw 'Invalid AAR structure: AndroidManifest.xml or classes.jar is missing.'
  }
  $jarMemory = New-Object System.IO.MemoryStream
  $zip.GetEntry('classes.jar').Open().CopyTo($jarMemory)
  $jarMemory.Position = 0
  $jar = [System.IO.Compression.ZipArchive]::new($jarMemory, [System.IO.Compression.ZipArchiveMode]::Read, $true)
  try {
    $jarNames = @($jar.Entries | ForEach-Object { $_.FullName })
    if (-not ($jarNames -contains 'com/xiaomi/mipush/sdk/MiPushClient.class') -or
        -not ($jarNames -contains 'com/xiaomi/mipush/sdk/PushMessageReceiver.class')) {
      throw 'This AAR does not contain official MiPushClient + PushMessageReceiver classes.'
    }
  }
  finally {
    $jar.Dispose()
    $jarMemory.Dispose()
  }
}
finally {
  $zip.Dispose()
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $AarDestination) | Out-Null
Copy-Item -LiteralPath $AarPath -Destination $AarDestination -Force

$conf = Get-Content -LiteralPath $MsalConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$conf.client_id = $MicrosoftClientId
$conf.redirect_uri = 'msauth://' + $Package + '/' +
                     [Uri]::EscapeDataString($MicrosoftSigningHash)
$conf.broker_redirect_uri_registered = $false
$conf | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $MsalConfig -Encoding UTF8

$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
$pathPattern = 'android:path="/[^"]*"'
if ($manifest -notmatch $pathPattern) {
  throw 'MSAL BrowserTabActivity android:path not found in AndroidManifest.xml.'
}
$escapedHash = [System.Security.SecurityElement]::Escape('/' + $MicrosoftSigningHash)
$manifest = [regex]::Replace($manifest, $pathPattern,
                             ('android:path="' + $escapedHash + '"'), 1)
Set-Content -LiteralPath $ManifestPath -Value $manifest -Encoding UTF8

$xmlId = [System.Security.SecurityElement]::Escape($MiAppId)
$xmlKey = [System.Security.SecurityElement]::Escape($MiAppKey)
$xml = '<' + '?xml version="1.0" encoding="utf-8"?' + '>' + [Environment]::NewLine +
  '<resources><string name="mipush_app_id">' + $xmlId +
  '</string><string name="mipush_app_key">' + $xmlKey +
  '</string></resources>'
Set-Content -LiteralPath $MiResource -Value $xml -Encoding UTF8

Write-Host 'Xiaomi mainland build inputs prepared.'
Write-Host 'Mi Push AAR: app/libs/MiPush_SDK_Client.aar'
Write-Host 'Local AAR SHA256:' (Get-FileHash -LiteralPath $AarDestination -Algorithm SHA256).Hash
Write-Host 'MSAL redirect and Android Manifest: configured for supplied signing hash.'
Write-Host 'Firebase/Google Play Services NOT required for xiaomiDebug.'
Write-Host 'AppSecret must remain ONLY on your VPS.'
Write-Host 'IMPORTANT: Do not commit these locally customized files before reviewing them.'

if ($Build) {
  Push-Location $Root
  try {
    $gradle = Get-Command gradle -ErrorAction SilentlyContinue
    if ($null -eq $gradle) {
      throw 'Gradle not in PATH. Open this folder in Android Studio, sync, then Build > Build APK(s).'
    }
    & $gradle.Source ':app:assembleXiaomiDebug' '--no-daemon'
    if ($LASTEXITCODE -ne 0) { throw 'Gradle Xiaomi APK compilation failed.' }
    $apk = Join-Path $Root 'app\build\outputs\apk\xiaomi\debug\app-xiaomi-debug.apk'
    if (-not (Test-Path -LiteralPath $apk)) { throw 'Expected compiled APK missing.' }
    Write-Host 'TEST APK CREATED:' $apk
    Write-Host 'Android debug certificate MUST match the hash registered at Microsoft.'
  }
  finally { Pop-Location }
}
else {
  Write-Host 'Next: Open android-jipite/ in Android Studio; choose xiaomiDebug and Build APK(s).'
}

# Glacier Android first-time owner-only signing setup (Windows).
# Run locally on a trusted machine with Java JDK + GitHub CLI (gh).
# Never paste the .p12, passwords or base64 into chats or source control.
$ErrorActionPreference = 'Stop'
$repo = 'zxasd2183-oss/comfyui-director-release'
$alias = 'glacier-android'
$folder = Join-Path $env:USERPROFILE '.glacier\android-signing'
$file = Join-Path $folder 'glacier-android-release.p12'

if (-not (Get-Command keytool -ErrorAction SilentlyContinue)) {
    throw 'Java JDK keytool is required.'
}
$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw 'GitHub CLI gh is required; install and authenticate with gh auth login.'
}
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI authorization is not available.' }
New-Item -ItemType Directory -Path $folder -Force | Out-Null

if (-not (Test-Path $file)) {
    Write-Host 'Creating the NEW independent Glacier Android signing keystore.'
    Write-Host 'Choose and back up a strong password; this key must survive future releases.'
    & keytool -genkeypair -alias $alias -keyalg RSA -keysize 3072 -validity 10950 -storetype PKCS12 -keystore $file -dname 'CN=Glacier Android'
    if ($LASTEXITCODE -ne 0) { throw 'Key creation failed. No GitHub secrets were changed.' }
} else {
    Write-Host 'Reusing existing keystore; a new signing identity will NOT be generated.'
}

function Set-GhSecret([string]$name, [string]$value) {
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $gh.Source
    $start.Arguments = "secret set $name --repo $repo"
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "Failed to start gh for $name" }
    try {
        $process.StandardInput.Write($value)
        $process.StandardInput.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Cannot set $name; verify GitHub repository permissions." }
    } finally {
        $process.Dispose()
    }
}

$secure = Read-Host 'Confirm the keystore password (hidden)' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plaintext = $null
try {
    $plaintext = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $env:GLACIER_ANDROID_KEY_CHECK = $plaintext
    & keytool -list -keystore $file -storetype PKCS12 -alias $alias -storepass:env GLACIER_ANDROID_KEY_CHECK *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Incorrect keystore password or alias.' }
    $encoded = [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))
    Set-GhSecret 'GLACIER_ANDROID_KEYSTORE_BASE64' $encoded
    Set-GhSecret 'GLACIER_ANDROID_SIGNING_STORE_PASSWORD' $plaintext
    Set-GhSecret 'GLACIER_ANDROID_SIGNING_KEY_ALIAS' $alias
    Set-GhSecret 'GLACIER_ANDROID_SIGNING_KEY_PASSWORD' $plaintext
} finally {
    Remove-Item Env:\GLACIER_ANDROID_KEY_CHECK -ErrorAction SilentlyContinue
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plaintext = $null
    $secure.Dispose()
}
Write-Host 'Glacier Android signing secrets uploaded to GitHub Actions.'
Write-Host "Private signing key remains on this trusted device: $file"
Write-Host 'Back up this keystore and password offline; losing either breaks future updates.'

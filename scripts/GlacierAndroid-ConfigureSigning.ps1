#Requires -Version 5.1
<#
Glacier Android stable signing: one-time setup on owner's trusted Windows PC.
Never runs in CI, prints secrets or publishes a Release.
Choose and back up the signing password in a password manager FIRST.
Keep offline encrypted backups of BOTH P12 keystore and password.
#>
param([switch]$CheckOnly,[switch]$NoInstall)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repository='zxasd2183-oss/comfyui-director-release'
if($CheckOnly){
  Write-Host 'PASS: signing helper parsed; no keys, login or releases touched.'
  exit 0
}
if([Environment]::OSVersion.Platform -ne 'Win32NT'){throw 'Windows DPAPI is required.'}
function Locate($name,$candidates){
  $found=Get-Command $name -ErrorAction SilentlyContinue
  if($found){return $found.Source}
  foreach($candidate in $candidates){
    if($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)){return $candidate}
  }
  return $null
}
function Bootstrap($name){
  if($NoInstall){throw ('Missing prerequisite: '+$name)}
  $winget=Locate 'winget.exe' @()
  if(-not $winget){throw ('Install '+$name+' from official source and rerun.')}
  & $winget install --id $name --exact --source winget --accept-source-agreements --accept-package-agreements
  if($LASTEXITCODE -ne 0){throw ('Unable to install '+$name)}
}
$gh=Locate 'gh.exe' @((Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\GitHub CLI\gh.exe'))
if(-not $gh){
  Bootstrap 'GitHub.cli'
  $gh=Locate 'gh.exe' @((Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'))
  if(-not $gh){throw 'GitHub CLI not found after installation.'}
}
$javaPaths=@()
if($env:JAVA_HOME){$javaPaths+=Join-Path $env:JAVA_HOME 'bin\keytool.exe'}
$keytool=Locate 'keytool.exe' $javaPaths
if(-not $keytool){
  $javaRoot=Join-Path $env:ProgramFiles 'Eclipse Adoptium'
  if(Test-Path $javaRoot){
    $keytool=Get-ChildItem $javaRoot -Recurse -File -Filter keytool.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
  }
}
if(-not $keytool){
  Bootstrap 'EclipseAdoptium.Temurin.17.JDK'
  $javaRoot=Join-Path $env:ProgramFiles 'Eclipse Adoptium'
  $keytool=Get-ChildItem $javaRoot -Recurse -File -Filter keytool.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
  if(-not $keytool){throw 'Java keytool missing after installation.'}
}
& $gh auth status -h github.com 2>$null | Out-Null
if($LASTEXITCODE -ne 0){
  Write-Host 'Login to YOUR GitHub account. You can open the device-login URL in Glacier Browser.'
  & $gh auth login -h github.com -p https
  if($LASTEXITCODE -ne 0){throw 'GitHub authentication incomplete.'}
}
& $gh repo view $repository --json nameWithOwner | Out-Null
if($LASTEXITCODE -ne 0){throw 'Current account cannot access the Glacier repository.'}
$directory=Join-Path $env:LOCALAPPDATA 'GlacierBrowser\AndroidSigning'
New-Item $directory -ItemType Directory -Force | Out-Null
$principal=$env:USERDOMAIN+'\'+$env:USERNAME
& icacls.exe $directory /inheritance:r /grant:r ($principal+':(OI)(CI)F') | Out-Null
if($LASTEXITCODE -ne 0){throw 'Cannot restrict directory permissions.'}
$store=Join-Path $directory 'GlacierAndroid-release.p12'
$passwordFile=Join-Path $directory 'GlacierAndroid-password.dpapi'
$public=Join-Path $directory 'GlacierAndroid-public.cer'
$alias='glacier-android-release'
if((Test-Path $store) -xor (Test-Path $passwordFile)){throw 'Existing signer/password incomplete. Refusing to rotate signing identity.'}
$password=$null
$encoded=$null
try {
  if(-not (Test-Path $store)){
    Write-Host 'Glacier Android requires ONE permanent signing password.'
    Write-Host 'Generate an ASCII password of at least 24 characters in your password manager.'
    Write-Host 'Keep it with an offline encrypted backup of the .p12 file. GitHub cannot recover it.'
    $first=Read-Host 'Paste your new signing password (hidden)' -AsSecureString
    $second=Read-Host 'Paste the same password again (hidden)' -AsSecureString
    $ptr1=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($first)
    $ptr2=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($second)
    try {
      $password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr1)
      $confirm=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)
    } finally {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
    }
    if($password.Length -lt 24 -or $password -cne $confirm -or
        $password -cnotmatch '^[!-~]+
    & $keytool -genkeypair -noprompt -storetype PKCS12 -keystore $store -alias $alias -keyalg RSA -keysize 3072 -sigalg SHA256withRSA -validity 7300 -dname 'CN=Glacier Browser Android, O=Glacier Browser' -storepass:env GLACIER_ANDROID_LOCAL_PASS -keypass:env GLACIER_ANDROID_LOCAL_PASS
    if($LASTEXITCODE -ne 0){throw 'Creating the independent signing key failed.'}
    $secure=ConvertTo-SecureString $password -AsPlainText -Force
    ConvertFrom-SecureString $secure | Set-Content $passwordFile -Encoding ASCII
    foreach($p in @($store,$passwordFile)){
      & icacls.exe $p /inheritance:r /grant:r ($principal+':F') | Out-Null
      if($LASTEXITCODE -ne 0){throw 'Cannot restrict signing-file ACL.'}
    }
  } else {
    $secure=Get-Content $passwordFile -Raw | ConvertTo-SecureString
    $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try{$password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
    $env:GLACIER_ANDROID_LOCAL_PASS=$password
  }
  & $keytool -exportcert -storetype PKCS12 -keystore $store -alias $alias -file $public -storepass:env GLACIER_ANDROID_LOCAL_PASS
  if($LASTEXITCODE -ne 0){throw 'Exporting public certificate failed.'}
  $sha=(Get-FileHash $public -Algorithm SHA256).Hash.ToLowerInvariant()
  if($sha -notmatch '^[0-9a-f]{64}$'){throw 'Invalid certificate fingerprint.'}
  $encoded=[Convert]::ToBase64String([IO.File]::ReadAllBytes($store))
  $encoded | & $gh secret set GLACIER_ANDROID_KEYSTORE_BASE64 --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload keystore Secret.'}
  $password | & $gh secret set GLACIER_ANDROID_SIGNING_STORE_PASSWORD --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload store-password Secret.'}
  $password | & $gh secret set GLACIER_ANDROID_SIGNING_KEY_PASSWORD --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload key-password Secret.'}
  & $gh variable set GLACIER_ANDROID_SIGNING_KEY_ALIAS --repo $repository --body $alias
  if($LASTEXITCODE -ne 0){throw 'Unable to set signing alias variable.'}
  & $gh variable set GLACIER_ANDROID_CERT_SHA256 --repo $repository --body $sha
  if($LASTEXITCODE -ne 0){throw 'Unable to set public certificate SHA256 variable.'}
  Write-Host 'SUCCESS: dedicated Android signing configured with GitHub Actions Secrets.'
  Write-Host ('Public cert SHA256: '+$sha)
  Write-Host ('Protected local signing folder: '+$directory)
  Write-Warning 'Keep your chosen password in your password manager AND an encrypted offline backup of the P12.'
  Write-Warning 'The DPAPI password file cannot be recovered from another Windows account or after reinstall.'
  Write-Host 'No APK or Release was published.'
} finally {
  Remove-Item Env:\GLACIER_ANDROID_LOCAL_PASS -ErrorAction SilentlyContinue
  $password=$null
  $encoded=$null
}
){
      throw 'Password must match, have 24+ printable ASCII characters, and be safely backed up.'
    }
    $confirm=$null
    $env:GLACIER_ANDROID_LOCAL_PASS=$password
    & $keytool -genkeypair -noprompt -storetype PKCS12 -keystore $store -alias $alias -keyalg RSA -keysize 3072 -sigalg SHA256withRSA -validity 7300 -dname 'CN=Glacier Browser Android, O=Glacier Browser' -storepass:env GLACIER_ANDROID_LOCAL_PASS -keypass:env GLACIER_ANDROID_LOCAL_PASS
    if($LASTEXITCODE -ne 0){throw 'Creating the independent signing key failed.'}
    $secure=ConvertTo-SecureString $password -AsPlainText -Force
    ConvertFrom-SecureString $secure | Set-Content $passwordFile -Encoding ASCII
    foreach($p in @($store,$passwordFile)){
      & icacls.exe $p /inheritance:r /grant:r ($principal+':F') | Out-Null
      if($LASTEXITCODE -ne 0){throw 'Cannot restrict signing-file ACL.'}
    }
  } else {
    $secure=Get-Content $passwordFile -Raw | ConvertTo-SecureString
    $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try{$password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
    $env:GLACIER_ANDROID_LOCAL_PASS=$password
  }
  & $keytool -exportcert -storetype PKCS12 -keystore $store -alias $alias -file $public -storepass:env GLACIER_ANDROID_LOCAL_PASS
  if($LASTEXITCODE -ne 0){throw 'Exporting public certificate failed.'}
  $sha=(Get-FileHash $public -Algorithm SHA256).Hash.ToLowerInvariant()
  if($sha -notmatch '^[0-9a-f]{64}$'){throw 'Invalid certificate fingerprint.'}
  $encoded=[Convert]::ToBase64String([IO.File]::ReadAllBytes($store))
  $encoded | & $gh secret set GLACIER_ANDROID_KEYSTORE_BASE64 --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload keystore Secret.'}
  $password | & $gh secret set GLACIER_ANDROID_SIGNING_STORE_PASSWORD --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload store-password Secret.'}
  $password | & $gh secret set GLACIER_ANDROID_SIGNING_KEY_PASSWORD --repo $repository
  if($LASTEXITCODE -ne 0){throw 'Unable to upload key-password Secret.'}
  & $gh variable set GLACIER_ANDROID_SIGNING_KEY_ALIAS --repo $repository --body $alias
  if($LASTEXITCODE -ne 0){throw 'Unable to set signing alias variable.'}
  & $gh variable set GLACIER_ANDROID_CERT_SHA256 --repo $repository --body $sha
  if($LASTEXITCODE -ne 0){throw 'Unable to set public certificate SHA256 variable.'}
  Write-Host 'SUCCESS: dedicated Android signing configured with GitHub Actions Secrets.'
  Write-Host ('Public cert SHA256: '+$sha)
  Write-Host ('Protected local signing folder: '+$directory)
  Write-Warning 'Back up the P12 AND its password separately in an encrypted offline vault.'
  Write-Warning 'The DPAPI password file cannot be recovered from another Windows account or after reinstall.'
  Write-Host 'No APK or Release was published.'
} finally {
  Remove-Item Env:\GLACIER_ANDROID_LOCAL_PASS -ErrorAction SilentlyContinue
  $password=$null
  $encoded=$null
}

# Read-only Windows PowerShell checker for an installed Glacier APK and a candidate APK.
# Requires Android platform-tools (adb) and Android build-tools (apksigner, aapt).
# Does not install, uninstall, export app data, or change device state.
param(
  [Parameter(Mandatory=$true)][string]$CandidateApk,
  [string]$PackageName = 'cn.borealos.glacier.geckopreview',
  [string]$Adb = 'adb',
  [string]$ApkSigner = 'apksigner',
  [string]$Aapt = 'aapt'
)
$ErrorActionPreference = 'Stop'
function Run-Tool([string]$Tool, [string[]]$ArgList) {
  $output = & $Tool @ArgList 2>&1
  if ($LASTEXITCODE -ne 0) { throw "$Tool failed: $output" }
  return ($output -join "`n")
}
function CertHash([string]$File) {
  $output = Run-Tool $ApkSigner @('verify','--print-certs',$File)
  $matchesFound = [regex]::Matches($output, '(?m)^Signer #(\d+) certificate SHA-256 digest:\s*([a-fA-F0-9]{64})\s*
}
$fullCandidate = (Resolve-Path -LiteralPath $CandidateApk).Path
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('glacier-sign-check-' + [guid]::NewGuid().ToString('N'))
New-Item -Path $tempDir -ItemType Directory | Out-Null
try {
  $remotePaths = Run-Tool $Adb @('shell','pm','path',$PackageName)
  $base = @($remotePaths -split "`r?`n" | Where-Object { $_ -match '^package:(.+/base\.apk)$' } | Select-Object -First 1)
  if (-not $base) { throw "Glacier is not installed, or base.apk cannot be located. Refusing to infer compatibility." }
  $remote = $base[0].Substring(8).Trim()
  $installed = Join-Path $tempDir 'installed-base.apk'
  [void](Run-Tool $Adb @('pull',$remote,$installed))
  $oldHash = CertHash $installed
  $newHash = CertHash $fullCandidate
  $installedInfo = Run-Tool $Aapt @('dump','badging',$installed)
  $candidateInfo = Run-Tool $Aapt @('dump','badging',$fullCandidate)
  $manifestPattern = "package: name='([^']+)' versionCode='(\d+)'"
  $oldMatch = [regex]::Match($installedInfo, $manifestPattern)
  $pkgMatch = [regex]::Match($candidateInfo, $manifestPattern)
  if (-not $oldMatch.Success -or -not $pkgMatch.Success) { throw 'Cannot verify both APK manifests. Blocking upgrade.' }
  if ($oldMatch.Groups[1].Value -ne $PackageName) { throw 'Installed base APK package differs from requested package. Blocking upgrade.' }
  $oldCode = [int64]$oldMatch.Groups[2].Value
  $newCode = [int64]$pkgMatch.Groups[2].Value
  $samePackage = $pkgMatch.Groups[1].Value -eq $PackageName
  $sameCert = $oldHash -eq $newHash
  $newer = $newCode -gt $oldCode
  Write-Output "Installed package: $PackageName (versionCode=$oldCode)"
  Write-Output "Candidate package: $($pkgMatch.Groups[1].Value) (versionCode=$newCode)"
  Write-Output "Installed signing SHA256: $oldHash"
  Write-Output "Candidate signing SHA256: $newHash"
  Write-Output "Package match: $samePackage; signer match: $sameCert; version increases: $newer"
  if ($samePackage -and $sameCert -and $newer) {
    Write-Output 'PASS: basic in-place upgrade identity checks pass. This does not guarantee installation or data migration.'
  } else {
    Write-Output 'BLOCK: do not install over existing Glacier or uninstall it. Preserve existing encrypted data.'
    exit 2
  }
} finally {
  Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
)
  if ($matchesFound.Count -ne 1 -or $matchesFound[0].Groups[1].Value -ne '1') {
    throw "Expected exactly one verified APK signing certificate: $File"
  }
  return $matchesFound[0].Groups[2].Value.ToLowerInvariant()
}
$fullCandidate = (Resolve-Path -LiteralPath $CandidateApk).Path
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('glacier-sign-check-' + [guid]::NewGuid().ToString('N'))
New-Item -Path $tempDir -ItemType Directory | Out-Null
try {
  $remotePaths = Run-Tool $Adb @('shell','pm','path',$PackageName)
  $base = @($remotePaths -split "`r?`n" | Where-Object { $_ -match '^package:(.+/base\.apk)$' } | Select-Object -First 1)
  if (-not $base) { throw "Glacier is not installed, or base.apk cannot be located. Refusing to infer compatibility." }
  $remote = $base[0].Substring(8).Trim()
  $installed = Join-Path $tempDir 'installed-base.apk'
  [void](Run-Tool $Adb @('pull',$remote,$installed))
  $oldHash = CertHash $installed
  $newHash = CertHash $fullCandidate
  $packageInfo = Run-Tool $Adb @('shell','dumpsys','package',$PackageName)
  $oldMatch = [regex]::Match($packageInfo, '(?m)^\s*versionCode=(\d+)')
  $candidateInfo = Run-Tool $Aapt @('dump','badging',$fullCandidate)
  $pkgMatch = [regex]::Match($candidateInfo, "package: name='([^']+)' versionCode='(\d+)'")
  if (-not $oldMatch.Success -or -not $pkgMatch.Success) { throw 'Could not verify version and package; refusing to infer compatibility.' }
  $oldCode = [int64]$oldMatch.Groups[1].Value
  $newCode = [int64]$pkgMatch.Groups[2].Value
  $samePackage = $pkgMatch.Groups[1].Value -eq $PackageName
  $sameCert = $oldHash -eq $newHash
  $newer = $newCode -gt $oldCode
  Write-Output "Installed package: $PackageName (versionCode=$oldCode)"
  Write-Output "Candidate package: $($pkgMatch.Groups[1].Value) (versionCode=$newCode)"
  Write-Output "Installed signing SHA256: $oldHash"
  Write-Output "Candidate signing SHA256: $newHash"
  Write-Output "Package match: $samePackage; signer match: $sameCert; version increases: $newer"
  if ($samePackage -and $sameCert -and $newer) {
    Write-Output 'PASS: basic in-place upgrade identity checks pass. This does not guarantee installation or data migration.'
  } else {
    Write-Output 'BLOCK: do not install over existing Glacier or uninstall it. Preserve existing encrypted data.'
    exit 2
  }
} finally {
  Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Read-only Glacier Android upgrade identity check (Windows PowerShell).
# Requires adb, apksigner, aapt; does not install, uninstall or modify device data.
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
  return ($output -join [Environment]::NewLine)
}
function CertHash([string]$File) {
  $output = Run-Tool $ApkSigner @('verify','--print-certs',$File)
  $signers = [regex]::Matches($output, '(?m)^Signer #(\d+) certificate SHA-256 digest:\s*([a-fA-F0-9]{64})\s*$')
  if ($signers.Count -ne 1 -or $signers[0].Groups[1].Value -ne '1') {
    throw "Expected exactly one verified APK signer: $File"
  }
  return $signers[0].Groups[2].Value.ToLowerInvariant()
}
function ApkIdentity([string]$File) {
  $badging = Run-Tool $Aapt @('dump','badging',$File)
  $parsed = [regex]::Match($badging, "package: name='([^']+)' versionCode='(\d+)'")
  if (-not $parsed.Success) { throw "Cannot parse APK identity: $File" }
  return @{ Package = $parsed.Groups[1].Value; VersionCode = [int64]$parsed.Groups[2].Value }
}
$fullCandidate = (Resolve-Path -LiteralPath $CandidateApk).Path
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('glacier-sign-check-' + [guid]::NewGuid().ToString('N'))
New-Item -Path $tempDir -ItemType Directory | Out-Null
try {
  $remotePaths = Run-Tool $Adb @('shell','pm','path',$PackageName)
  $base = @($remotePaths -split '\r?\n' | Where-Object { $_ -match '^package:(.+/base\.apk)$' } | Select-Object -First 1)
  if (-not $base) { throw "Installed Glacier base.apk not found; cannot establish upgrade compatibility." }
  $remote = $base[0].Substring(8).Trim()
  $installed = Join-Path $tempDir 'installed-base.apk'
  [void](Run-Tool $Adb @('pull',$remote,$installed))
  $installedIdentity = ApkIdentity $installed
  $candidateIdentity = ApkIdentity $fullCandidate
  $installedHash = CertHash $installed
  $candidateHash = CertHash $fullCandidate
  $samePackage = $installedIdentity.Package -ceq $PackageName -and $candidateIdentity.Package -ceq $PackageName
  $sameCertificate = $installedHash -ceq $candidateHash
  $versionIncreases = $candidateIdentity.VersionCode -gt $installedIdentity.VersionCode
  Write-Output "Installed: $($installedIdentity.Package), versionCode=$($installedIdentity.VersionCode)"
  Write-Output "Candidate: $($candidateIdentity.Package), versionCode=$($candidateIdentity.VersionCode)"
  Write-Output "Installed certificate SHA-256: $installedHash"
  Write-Output "Candidate certificate SHA-256: $candidateHash"
  Write-Output "Same package: $samePackage; same certificate: $sameCertificate; newer version: $versionIncreases"
  if (-not ($samePackage -and $sameCertificate -and $versionIncreases)) {
    Write-Output 'BLOCK: do not uninstall Glacier or attempt this APK as a direct upgrade.'
    exit 2
  }
  Write-Output 'PASS: basic signing and version checks passed; installation/data preservation still require device testing.'
} finally {
  Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

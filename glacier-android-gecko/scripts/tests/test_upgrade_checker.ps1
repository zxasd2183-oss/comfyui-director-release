# Deterministic mock CLI tests of the read-only compatibility gate; never touch a phone.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$checker = Join-Path $root 'check_installed_apk_upgrade.ps1'
$adb = Join-Path $PSScriptRoot 'mock_upgrade_adb.ps1'
$aapt = Join-Path $PSScriptRoot 'mock_upgrade_aapt.ps1'
$signer = Join-Path $PSScriptRoot 'mock_upgrade_apksigner.ps1'
$temp = Join-Path ([IO.Path]::GetTempPath()) ('glacier-upgrade-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
  $env:MOCK_OLD_APK = Join-Path $temp 'original.apk'
  $candidate = Join-Path $temp 'candidate.apk'
  [IO.File]::WriteAllText($env:MOCK_OLD_APK, 'mock old apk')
  [IO.File]::WriteAllText($candidate, 'mock candidate apk')
  function Case([string]$Name, [string]$NewVersion, [string]$NewPackage, [string]$DifferentCert, [string]$InvalidSignature, [string]$ExtraSigner, [bool]$ExpectedPass) {
    $env:MOCK_NEW_VERSION = $NewVersion
    $env:MOCK_NEW_PACKAGE = $NewPackage
    $env:MOCK_DIFFERENT_CERT = $DifferentCert
    $env:MOCK_INVALID_SIGNATURE = $InvalidSignature
    $env:MOCK_EXTRA_SIGNER = $ExtraSigner
    $output = & pwsh -NoProfile -NonInteractive -File $checker -CandidateApk $candidate -Adb $adb -Aapt $aapt -ApkSigner $signer 2>&1
    $status = $LASTEXITCODE
    if ($ExpectedPass -and ($status -ne 0 -or (($output -join ' ') -notmatch 'PASS:'))) {
      throw "Unexpected failure: $Name (exit $status): $output"
    }
    if (-not $ExpectedPass -and ($status -eq 0 -or (($output -join ' ') -match 'PASS:'))) {
      throw "Unsafe success: $Name (exit $status): $output"
    }
    Write-Host "PASS scenario: $Name (exit $status)"
  }
  $pkg = 'cn.borealos.glacier.geckopreview'
  Case 'matching signer and newer version' '10' $pkg '0' '0' '0' $true
  Case 'different signer' '10' $pkg '1' '0' '0' $false
  Case 'same version' '9' $pkg '0' '0' '0' $false
  Case 'downgrade' '8' $pkg '0' '0' '0' $false
  Case 'wrong package' '10' 'com.example.other' '0' '0' '0' $false
  Case 'invalid candidate signature' '10' $pkg '0' '1' '0' $false
  Case 'multiple certificate signers' '10' $pkg '0' '0' '1' $false
  Write-Host 'PASS: all 7 upgrade checker scenarios'
} finally {
  Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
  foreach ($name in @('MOCK_OLD_APK','MOCK_NEW_VERSION','MOCK_NEW_PACKAGE','MOCK_DIFFERENT_CERT','MOCK_INVALID_SIGNATURE','MOCK_EXTRA_SIGNER')) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
  }
}

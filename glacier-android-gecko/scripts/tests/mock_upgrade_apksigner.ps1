if ($args.Count -ne 3 -or $args[0] -ne 'verify' -or $args[1] -ne '--print-certs') { throw 'Unexpected apksigner command' }
$old = [IO.Path]::GetFileName($args[2]) -eq 'installed-base.apk'
if (-not $old -and $env:MOCK_INVALID_SIGNATURE -eq '1') { Write-Error 'APK signature verification failed'; exit 1 }
$cert = if ($old) { 'a' * 64 } elseif ($env:MOCK_DIFFERENT_CERT -eq '1') { 'b' * 64 } else { 'a' * 64 }
Write-Output "Signer #1 certificate SHA-256 digest: $cert"
if (-not $old -and $env:MOCK_EXTRA_SIGNER -eq '1') { Write-Output ('Signer #2 certificate SHA-256 digest: ' + ('c' * 64)) }

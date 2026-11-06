if ($args.Count -ne 3 -or $args[0] -ne 'dump' -or $args[1] -ne 'badging') { throw 'Unexpected aapt command' }
$old = [IO.Path]::GetFileName($args[2]) -eq 'installed-base.apk'
$name = if ($old) { 'cn.borealos.glacier.geckopreview' } else { $env:MOCK_NEW_PACKAGE }
$code = if ($old) { '9' } else { $env:MOCK_NEW_VERSION }
Write-Output "package: name='$name' versionCode='$code' versionName='0.2.1'"

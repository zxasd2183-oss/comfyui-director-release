if ($args.Count -lt 3) { throw 'Unexpected adb arguments' }
if ($args[0] -eq 'shell' -and $args[1] -eq 'pm' -and $args[2] -eq 'path') {
  Write-Output 'package:/data/app/fake/base.apk'
  exit 0
}
if ($args[0] -eq 'pull' -and $args.Count -eq 3) {
  Copy-Item -LiteralPath $env:MOCK_OLD_APK -Destination $args[2] -Force
  Write-Output '1 file pulled'
  exit 0
}
throw ('Unexpected adb command: ' + ($args -join ' '))

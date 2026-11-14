# Director Desktop Companion 0.2 - view-only, human-armed RDP session sharing.
# Runs interactively inside the existing RDP session, never as SYSTEM.
# Local manual Stop, session Lock/Disconnect/Logoff revoke access immediately.
# A visible 128-bit PIN is good for ONE initial pairing for up to ten minutes;
# a separate private session credential lasts only until Stop/session exit.
# This script has NO keyboard/mouse command endpoint or Internet listener.
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
if (-not [Environment]::UserInteractive) { throw 'Interactive RDP desktop required' }

# Native session-change notifications: fail closed if the OS cannot register.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public sealed class DirectorSessionForm : Form {
    [DllImport("wtsapi32.dll", SetLastError=true)]
    private static extern bool WTSRegisterSessionNotification(IntPtr hWnd, int flags);
    [DllImport("wtsapi32.dll", SetLastError=true)]
    private static extern bool WTSUnRegisterSessionNotification(IntPtr hWnd);
    private const int WM_WTSSESSION_CHANGE = 0x02B1;
    public event EventHandler SessionGone;
    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e);
        if (!WTSRegisterSessionNotification(this.Handle, 0))
            throw new InvalidOperationException("RDP session notification unavailable");
    }
    protected override void OnHandleDestroyed(EventArgs e) {
        if (this.IsHandleCreated) WTSUnRegisterSessionNotification(this.Handle);
        base.OnHandleDestroyed(e);
    }
    protected override void WndProc(ref Message message) {
        // Remote/console disconnect, logoff and session lock all revoke access.
        if (message.Msg == WM_WTSSESSION_CHANGE) {
            int reason = message.WParam.ToInt32();
            if (reason == 2 || reason == 4 || reason == 6 || reason == 7) {
                EventHandler handler = SessionGone;
                if (handler != null) handler(this, EventArgs.Empty);
            }
        }
        base.WndProc(ref message);
    }
}
'@ -ReferencedAssemblies @('System.Windows.Forms.dll','System.Drawing.dll')

# Separate local Enable Input is required before these APIs can run.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DirectorDesktopInput {
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
}
'@

$port = 19017
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
$listener.Start()
$script:code = ''
$script:pairDeadline = [DateTime]::MinValue
$script:sessionToken = ''
$script:enabled = $false
$script:controlEnabled = $false
$script:paired = $false
$script:denials = 0
$script:lastFrame = [DateTime]::MinValue

function New-Secret {
    $buffer = [byte[]]::new(16)
    $crypto = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $crypto.GetBytes($buffer) } finally { $crypto.Dispose() }
    return [BitConverter]::ToString($buffer).Replace('-', '').ToLowerInvariant()
}
function Reset-Consent {
    $script:code = New-Secret
    $script:pairDeadline = [DateTime]::UtcNow.AddMinutes(10)
    $script:sessionToken = ''
    $script:enabled = $false
    $script:controlEnabled = $false
    $script:paired = $false
    $script:denials = 0
    $script:lastFrame = [DateTime]::MinValue
}
function Equal-Secret([string]$left, [string]$right) {
    if ($left.Length -ne 32 -or $right.Length -ne 32) { return $false }
    $difference = 0
    for ($i=0; $i -lt 32; $i++) {
        $difference = $difference -bor ([int][char]$left[$i] -bxor [int][char]$right[$i])
    }
    return $difference -eq 0
}
function Get-ShareActive {
    return ($script:enabled -and $script:paired -and $script:sessionToken.Length -eq 32)
}
function Get-ControlActive { return ((Get-ShareActive) -and $script:controlEnabled) }
function Test-ExactFields($obj, [string[]]$expected) {
    if ($null -eq $obj) { return $false }
    $names = @($obj.PSObject.Properties.Name)
    if ($names.Count -ne $expected.Count) { return $false }
    foreach ($name in $expected) { if ($name -notin $names) { return $false } }
    return $true
}
function Invoke-DirectorInput($item) {
    if (-not (Get-ControlActive)) { throw 'input_not_armed' }
    switch ([string]$item.action) {
        'click' {
            if (-not (Test-ExactFields $item @('action','x','y','clicks'))) { throw 'bad_fields' }
            if ($item.x -isnot [int] -or $item.y -isnot [int] -or
                $item.clicks -isnot [int] -or $item.x -lt 0 -or
                $item.x -gt 999 -or $item.y -lt 0 -or
                $item.y -gt 999 -or $item.clicks -notin @(1,2)) { throw 'bad_click' }
            $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
            if ($bounds.Width -lt 320 -or $bounds.Height -lt 200) { throw 'screen_unavailable' }
            $x = $bounds.X + [int][Math]::Round($item.x * ($bounds.Width-1) / 999.0)
            $y = $bounds.Y + [int][Math]::Round($item.y * ($bounds.Height-1) / 999.0)
            [System.Windows.Forms.Cursor]::Position = [System.Drawing.Point]::new($x,$y)
            for ($i=0; $i -lt $item.clicks; $i++) {
                [DirectorDesktopInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
                [DirectorDesktopInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
                if ($i -eq 0 -and $item.clicks -eq 2) { Start-Sleep -Milliseconds 75 }
            }
        }
        'key' {
            if (-not (Test-ExactFields $item @('action','key')) -or
                $item.key -isnot [string]) { throw 'bad_fields' }
            $keys = @{
                ENTER='{ENTER}'; ESC='{ESC}'; TAB='{TAB}'; BACKSPACE='{BACKSPACE}';
                UP='{UP}'; DOWN='{DOWN}'; LEFT='{LEFT}'; RIGHT='{RIGHT}';
                SPACE=' '; DELETE='{DELETE}'; HOME='{HOME}'; END='{END}'; F2='{F2}'
            }
            if (-not $keys.ContainsKey($item.key)) { throw 'bad_key' }
            [System.Windows.Forms.SendKeys]::SendWait([string]$keys[$item.key])
        }
        'text' {
            if (-not (Test-ExactFields $item @('action','text')) -or
                $item.text -isnot [string] -or
                -not [regex]::IsMatch($item.text,'\A[A-Za-z0-9 ._/@-]{1,100}\z')) {
                throw 'bad_text'
            }
            foreach ($c in $item.text.ToCharArray()) {
                [System.Windows.Forms.SendKeys]::SendWait([string]$c)
            }
        }
        default { throw 'bad_action' }
    }
}

function Encode-Snapshot {
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    if ($screen.Width -lt 320 -or $screen.Height -lt 200) { throw 'Screen unavailable' }
    $size = [System.Drawing.Size]::new($screen.Width, $screen.Height)
    $original = [System.Drawing.Bitmap]::new($size.Width, $size.Height)
    $g = [System.Drawing.Graphics]::FromImage($original)
    try { $g.CopyFromScreen($screen.X, $screen.Y, 0, 0, $size) }
    finally { $g.Dispose() }
    $w = [Math]::Min(800, $screen.Width)
    $h = [Math]::Max(1, [int][Math]::Round($screen.Height * $w / $screen.Width))
    $small = [System.Drawing.Bitmap]::new($w, $h)
    $g2 = [System.Drawing.Graphics]::FromImage($small)
    try {
        $g2.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g2.DrawImage($original, 0, 0, $w, $h)
        $stream = New-Object System.IO.MemoryStream
        try {
            $encoder = [Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
                Where-Object { $_.MimeType -eq 'image/jpeg' } | Select-Object -First 1
            if (-not $encoder) { throw 'JPEG encoder missing' }
            $parameters = [System.Drawing.Imaging.EncoderParameters]::new(1)
            try {
                $parameters.Param[0] = [System.Drawing.Imaging.EncoderParameter]::new(
                    [System.Drawing.Imaging.Encoder]::Quality, [long]55)
                $small.Save($stream, $encoder, $parameters)
                $bytes = $stream.ToArray()
            } finally { $parameters.Dispose() }
        } finally { $stream.Dispose() }
    } finally { $g2.Dispose(); $small.Dispose(); $original.Dispose() }
    if ($bytes.Length -lt 200 -or $bytes.Length -gt 400000) {
        throw 'Desktop snapshot outside safe size bounds'
    }
    return ,$bytes
}
function Send-Reply($stream, [int]$status, [string]$type, [byte[]]$body) {
    $label = @{200='OK';401='Unauthorized';403='Forbidden';404='Not Found';409='Conflict';429='Too Many Requests';503='Unavailable'}[$status]
    if (-not $label) { $label = 'Error' }
    $crlf = [string][char]13 + [char]10
    $head = "HTTP/1.1 $status $label" + $crlf +
            "Content-Type: $type" + $crlf +
            "Content-Length: $($body.Length)" + $crlf +
            "Cache-Control: no-store" + $crlf +
            "X-Content-Type-Options: nosniff" + $crlf +
            "Connection: close" + $crlf + $crlf
    $part = [Text.Encoding]::ASCII.GetBytes($head)
    $stream.Write($part, 0, $part.Length)
    if ($body.Length) { $stream.Write($body, 0, $body.Length) }
}
function Json-Bytes([bool]$ok, [string]$reason) {
    $obj = @{ok=$ok; sharing=(Get-ShareActive); control_enabled=(Get-ControlActive)}
    if ($reason) { $obj.reason = $reason }
    return ,[Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Compress))
}
Reset-Consent
$form = New-Object DirectorSessionForm
$form.Text = 'Director Desktop - RDP View Only'
$form.Width = 500
$form.Height = 305
$form.TopMost = $true
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedDialog
$form.MaximizeBox = $false
$note = New-Object Windows.Forms.Label
$note.Text = 'View until Stop/lock/disconnect. Control requires Enable Input. Never share passwords.'
$note.SetBounds(12, 12, 462, 36)
$form.Controls.Add($note)
$field = New-Object Windows.Forms.TextBox
$field.ReadOnly = $true
$field.SetBounds(12, 56, 462, 28)
$field.Font = [System.Drawing.Font]::new('Consolas', 12)
$field.Text = $script:code
$form.Controls.Add($field)
$status = New-Object Windows.Forms.Label
$status.SetBounds(12, 94, 462, 25)
$status.Text = 'OFF: Share code in ChatGPT, click Start, then pair.'
$form.Controls.Add($status)
$start = New-Object Windows.Forms.Button
$start.Text = 'Start View-Only'
$start.SetBounds(12, 135, 145, 32)
$start.Add_Click({
    if ($script:paired) {
        $status.Text = 'Already paired. Use Stop to revoke session.'
    } elseif ([DateTime]::UtcNow -lt $script:pairDeadline) {
        $script:enabled = $true
        $status.Text = 'Awaiting pairing. Code works only once.'
    } else {
        $status.Text = 'Pair code expired. Click New Code.'
    }
})
$form.Controls.Add($start)
$stop = New-Object Windows.Forms.Button
$stop.Text = 'Stop Immediately'
$stop.SetBounds(173, 135, 145, 32)
$stop.Add_Click({
    Reset-Consent
    $field.Text = $script:code
    $status.Text = 'OFF: Stopped and old session revoked.'
})
$form.Controls.Add($stop)
$rotate = New-Object Windows.Forms.Button
$rotate.Text = 'New Code'
$rotate.SetBounds(335, 135, 139, 32)
$rotate.Add_Click({
    Reset-Consent
    $field.Text=$script:code
    $status.Text='OFF: New one-time pairing code generated'
})
$form.Controls.Add($rotate)
$arm = New-Object Windows.Forms.Button
$arm.Text = 'Enable Input'
$arm.SetBounds(12,184,145,32)
$arm.Add_Click({
    if (Get-ShareActive) {
        $script:controlEnabled = $true
        $status.Text = 'CONTROL ON: Click Disable Input or Stop to revoke.'
    } else {
        $status.Text = 'Start View-Only and pair first.'
    }
})
$form.Controls.Add($arm)
$disarm = New-Object Windows.Forms.Button
$disarm.Text = 'Disable Input'
$disarm.SetBounds(173,184,145,32)
$disarm.Add_Click({
    $script:controlEnabled = $false
    $status.Text = 'VIEW ONLY: Remote input is OFF.'
})
$form.Controls.Add($disarm)
$form.add_SessionGone({
    Reset-Consent
    $field.Text = $script:code
    $status.Text = 'PAUSED: RDP locked/disconnected. New authorization required.'
})
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 150
$timer.Add_Tick({
    if (-not $script:paired -and [DateTime]::UtcNow -ge $script:pairDeadline) {
        $script:enabled = $false
        $status.Text = 'Code expired: click New Code'
    }
    if (-not $listener.Pending()) { return }
    $client = $null
    try {
        $client = $listener.AcceptTcpClient()
        $client.ReceiveTimeout = 1500
        $client.SendTimeout = 1500
        $stream = $client.GetStream()
        $buffer = [byte[]]::new(2048)
        $len = $stream.Read($buffer, 0, $buffer.Length)
        $header = [Text.Encoding]::ASCII.GetString($buffer, 0, $len)
        $pin = [regex]::Match($header, '(?im)^X-Director-Desktop-Code:\s*([0-9a-f]{32})\s*$')
        $session = [regex]::Match($header, '(?im)^X-Director-Desktop-Session:\s*([0-9a-f]{32})\s*$')
        if ($header.StartsWith('POST /v1/pair HTTP/1.1')) {
            if (-not $pin.Success -or -not (Equal-Secret $pin.Groups[1].Value $script:code)) {
                $script:denials++
                Send-Reply $stream 401 'application/json' (Json-Bytes $false 'unauthorized')
            } elseif (-not $script:enabled -or $script:paired -or
                      [DateTime]::UtcNow -ge $script:pairDeadline -or $script:denials -ge 12) {
                Send-Reply $stream 403 'application/json' (Json-Bytes $false 'not_accepting_pairing')
            } else {
                $script:sessionToken = New-Secret
                $script:paired = $true
                $script:code = ''
                $field.Text = '(paired; one-time code consumed)'
                $status.Text = 'ON: Shared until Stop, RDP lock, or disconnect.'
                $payload = [Text.Encoding]::UTF8.GetBytes((@{
                    ok=$true; sharing=$true; session_token=$script:sessionToken
                } | ConvertTo-Json -Compress))
                Send-Reply $stream 200 'application/json' $payload
            }
        } elseif (-not $session.Success -or
                  -not (Equal-Secret $session.Groups[1].Value $script:sessionToken)) {
            $script:denials++
            Send-Reply $stream 401 'application/json' (Json-Bytes $false 'unauthorized')
        } elseif ($header.StartsWith('GET /v1/status HTTP/1.1')) {
            Send-Reply $stream 200 'application/json' (Json-Bytes $true '')
        } elseif ($header.StartsWith('GET /v1/frame HTTP/1.1')) {
            if (-not (Get-ShareActive)) {
                Send-Reply $stream 403 'application/json' (Json-Bytes $false 'not_sharing')
            } elseif (([DateTime]::UtcNow - $script:lastFrame).TotalSeconds -lt 3) {
                Send-Reply $stream 429 'application/json' (Json-Bytes $false 'rate_limited')
            } else {
                $snapshot = Encode-Snapshot
                $script:lastFrame = [DateTime]::UtcNow
                Send-Reply $stream 200 'image/jpeg' $snapshot
            }
        } else {
            Send-Reply $stream 404 'application/json' (Json-Bytes $false 'not_found')
        }
    } catch {
        # Never show secrets, HTTP bodies, or desktop contents in exceptions.
        $status.Text = 'Connection error. Stop and restart.'
    } finally {
        if ($client) { $client.Dispose() }
    }
})
$form.Add_FormClosed({
    $timer.Stop()
    $listener.Stop()
    $script:code=''
    $script:sessionToken=''
    $script:enabled=$false
    $script:controlEnabled=$false
    $script:paired=$false
})
$timer.Start()
try { [void]$form.ShowDialog() }
finally { $timer.Stop();$listener.Stop();$timer.Dispose();$form.Dispose() }

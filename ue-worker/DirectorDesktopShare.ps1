# Director Desktop Companion 0.1 - manually launched in the current RDP session.
# This file is NOT installed as a service, cannot see other sessions, cannot
# control mouse/keyboard, and never uploads frames without visible consent.
# Runs with this desktop user's permissions; no administrator rights needed.
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
if (-not [Environment]::UserInteractive) { throw 'Interactive RDP desktop required' }
$port = 19017
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
$listener.Start()
$script:code = ''
$script:expires = [DateTime]::MinValue
$script:enabled = $false
$script:denials = 0
$script:lastFrame = [DateTime]::MinValue
function Reset-Consent {
    $random = [byte[]]::new(16)
    $crypto = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $crypto.GetBytes($random) } finally { $crypto.Dispose() }
    $script:code = [BitConverter]::ToString($random).Replace('-', '').ToLowerInvariant()
    $script:expires = [DateTime]::UtcNow.AddMinutes(10)
    $script:enabled = $false
    $script:denials = 0
    $script:lastFrame = [DateTime]::MinValue
}
function Equal-Code([string]$left, [string]$right) {
    if ($left.Length -ne 32 -or $right.Length -ne 32) { return $false }
    $difference = 0
    for ($i=0; $i -lt 32; $i++) {
        $difference = $difference -bor ([int][char]$left[$i] -bxor [int][char]$right[$i])
    }
    return $difference -eq 0
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
    $label = @{200='OK';401='Unauthorized';403='Forbidden';404='Not Found';429='Too Many Requests';503='Unavailable'}[$status]
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
    $obj = @{ok=$ok; sharing=($script:enabled -and [DateTime]::UtcNow -lt $script:expires)}
    if ($reason) { $obj.reason = $reason }
    return ,[Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Compress))
}
Reset-Consent
$form = New-Object Windows.Forms.Form
$form.Text = 'Director Desktop - RDP View Only'
$form.Width = 500
$form.Height = 255
$form.TopMost = $true
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedDialog
$form.MaximizeBox = $false
$note = New-Object Windows.Forms.Label
$note.Text = 'Shares current RDP primary screen ONLY, up to 10 minutes. STOP before passwords.'
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
$status.Text = 'OFF: Copy the temporary code to ChatGPT, then click Start.'
$form.Controls.Add($status)
$start = New-Object Windows.Forms.Button
$start.Text = 'Start View-Only'
$start.SetBounds(12, 135, 145, 32)
$start.Add_Click({
    if ([DateTime]::UtcNow -lt $script:expires) {
        $script:enabled = $true
        $status.Text = 'ON: One 800px JPEG per request. Click Stop anytime.'
    }
})
$form.Controls.Add($start)
$stop = New-Object Windows.Forms.Button
$stop.Text = 'Stop Immediately'
$stop.SetBounds(173, 135, 145, 32)
$stop.Add_Click({ $script:enabled = $false; $status.Text = 'Sharing stopped' })
$form.Controls.Add($stop)
$rotate = New-Object Windows.Forms.Button
$rotate.Text = 'New Code'
$rotate.SetBounds(335, 135, 139, 32)
$rotate.Add_Click({ Reset-Consent; $field.Text=$script:code; $status.Text='OFF: New pairing code generated' })
$form.Controls.Add($rotate)
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 150
$timer.Add_Tick({
    if ([DateTime]::UtcNow -ge $script:expires) {
        $script:enabled = $false
        $status.Text = 'Expired: click New Code'
    }
    if (-not $listener.Pending()) { return }
    $client = $null
    try {
        $client = $listener.AcceptTcpClient()
        $client.ReceiveTimeout = 1500
        $client.SendTimeout = 1500
        $stream = $client.GetStream()
        $buffer = [byte[]]::new(2048)
        $len = $stream.Read($buffer,0,$buffer.Length)
        $header = [Text.Encoding]::ASCII.GetString($buffer,0,$len)
        $match = [regex]::Match($header, '(?im)^X-Director-Desktop-Code:\s*([0-9a-f]{32})\s*$')
        $supplied = if ($match.Success) { $match.Groups[1].Value } else { '' }
        if (-not (Equal-Code $supplied $script:code)) {
            $script:denials++
            Send-Reply $stream 401 'application/json' (Json-Bytes $false 'unauthorized')
        } elseif ([DateTime]::UtcNow -ge $script:expires -or $script:denials -ge 12) {
            Send-Reply $stream 403 'application/json' (Json-Bytes $false 'expired_or_locked')
        } elseif ($header.StartsWith('GET /v1/status HTTP/1.1')) {
            Send-Reply $stream 200 'application/json' (Json-Bytes $true '')
        } elseif ($header.StartsWith('GET /v1/frame HTTP/1.1')) {
            if (-not $script:enabled) {
                Send-Reply $stream 403 'application/json' (Json-Bytes $false 'not_sharing')
            } elseif (([DateTime]::UtcNow - $script:lastFrame).TotalSeconds -lt 3) {
                Send-Reply $stream 429 'application/json' (Json-Bytes $false 'rate_limited')
            } else {
                $image = Encode-Snapshot
                $script:lastFrame = [DateTime]::UtcNow
                Send-Reply $stream 200 'image/jpeg' $image
            }
        } else {
            Send-Reply $stream 404 'application/json' (Json-Bytes $false 'not_found')
        }
    } catch {
        # Do not show HTTP bodies, auth codes or sensitive exception details.
        $status.Text = 'Connection error. Stop and restart.'
    } finally {
        if ($client) { $client.Dispose() }
    }
})
$form.Add_FormClosed({$timer.Stop();$listener.Stop();$script:code='';$script:enabled=$false})
$timer.Start()
try { [void]$form.ShowDialog() }
finally { $timer.Stop();$listener.Stop();$timer.Dispose();$form.Dispose() }

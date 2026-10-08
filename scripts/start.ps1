param([string]$LanAddress = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = 'D:\DahanPhotoLibraryData\venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\DahanPhotoLibraryData\cache'
$env:TMP = $env:TEMP
Set-Location -LiteralPath $projectRoot
$listenAddress = '127.0.0.1'
$env:DAHAN_LAN_ADDRESS = $LanAddress
if ($LanAddress) {
    $parsedAddress = [System.Net.IPAddress]::Parse($LanAddress)
    if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Use the desktop IPv4 LAN address.' }
    $listenAddress = '0.0.0.0'
    Write-Host "Mobile test: http://${LanAddress}/ (same home network; no login yet)"
}
& $pythonPath -B -m uvicorn backend.app:app --host $listenAddress --port 80

param(
    [string]$PythonPath = '',
    [string]$DataDirectory = $env:DAHAN_DATA,
    [string]$DatabaseDirectory = $env:DAHAN_DATABASE_DIR,
    [string]$SourceDirectory = $env:DAHAN_SOURCE,
    [string]$LanAddress = '',
    [ValidateRange(1,65535)][int]$Port = 8765,
    [switch]$EnableSchedules,
    [switch]$RequireExistingDatabase,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Import-DahanConfiguration -ProjectRoot (Split-Path -Parent $PSScriptRoot)
$taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskProject
Set-DahanPaths -DataDirectory $DataDirectory -DatabaseDirectory $DatabaseDirectory -SourceDirectory $SourceDirectory
$env:DAHAN_DISABLE_SCHEDULER = if ($EnableSchedules) { '0' } else { '1' }
$env:DAHAN_REQUIRE_EXISTING_DATABASE = if ($RequireExistingDatabase) { '1' } else { '0' }
if (-not $PSBoundParameters.ContainsKey('LanAddress') -and $env:DAHAN_LAN_ADDRESS) { $LanAddress = $env:DAHAN_LAN_ADDRESS }
$env:DAHAN_LAN_ADDRESS = $LanAddress
$taskListen = '127.0.0.1'
if ($LanAddress) {
    if ([Net.IPAddress]::Parse($LanAddress).AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'LanAddress must be the server IPv4 address.'
    }
    $taskListen = '0.0.0.0'
}
if ($CheckOnly) {
    @{application=$taskProject;python=$taskPython;runtime=$env:DAHAN_DATA;databases=$env:DAHAN_DATABASE_DIR;host=$taskListen;port=$Port;schedules=[bool]$EnableSchedules} | ConvertTo-Json
    return
}
Push-Location -LiteralPath $taskProject
try {
    & $taskPython -X faulthandler -B -m uvicorn backend.app:app --host $taskListen --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
} finally { Pop-Location }

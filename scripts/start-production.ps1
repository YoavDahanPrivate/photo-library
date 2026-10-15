param(
    [string]$ApplicationDirectory = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = '',
    [string]$RuntimeDirectory = 'C:\DahanPhotoLibraryData\runtime',
    [string]$DatabaseDirectory = 'D:\DahanPhotoLibraryData\prototype',
    [string]$SourceDirectory = 'D:\DahanPhotosSync',
    [string]$LogsDirectory = 'C:\DahanPhotoLibraryData\logs',
    [string]$BackupDirectory = 'C:\DahanPhotoLibraryData\backups',
    [string]$LanAddress = '',
    [ValidateRange(1,65535)][int]$Port = 80,
    [switch]$EnableSchedules,
    [switch]$SingleRun,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$taskApp = (Resolve-Path -LiteralPath $ApplicationDirectory).Path
if (-not (Test-Path -LiteralPath (Join-Path $taskApp 'backend\app.py') -PathType Leaf)) { throw 'ApplicationDirectory must contain backend/app.py.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskApp 'frontend\dist\index.html') -PathType Leaf)) { throw 'Build the frontend before starting production.' }
$taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskApp
Set-DahanPaths -DataDirectory $RuntimeDirectory -DatabaseDirectory $DatabaseDirectory -SourceDirectory $SourceDirectory
$env:DAHAN_REQUIRE_EXISTING_DATABASE = '1'
$env:DAHAN_BACKUP_DIR = $BackupDirectory
$env:DAHAN_DISABLE_SCHEDULER = if ($EnableSchedules) { '0' } else { '1' }
# Reuse this installation's configured address unless explicitly overridden.
$taskConfig = Join-Path (Split-Path -Parent $taskApp) 'server-config.json'
if (-not $PSBoundParameters.ContainsKey('LanAddress')) {
    if ($env:DAHAN_LAN_ADDRESS) { $LanAddress = $env:DAHAN_LAN_ADDRESS }
    elseif (Test-Path -LiteralPath $taskConfig -PathType Leaf) {
        $LanAddress = (Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json).lan_address
    }
}
$taskListen = '127.0.0.1'
if ($LanAddress) {
    if ([Net.IPAddress]::Parse($LanAddress).AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'LanAddress must be the server IPv4 address.' }
    $taskListen = '0.0.0.0'
}
$env:DAHAN_LAN_ADDRESS = $LanAddress
if ($CheckOnly) {
    @{application=$taskApp;python=$taskPython;runtime=$RuntimeDirectory;databases=$DatabaseDirectory;logs=$LogsDirectory;host=$taskListen;port=$Port;schedules=[bool]$EnableSchedules;require_existing_database=$true} | ConvertTo-Json
    return
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
New-Item -ItemType Directory -Path $LogsDirectory -Force | Out-Null
$taskStop = Join-Path $LogsDirectory ('stop-'+$Port+'.txt')
if (Test-Path -LiteralPath $taskStop) { Remove-Item -LiteralPath $taskStop }
$taskDelay = 5
do {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
    $taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $taskOut = Join-Path $LogsDirectory ('server-'+$Port+'-'+$taskStamp+'.log')
    $taskErr = Join-Path $LogsDirectory ('server-'+$Port+'-'+$taskStamp+'-error.log')
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-X','faulthandler','-B','-m','uvicorn','backend.app:app','--host',$taskListen,'--port',$Port) -WorkingDirectory $taskApp -WindowStyle Hidden -RedirectStandardOutput $taskOut -RedirectStandardError $taskErr -PassThru
    @{supervisor=$PID;launcher=$taskProcess.Id;port=$Port;application=$taskApp;data=$RuntimeDirectory;databases=$DatabaseDirectory;stdout=$taskOut;stderr=$taskErr} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogsDirectory ('current-'+$Port+'.json')) -Encoding utf8
    $taskProcess.WaitForExit()
    if ($SingleRun -or (Test-Path -LiteralPath $taskStop)) { break }
    @{time=(Get-Date -Format o);exit_code=$taskProcess.ExitCode;restart_delay=$taskDelay} | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $LogsDirectory ('restarts-'+$Port+'.jsonl'))
    Start-Sleep -Seconds $taskDelay
    $taskDelay = [Math]::Min(60,$taskDelay*2)
} while (-not (Test-Path -LiteralPath $taskStop))

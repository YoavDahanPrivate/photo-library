param(
    [string]$LanAddress = '',
    [string]$StorageDirectory = (Split-Path -Parent $PSScriptRoot),
    [string]$SourceDirectory = '',
    [switch]$LocalOnly,
    [switch]$GatewayWorker,
    [switch]$TunnelServiceWorker,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskStorage = $StorageDirectory
$taskApp = Join-Path $taskRoot 'app'
$taskPython = Join-Path $taskRoot 'python\python.exe'
$taskGateway = Join-Path $taskRoot 'gateway'
$taskLogs = Join-Path $taskRoot 'logs'
$taskShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskData = Join-Path $taskStorage 'prototype'
$taskSource = $SourceDirectory
if (-not $taskSource) { $taskSource = Join-Path (Split-Path -Qualifier $taskRoot) 'DahanPhotosSync' }
$taskTemp = Join-Path $taskRoot 'temp'
$taskPackConfigPath = Join-Path $taskRoot 'cache-pack-config.json'
if (-not (Test-Path -LiteralPath $taskPackConfigPath -PathType Leaf)) { throw 'Verified cache archive configuration is missing.' }
$taskPackConfig = Get-Content -LiteralPath $taskPackConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskPackRelative = [string]$taskPackConfig.relative_path
if ([IO.Path]::IsPathRooted($taskPackRelative) -or ($taskPackRelative -split '[\\/]') -contains '..') { throw 'Invalid cache archive relative path.' }
$taskCachePacks = [IO.Path]::GetFullPath((Join-Path $taskRoot $taskPackRelative))
if (-not $taskCachePacks.StartsWith(($taskRoot.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Cache archive configuration escapes production.' }


# Explicitly replace inherited development/previous-installation settings.
$env:DAHAN_PYTHON = $taskPython
$env:DAHAN_DATA = $taskData
$env:DAHAN_DATABASE_DIR = $taskData
$env:DAHAN_SOURCE = $taskSource
$env:DAHAN_CACHE_PACKS = $taskCachePacks
$env:DAHAN_LOGS_DIR = $taskLogs
$env:DAHAN_BACKUP_DIR = Join-Path $taskStorage 'backups'
$env:DAHAN_REQUIRE_EXISTING_DATABASE = '1'
$env:DAHAN_DISABLE_SCHEDULER = '1'
$env:DAHAN_LEGACY_SOURCES = '[]'
$env:DAHAN_HOST_ALIASES = 'dahanoffice,dahanoffice.local'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:TEMP = $taskTemp
$env:TMP = $taskTemp

foreach ($taskRequired in @($taskPython,(Join-Path $taskApp 'backend\app.py'),(Join-Path $taskApp 'frontend\dist\index.html'),(Join-Path $taskGateway 'password_gateway.py'),(Join-Path $taskData 'catalogue.sqlite'),(Join-Path $taskData 'sync.sqlite'),(Join-Path $taskCachePacks 'cache-index.json'),(Join-Path $taskCachePacks 'verification.json'))) {
    if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) { throw "Required production file missing: $taskRequired" }
}
if (-not (Test-Path -LiteralPath $taskSource -PathType Container)) { throw "Local originals missing: $taskSource" }
$taskDrive = [IO.Path]::GetPathRoot($taskRoot)
foreach ($taskPath in @($taskPython,$taskApp,$taskData,$taskSource,$taskLogs,$taskGateway,$env:DAHAN_BACKUP_DIR,$taskTemp,$taskCachePacks)) {
    if ([IO.Path]::GetPathRoot($taskPath) -ne $taskDrive) { throw "Application dependency outside the production drive: $taskPath" }
}
# LAN discovery is optional: the backend always binds to 0.0.0.0:80.
if (-not $LanAddress -and -not $GatewayWorker -and -not $TunnelServiceWorker) {
    $taskAddresses = @(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | ForEach-Object {$_.IPv4Address.IPAddress} | Where-Object {$_ -notmatch '^(127\.|169\.254\.)'} | Select-Object -Unique)
    if ($taskAddresses.Count -eq 1) { $LanAddress = $taskAddresses[0] }
}
$env:DAHAN_LAN_ADDRESS = $LanAddress
if ($CheckOnly) {
    [ordered]@{application=$taskApp;python=$taskPython;runtime=$taskData;databases=$taskData;originals=$taskSource;logs=$taskLogs;temporary=$taskTemp;gateway=$taskGateway;models=(Join-Path $taskStorage 'models');cache_archives=$taskCachePacks;all_application_paths_on_drive=$taskDrive;schedules=$false;backend_listen='0.0.0.0:80';startup_order=@('tunnel','backend','gateway','public_health');public_route='Cloudflare tunnel -> 127.0.0.1:8787 gateway -> 127.0.0.1:80 backend'} | ConvertTo-Json
    exit 0
}
foreach ($taskDirectory in @($taskLogs,$taskTemp)) { New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null }
function Assert-DahanListener([int]$Port,[string]$Module) {
    $taskListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($taskListener in $taskListeners) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
        if ($taskProcess.ExecutablePath -ne $taskPython -or $taskProcess.CommandLine -notlike "*uvicorn $Module*") {
            throw "Port $Port belongs to another installation/process. It was not stopped."
        }
    }
    return ($taskListeners.Count -gt 0)
}
if ($GatewayWorker) {
    $taskMutex = New-Object Threading.Mutex($false,'Local\DahanLibraryGateway')
    if (-not $taskMutex.WaitOne(0)) { exit 0 }
    try {
        while ($true) {
            if (-not (Assert-DahanListener 8787 'password_gateway:app')) {
                $taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-B','-m','uvicorn','password_gateway:app','--host','127.0.0.1','--port','8787','--no-proxy-headers') -WorkingDirectory $taskGateway -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogs "gateway-$taskStamp.log") -RedirectStandardError (Join-Path $taskLogs "gateway-$taskStamp-error.log") -PassThru
                $taskProcess.WaitForExit()
            }
            Start-Sleep -Seconds 5
        }
    } finally { $taskMutex.ReleaseMutex();$taskMutex.Dispose() }
    exit 0
}
function Get-DahanTunnelService {
    $taskService = Get-CimInstance Win32_Service -Filter "Name='Cloudflared'"
    $taskTunnelPath = Join-Path $taskRoot 'tunnel\cloudflared.exe'
    $taskTokenPath = Join-Path $taskRoot 'tunnel\tunnel.token'
    $taskExpected = '"' + $taskTunnelPath + '" tunnel run --token-file "' + $taskTokenPath + '"'
    if (-not $taskService -or $taskService.PathName -ne $taskExpected) {
        throw 'Cloudflared is not registered to this D: installation. Inspect Install-Host.ps1 before changing service registration.'
    }
    foreach ($taskFile in @($taskTunnelPath,$taskTokenPath)) {
        if (-not (Test-Path -LiteralPath $taskFile -PathType Leaf)) { throw "Tunnel file missing: $taskFile" }
    }
    return $taskService
}
function Start-DahanTunnelService {
    $null = Get-DahanTunnelService
    $taskService = Get-Service -Name Cloudflared
    if ($taskService.Status -eq 'StopPending') { $taskService.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));$taskService.Refresh() }
    if ($taskService.Status -eq 'StartPending') { $taskService.WaitForStatus('Running',[TimeSpan]::FromSeconds(30));$taskService.Refresh() }
    if ($taskService.Status -ne 'Running') { Start-Service -Name Cloudflared -ErrorAction Stop }
    (Get-Service -Name Cloudflared).WaitForStatus('Running',[TimeSpan]::FromSeconds(30))
}
if ($TunnelServiceWorker) {
    # This elevated branch can only start the already-registered D: tunnel service.
    Start-DahanTunnelService
    exit 0
}
$taskStartupMutex = New-Object Threading.Mutex($false,'Local\DahanLibraryStartup')
$taskOwnStartup = $false
try {
    try { $taskOwnStartup = $taskStartupMutex.WaitOne([TimeSpan]::FromSeconds(120)) }
    catch [Threading.AbandonedMutexException] { $taskOwnStartup = $true }
    if (-not $taskOwnStartup) { throw 'Another library startup is still in progress. Try again shortly.' }
    $taskSteps = New-Object 'System.Collections.Generic.List[object]'
    $taskTunnelWasRunning = $false
    if (-not $LocalOnly) {
        $taskTunnelWasRunning = ((Get-DahanTunnelService).State -eq 'Running')
        if (-not $taskTunnelWasRunning) {
            Write-Output 'Starting the registered D: Cloudflare tunnel service...'
            $taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $taskAdmin = ([Security.Principal.WindowsPrincipal]::new($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            if ($taskAdmin) { Start-DahanTunnelService }
            else {
                # Elevate just the service-start helper; backend and gateway stay under this user.
                $taskElevated = Start-Process -FilePath $taskShell -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-TunnelServiceWorker') -Verb RunAs -WindowStyle Hidden -Wait -PassThru
                if ($taskElevated.ExitCode -ne 0) { throw 'Windows could not start the tunnel service. Approve its service-start prompt and retry.' }
            }
        }
        if ((Get-DahanTunnelService).State -ne 'Running') { throw 'Tunnel service is not running.' }
        $taskSteps.Add([ordered]@{step='tunnel';utc=[DateTime]::UtcNow.ToString('o');already_running=$taskTunnelWasRunning})
        Write-Output 'Tunnel service is running.'
    }
    $taskBackendWasRunning = Assert-DahanListener 80 'backend.app:app'
    if ($taskBackendWasRunning) {
        $taskIPv4 = @(Get-NetTCPConnection -LocalPort 80 -State Listen | Where-Object {$_.LocalAddress -eq '0.0.0.0'})
        if (-not $taskIPv4.Count) { throw 'The existing backend does not listen on 0.0.0.0:80. Restart its supervisor with the updated launcher.' }
    } else {
        Write-Output 'Starting the D: backend on 0.0.0.0:80...'
        $taskArguments = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $taskApp 'start-production.ps1')+'"'),'-PythonPath',('"'+$taskPython+'"'),'-RuntimeDirectory',('"'+$taskData+'"'),'-DatabaseDirectory',('"'+$taskData+'"'),'-SourceDirectory',('"'+$taskSource+'"'),'-LogsDirectory',('"'+$taskLogs+'"'),'-Port','80','-BindAddress','0.0.0.0')
        if ($LanAddress) { $taskArguments += @('-LanAddress',$LanAddress) }
        Start-Process -FilePath $taskShell -ArgumentList $taskArguments -WindowStyle Hidden | Out-Null
    }
    $taskReady = $false
    for ($taskTry=0;$taskTry -lt 45;$taskTry++) {
        try { $taskHealth=Invoke-RestMethod 'http://127.0.0.1/api/health' -TimeoutSec 3;if ($taskHealth.storage -eq 'available') {$taskReady=$true;break} } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $taskReady) { throw "Library did not become healthy. Inspect $taskLogs." }
    $null = Assert-DahanListener 80 'backend.app:app'
    if (-not @(Get-NetTCPConnection -LocalPort 80 -State Listen | Where-Object {$_.LocalAddress -eq '0.0.0.0'}).Count) { throw 'Backend is not listening on 0.0.0.0:80.' }
    $taskSteps.Add([ordered]@{step='backend';utc=[DateTime]::UtcNow.ToString('o');already_running=$taskBackendWasRunning;listen='0.0.0.0:80'})
    $taskPublicReady = $false
    if (-not $LocalOnly) {
        $taskGatewayWasRunning = Assert-DahanListener 8787 'password_gateway:app'
        if (-not $taskGatewayWasRunning) {
            Start-Process -FilePath $taskShell -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-GatewayWorker') -WindowStyle Hidden | Out-Null
        }
        $taskGatewayReady = $false
        for ($taskTry=0;$taskTry -lt 45;$taskTry++) {
            try {
                $taskHealth=Invoke-RestMethod 'http://127.0.0.1:8787/api/health' -TimeoutSec 3
                if ($taskHealth.storage -eq 'available') {$taskGatewayReady=$true;break}
            } catch {}
            Start-Sleep -Seconds 1
        }
        if (-not $taskGatewayReady) { throw "Tunnel gateway did not become healthy. Inspect $taskLogs." }
        $null=Assert-DahanListener 8787 'password_gateway:app'
        $taskSteps.Add([ordered]@{step='gateway';utc=[DateTime]::UtcNow.ToString('o');already_running=$taskGatewayWasRunning;upstream='http://127.0.0.1:80'})
        $taskExpectedVersion = (Get-Content -LiteralPath (Join-Path $taskApp 'frontend\dist\version.json') -Raw | ConvertFrom-Json).version
        for ($taskTry=0;$taskTry -lt 20;$taskTry++) {
            try {
                $taskHealth=Invoke-RestMethod ('https://dahanphotos.com/api/health?startup='+[DateTime]::UtcNow.Ticks) -TimeoutSec 5 -UserAgent 'Mozilla/5.0 DahanStartup'
                $taskVersion=Invoke-RestMethod ('https://dahanphotos.com/version.json?startup='+[DateTime]::UtcNow.Ticks) -TimeoutSec 5 -UserAgent 'Mozilla/5.0 DahanStartup'
                if ($taskHealth.storage -eq 'available' -and $taskVersion.version -eq $taskExpectedVersion) {$taskPublicReady=$true;break}
            } catch {}
            Start-Sleep -Seconds 2
        }
        if (-not $taskPublicReady) { throw 'The local library is running, but the public tunnel did not pass health/version checks. Check Internet connectivity and Cloudflared service logs.' }
        $taskSteps.Add([ordered]@{step='public_health';utc=[DateTime]::UtcNow.ToString('o');version=$taskExpectedVersion;url='https://dahanphotos.com/'})
    }
    [ordered]@{checked_local=(Get-Date -Format o);local='http://localhost/';public='https://dahanphotos.com/';public_verified=$taskPublicReady;application=$taskApp;python=$taskPython;data=$taskData;local_only=[bool]$LocalOnly;storage='available';backend_listen='0.0.0.0:80';steps=@($taskSteps.ToArray())} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskLogs 'startup-verification.json') -Encoding UTF8
    Write-Output 'Dahan Library is ready: http://localhost/ and https://dahanphotos.com/'
} finally {
    if ($taskOwnStartup) { $taskStartupMutex.ReleaseMutex() }
    $taskStartupMutex.Dispose()
}

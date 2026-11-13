param(
    [string]$LanAddress = '',
    [string]$GatewayDirectory = (Join-Path $env:LOCALAPPDATA 'DahanTunnelTest'),
    [switch]$GatewayWorker
)
$ErrorActionPreference = 'Stop'
$taskApp = $PSScriptRoot
$taskLogs = Join-Path (Split-Path -Parent $taskApp) 'logs'
$taskShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $taskApp 'scripts\common.ps1')
Import-DahanConfiguration -ProjectRoot $taskApp
$taskPython = Resolve-DahanPython -ProjectRoot $taskApp
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
function Get-Listener([int]$Port) { @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
function Assert-Listener([int]$Port,[string]$Pattern,[string]$Address) {
    $listeners = @(Get-Listener $Port)
    if (-not $listeners) { throw "Port $Port is not listening." }
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($process.CommandLine -notlike $Pattern -or $listener.LocalAddress -ne $Address) {
            throw "Port $Port is occupied by an unexpected process or binding. No process was stopped."
        }
    }
}
if ($GatewayWorker) {
    $taskMutex = New-Object Threading.Mutex($false,'Local\DahanLibraryGateway')
    if (-not $taskMutex.WaitOne(0)) { exit 0 }
    try {
        while ($true) {
            if (-not (Get-Listener 8787)) {
                $taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $taskGateway = Start-Process -FilePath $taskPython -ArgumentList @('-B','-m','uvicorn','password_gateway:app','--host','127.0.0.1','--port','8787','--no-proxy-headers') -WorkingDirectory $GatewayDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLogs "gateway-$taskStamp.log") -RedirectStandardError (Join-Path $taskLogs "gateway-$taskStamp-error.log")
                $taskGateway.WaitForExit()
            } else { Assert-Listener 8787 '*uvicorn password_gateway:app*' '127.0.0.1' }
            Start-Sleep -Seconds 5
        }
    } finally { $taskMutex.ReleaseMutex(); $taskMutex.Dispose() }
    exit
}
$taskLaunchMutex = New-Object Threading.Mutex($false,'Local\DahanLibraryStartup')
if (-not $taskLaunchMutex.WaitOne(0)) { throw 'Another Library startup is already in progress.' }
try {
    $taskManifest = Get-Content (Join-Path $taskApp 'deployed-release.json') -Raw | ConvertFrom-Json
    foreach ($file in $taskManifest.files) {
        $taskFile = Join-Path $taskApp $file.path
        if (-not (Test-Path -LiteralPath $taskFile) -or (Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash -ne $file.sha256) {
            throw "Deployed release verification failed: $($file.path). Redeploy the tested build before starting."
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $GatewayDirectory 'password_gateway.py'))) { throw "Gateway missing from $GatewayDirectory" }
    $taskTunnel = Get-Service Cloudflared -ErrorAction Stop
    if ($taskTunnel.Status -ne 'Running') {
        try { Start-Service Cloudflared } catch { throw 'Cannot start Cloudflared. Run this script as Administrator to start the installed service.' }
        (Get-Service Cloudflared).WaitForStatus('Running',[TimeSpan]::FromSeconds(30))
    }
    if (-not $LanAddress) {
        $taskAddresses = @(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | ForEach-Object {$_.IPv4Address.IPAddress} | Where-Object {$_ -notmatch '^(127\.|169\.254\.)'} | Select-Object -Unique)
        if ($taskAddresses.Count -eq 1) { $LanAddress = $taskAddresses[0] }
        else { throw 'Supply -LanAddress with this computer''s LAN IPv4 address.' }
    }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $LanAddress -ErrorAction SilentlyContinue)) { throw 'LanAddress must belong to this computer.' }
    if (-not (Get-Listener 80)) {
        $taskExisting = @(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$taskApp\start-production.ps1*"})
        if (-not $taskExisting) {
            Start-Process -FilePath $taskShell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $taskApp 'start-production.ps1')+'"'),'-LanAddress',$LanAddress,'-Port','80') -WindowStyle Hidden | Out-Null
        }
    }
    $taskReady = $false
    for ($taskTry=0; $taskTry -lt 40; $taskTry++) {
        try { $taskHealth=Invoke-RestMethod 'http://127.0.0.1/api/health' -TimeoutSec 3; if ($taskHealth.storage -eq 'available') {$taskReady=$true;break} } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $taskReady) { throw "Library did not become healthy. Check $taskLogs and ensure the database drive is connected." }
    Assert-Listener 80 '*uvicorn backend.app:app*' '0.0.0.0'
    if (Get-Listener 8787) { Assert-Listener 8787 '*uvicorn password_gateway:app*' '127.0.0.1' }
    Start-Process -FilePath $taskShell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-GatewayWorker','-GatewayDirectory',('"'+$GatewayDirectory+'"')) -WindowStyle Hidden | Out-Null
    $taskGatewayReady=$false
    for ($taskTry=0;$taskTry -lt 20;$taskTry++) {
        try { $taskVersion=Invoke-RestMethod 'http://127.0.0.1:8787/version.json' -TimeoutSec 3; if ($taskVersion.version -eq $taskManifest.version) {$taskGatewayReady=$true;break} } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $taskGatewayReady) { throw "Gateway is not serving release $($taskManifest.version). Check $taskLogs." }
    Assert-Listener 8787 '*uvicorn password_gateway:app*' '127.0.0.1'
    $taskPublicReady=$false
    for ($taskTry=0;$taskTry -lt 6;$taskTry++) {
        try { $taskPublic=Invoke-RestMethod ('https://dahanphotos.com/version.json?startup='+[Guid]::NewGuid().ToString()) -TimeoutSec 10; if ($taskPublic.version -eq $taskManifest.version) {$taskPublicReady=$true;break} } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $taskPublicReady) { throw 'Local Library is ready, but dahanphotos.com is not serving this release. Check Cloudflared and its origin route to http://127.0.0.1:8787.' }
    try { $null=Invoke-WebRequest 'https://dahanphotos.com/api/auth/me' -UseBasicParsing -TimeoutSec 10; throw 'Public authentication check unexpectedly allowed anonymous access.' }
    catch { if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 401) { throw } }
    $taskResult = [ordered]@{checked_at=(Get-Date -Format o);local='http://localhost/';binding='0.0.0.0:80';lan="http://$LanAddress/";public='https://dahanphotos.com';release=$taskManifest.version;storage='available';gateway='verified';tunnel='verified end-to-end';authentication='anonymous access denied';logs=$taskLogs}
    $taskResult | ConvertTo-Json | Set-Content (Join-Path $taskLogs 'startup-verification.json') -Encoding UTF8
    $taskResult | ConvertTo-Json
} finally { $taskLaunchMutex.ReleaseMutex(); $taskLaunchMutex.Dispose() }

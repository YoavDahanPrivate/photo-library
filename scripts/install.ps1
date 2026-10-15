param(
    [string]$PythonPath = '',
    [string]$DataDirectory = '',
    [string]$DatabaseDirectory = '',
    [switch]$SkipDependencies,
    [switch]$SkipModels,
    [switch]$SkipMaps,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Import-DahanConfiguration -ProjectRoot $taskProject
Set-DahanPaths -DataDirectory $DataDirectory -DatabaseDirectory $DatabaseDirectory
$taskConfig = Join-Path $taskProject 'dahan-config.json'
$taskEnvironment = Join-Path $taskProject '.venv\Scripts\python.exe'
if ($CheckOnly) {
    @{application=$taskProject;runtime=$env:DAHAN_DATA;databases=$env:DAHAN_DATABASE_DIR;config=$taskConfig;installs_dependencies=(-not $SkipDependencies);downloads_models=(-not $SkipModels);downloads_maps=(-not $SkipMaps)} | ConvertTo-Json
    return
}
Push-Location -LiteralPath $taskProject
try {
    if (-not $SkipDependencies) {
        if (-not (Test-Path -LiteralPath $taskEnvironment -PathType Leaf)) {
            if ($PythonPath) { & $PythonPath -m venv (Join-Path $taskProject '.venv') }
            else { & py -3.12 -m venv (Join-Path $taskProject '.venv') }
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required to create the environment.' }
        }
        $taskPython = $taskEnvironment
        & $taskPython -m pip install -r requirements.lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
        & npm.cmd ci --prefix frontend
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed; install Node.js 22+ and npm.' }
        & npm.cmd run build --prefix frontend -- --configLoader runner
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } else {
        $taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskProject
        if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'frontend\dist\index.html') -PathType Leaf)) { throw 'Build the frontend before using SkipDependencies.' }
    }
    if (-not $SkipModels) {
        & $taskPython -B -c 'from backend.indexer import models; models()'
        if ($LASTEXITCODE -ne 0) { throw 'Face model download failed. Retry setup or use SkipModels for browsing without face processing.' }
    }
    if (-not $SkipMaps) {
        & $taskPython -B -m backend.setup_references
        if ($LASTEXITCODE -ne 0) { throw 'Map reference installation failed. Retry setup or use SkipMaps for browsing without location processing.' }
    }
    & $taskPython -B -m backend.setup_library
    if ($LASTEXITCODE -ne 0) { throw 'Library initialization failed. Existing databases were not replaced.' }
    $taskConfigEnv = @{}
    foreach ($taskName in @('DAHAN_DATA','DAHAN_DATABASE_DIR','DAHAN_SOURCE','DAHAN_LEGACY_SOURCES','DAHAN_LAN_ADDRESS','DAHAN_HOST_ALIASES','DAHAN_LOGS_DIR','DAHAN_BACKUP_DIR')) {
        $taskValue = [Environment]::GetEnvironmentVariable($taskName, 'Process')
        if ($taskValue) { $taskConfigEnv[$taskName] = $taskValue }
    }
    @{python_path=$taskPython;env=$taskConfigEnv} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $taskConfig -Encoding UTF8
    Write-Host 'Installed. Run powershell -NoProfile -ExecutionPolicy Bypass -File .\start-production.ps1 -Port 8765, open http://127.0.0.1:8765/ and add folders in Library tools > Databases, Sources & Albums.'
} finally { Pop-Location }

# Shared installation settings. Dot-sourcing this file does not start any work.
function Import-DahanConfiguration {
    param([string]$ProjectRoot)
    $taskConfig = Join-Path $ProjectRoot 'dahan-config.json'
    if (-not (Test-Path -LiteralPath $taskConfig -PathType Leaf)) {
        # Compatibility with locally configured installations, never bundled in Git.
        $taskConfig = Join-Path (Split-Path -Parent $ProjectRoot) 'server-config.json'
    }
    if (-not (Test-Path -LiteralPath $taskConfig -PathType Leaf)) { return }
    $taskSettings = Get-Content -LiteralPath $taskConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($taskName in @('DAHAN_DATA','DAHAN_DATABASE_DIR','DAHAN_SOURCE','DAHAN_LEGACY_SOURCES','DAHAN_LAN_ADDRESS','DAHAN_HOST_ALIASES','DAHAN_LOGS_DIR','DAHAN_BACKUP_DIR')) {
        $taskValue = $taskSettings.env.$taskName
        if ($taskValue -and -not [Environment]::GetEnvironmentVariable($taskName, 'Process')) {
            [Environment]::SetEnvironmentVariable($taskName, [string]$taskValue, 'Process')
        }
    }
    if (-not $env:DAHAN_PYTHON -and $taskSettings.python_path) { $env:DAHAN_PYTHON = $taskSettings.python_path }
    if (-not $env:DAHAN_LAN_ADDRESS -and $taskSettings.lan_address) { $env:DAHAN_LAN_ADDRESS = $taskSettings.lan_address }
    if (-not $env:DAHAN_LOGS_DIR -and $taskSettings.current_log_pointer) { $env:DAHAN_LOGS_DIR = Split-Path -Parent $taskSettings.current_log_pointer }
}

function Resolve-DahanPython {
    param([string]$PythonPath, [string]$ProjectRoot)
    $taskCandidates = @($PythonPath, $env:DAHAN_PYTHON,
        (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
        (Join-Path (Split-Path -Parent $ProjectRoot) 'venv\Scripts\python.exe'))
    if ($PythonPath -and -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'PythonPath does not exist. Supply the Python executable for this installation.'
    }
    foreach ($taskCandidate in $taskCandidates) {
        if ($taskCandidate -and (Test-Path -LiteralPath $taskCandidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $taskCandidate).Path
        }
    }
    throw 'Python was not found. Run scripts/install.ps1, create .venv or supply -PythonPath / DAHAN_PYTHON.'
}

function Set-DahanPaths {
    param([string]$DataDirectory, [string]$DatabaseDirectory, [string]$SourceDirectory)
    if (-not $DataDirectory) { $DataDirectory = $env:DAHAN_DATA }
    if (-not $DataDirectory) {
        $taskLocal = $env:LOCALAPPDATA
        if (-not $taskLocal) { $taskLocal = [Environment]::GetFolderPath('LocalApplicationData') }
        $DataDirectory = Join-Path $taskLocal 'DahanPhotoLibrary\runtime'
    }
    if (-not $DatabaseDirectory) { $DatabaseDirectory = $env:DAHAN_DATABASE_DIR }
    if (-not $DatabaseDirectory) { $DatabaseDirectory = $DataDirectory }
    if (-not $SourceDirectory) { $SourceDirectory = $env:DAHAN_SOURCE }
    foreach ($taskPath in @($DataDirectory, $DatabaseDirectory, $SourceDirectory)) {
        if ($taskPath -and $taskPath -notmatch '^([A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
            throw 'Use absolute Windows drive or UNC paths for runtime, database and original folders.'
        }
    }
    $env:DAHAN_DATA = $DataDirectory
    $env:DAHAN_DATABASE_DIR = $DatabaseDirectory
    $env:DAHAN_SOURCE = $SourceDirectory
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:OPENBLAS_NUM_THREADS = '1'
    $env:OMP_NUM_THREADS = '1'
}

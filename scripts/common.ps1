# Shared path handling; dot-sourcing this file does not start any work.
function Resolve-DahanPython {
    param([string]$PythonPath, [string]$ProjectRoot)
    $taskCandidates = @($PythonPath, $env:DAHAN_PYTHON,
        (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
        (Join-Path (Split-Path -Parent $ProjectRoot) 'venv\Scripts\python.exe'),
        'C:\DahanPhotoLibraryData\venv\Scripts\python.exe')
    if ($PythonPath -and -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'PythonPath does not exist. Supply the Python executable for this installation.'
    }
    foreach ($taskCandidate in $taskCandidates) {
        if ($taskCandidate -and (Test-Path -LiteralPath $taskCandidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $taskCandidate).Path
        }
    }
    throw 'Python was not found. Create .venv or supply -PythonPath / DAHAN_PYTHON.'
}

function Set-DahanPaths {
    param([string]$DataDirectory, [string]$DatabaseDirectory, [string]$SourceDirectory)
    if (-not $DataDirectory) { throw 'Supply -DataDirectory or set DAHAN_DATA; runtime storage must be explicit.' }
    if (-not $SourceDirectory) { throw 'Supply -SourceDirectory or set DAHAN_SOURCE for initial legacy-root registration.' }
    if (-not $DatabaseDirectory) { $DatabaseDirectory = $DataDirectory }
    foreach ($taskPath in @($DataDirectory, $DatabaseDirectory, $SourceDirectory)) {
        if ($taskPath -notmatch '^([A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
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

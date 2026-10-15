param(
    [switch]$FacesOnly,
    [string]$PythonPath = '',
    [string]$DataDirectory = $env:DAHAN_DATA,
    [string]$DatabaseDirectory = $env:DAHAN_DATABASE_DIR,
    [string]$SourceDirectory = $env:DAHAN_SOURCE
)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskProject
Set-DahanPaths -DataDirectory $DataDirectory -DatabaseDirectory $DatabaseDirectory -SourceDirectory $SourceDirectory
$env:DAHAN_REQUIRE_EXISTING_DATABASE = '1'
Push-Location -LiteralPath $taskProject
try {
    if ($FacesOnly) { & $taskPython -B -u -m backend.indexer --faces-only }
    else { & $taskPython -B -u -m backend.indexer }
    if ($LASTEXITCODE -ne 0) { throw 'Indexing failed; inspect the console output.' }
} finally { Pop-Location }

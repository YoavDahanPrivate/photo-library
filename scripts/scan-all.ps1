param(
    [ValidateRange(1,4)][int]$Workers = 2,
    [string]$PythonPath = '',
    [string]$DataDirectory = $env:DAHAN_DATA,
    [string]$DatabaseDirectory = $env:DAHAN_DATABASE_DIR,
    [string]$SourceDirectory = $env:DAHAN_SOURCE,
    [string]$BackupDirectory = $env:DAHAN_BACKUP_DIR
)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskProject
Set-DahanPaths -DataDirectory $DataDirectory -DatabaseDirectory $DatabaseDirectory -SourceDirectory $SourceDirectory
$env:DAHAN_REQUIRE_EXISTING_DATABASE = '1'
if ($BackupDirectory) { $env:DAHAN_BACKUP_DIR = $BackupDirectory }
$taskPauseFile = Join-Path $env:DAHAN_DATA 'scan-pause'
if (Test-Path -LiteralPath $taskPauseFile) { Remove-Item -LiteralPath $taskPauseFile }
Push-Location -LiteralPath $taskProject
try {
    & $taskPython -B -m backend.full_scan --workers $Workers
    if ($LASTEXITCODE -ne 0) { throw "Full scan exited with code $LASTEXITCODE" }
} finally { Pop-Location }

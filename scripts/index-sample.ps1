param([switch]$FacesOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\DahanPhotoLibraryData\cache'
$env:TMP = $env:TEMP
$pythonPath = 'D:\DahanPhotoLibraryData\venv\Scripts\python.exe'
if ($FacesOnly) { & $pythonPath -B -u -m backend.indexer --faces-only }
else { & $pythonPath -B -u -m backend.indexer }
if ($LASTEXITCODE -ne 0) { throw 'Indexing failed; inspect the console output.' }

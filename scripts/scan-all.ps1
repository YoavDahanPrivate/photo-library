param([ValidateRange(1,4)][int]$Workers = 2)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\DahanPhotoLibraryData\cache'
$env:TMP = $env:TEMP
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$pauseFile = 'D:\DahanPhotoLibraryData\prototype\scan-pause'
if (Test-Path -LiteralPath $pauseFile) { Remove-Item -LiteralPath $pauseFile }
Set-Location -LiteralPath $projectRoot
& 'D:\DahanPhotoLibraryData\venv\Scripts\python.exe' -B -m backend.full_scan --workers $Workers

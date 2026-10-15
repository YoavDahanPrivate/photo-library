param([string]$PythonPath = '', [string]$PlaywrightModule = '', [switch]$BrowserChecks)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskPython = Resolve-DahanPython -PythonPath $PythonPath -ProjectRoot $taskProject
Push-Location -LiteralPath $taskProject
try {
    & $taskPython -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend regression tests failed.' }
    & npm.cmd run build --prefix frontend -- --configLoader runner
    if ($LASTEXITCODE -ne 0) { throw 'Frontend type check/build failed.' }
    if ($BrowserChecks) {
        foreach ($taskCheck in @('people_progress_ui.cjs','auto_review_ui.cjs','matching_quality_ui.cjs')) {
            if ($PlaywrightModule) { & node (Join-Path $taskProject ('tests\'+$taskCheck)) $PlaywrightModule }
            else { & node (Join-Path $taskProject ('tests\'+$taskCheck)) }
            if ($LASTEXITCODE -ne 0) { throw "Browser check failed: $taskCheck" }
        }
    }
} finally { Pop-Location }

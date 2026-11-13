param([Parameter(Mandatory=$true)][string]$JobId,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
if ([IO.Path]::GetPathRoot($taskRoot) -ne 'D:\') { throw 'Host registration must use the completed D: production package.' }
$taskOwner=Get-Content -LiteralPath (Join-Path $taskRoot 'self-contained-owner.json') -Raw | ConvertFrom-Json
if ($taskOwner.job_id -ne $JobId) { throw 'Production ownership marker mismatch.' }
$taskBinary=Join-Path $taskRoot 'tunnel\cloudflared.exe'
$taskToken=Join-Path $taskRoot 'tunnel\tunnel.token'
$taskLauncher=Join-Path $taskRoot 'Start-DahanLibrary.ps1'
$taskStartup='C:\Users\user\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup'
$taskService=Get-CimInstance Win32_Service -Filter "Name='Cloudflared'"
if (-not $taskService) { throw 'Expected installed Cloudflared service is missing.' }
if ($taskService.PathName -notlike '"C:\Program Files (x86)\cloudflared\cloudflared.exe" *' -and $taskService.PathName -notlike ('"'+$taskBinary+'" *')) { throw 'Cloudflared service location changed unexpectedly; no changes made.' }
if ($taskService.PathName -notlike '*cloudflared.exe*tunnel run --token-file*' -or $taskService.PathName -match '\s--token\s') { throw 'Unrecognized service configuration; no changes made.' }
if ($taskService.PathName -notmatch '--token-file\s+(?:"([^"]+)"|(\S+))') { throw 'Cannot locate the existing tunnel token file.' }
$taskSourceToken=if($Matches[1]){$Matches[1]}else{$Matches[2]}
if (-not (Test-Path -LiteralPath $taskBinary -PathType Leaf) -or -not (Test-Path -LiteralPath $taskSourceToken -PathType Leaf)) { throw 'Tunnel executable or existing token file missing.' }
$taskCommand='"'+$taskBinary+'" tunnel run --token-file "'+$taskToken+'"'
if ($CheckOnly) { @{service='Cloudflared';binary=$taskBinary;token_source=$taskSourceToken;token_destination=$taskToken;startup_launcher=$taskLauncher;startup_directory=$taskStartup} | ConvertTo-Json;exit 0 }
$taskIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Windows Administrator is required for service registration.' }
$taskRollback=Join-Path $taskRoot 'host-registration-before.json'
if (-not (Test-Path -LiteralPath $taskRollback)) {
    @{name=$taskService.Name;path=$taskService.PathName;state=$taskService.State;start_mode=$taskService.StartMode;startup_shortcut=(Join-Path $taskStartup 'Dahan Photo Access.lnk')} | ConvertTo-Json | Set-Content -LiteralPath $taskRollback -Encoding UTF8
}
if ($taskSourceToken -ne $taskToken) {
    Copy-Item -LiteralPath $taskSourceToken -Destination ($taskToken+'.partial') -Force
    if ((Get-FileHash -LiteralPath $taskSourceToken).Hash -ne (Get-FileHash -LiteralPath ($taskToken+'.partial')).Hash) { throw 'Tunnel token copy verification failed.' }
    Move-Item -LiteralPath ($taskToken+'.partial') -Destination $taskToken -Force
}
if ($taskService.PathName -ne $taskCommand) {
    if ($taskService.State -eq 'Running') { Stop-Service Cloudflared -ErrorAction Stop }
    $taskChanged=Invoke-CimMethod -InputObject $taskService -MethodName Change -Arguments @{PathName=$taskCommand}
    if ($taskChanged.ReturnValue -ne 0) { throw "Tunnel service update failed with Windows code $($taskChanged.ReturnValue)." }
}
Start-Service Cloudflared -ErrorAction Stop
(Get-Service Cloudflared).WaitForStatus('Running',[TimeSpan]::FromSeconds(30))
New-Item -ItemType Directory -Path $taskStartup -Force | Out-Null
$taskShortcutPath=Join-Path $taskStartup 'Dahan Photo Access.lnk'
if (Test-Path -LiteralPath $taskShortcutPath) {
    $taskShortcutBackup=Join-Path $taskRoot 'startup-shortcut-before.lnk'
    if (-not (Test-Path -LiteralPath $taskShortcutBackup)) { Copy-Item -LiteralPath $taskShortcutPath -Destination $taskShortcutBackup }
}
$taskShell=New-Object -ComObject WScript.Shell
$taskShortcut=$taskShell.CreateShortcut($taskShortcutPath)
$taskShortcut.TargetPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskShortcut.Arguments='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$taskLauncher+'"'
$taskShortcut.WorkingDirectory=$taskRoot
$taskShortcut.WindowStyle=7
$taskShortcut.Save()
@{registered_local=(Get-Date -Format o);tunnel_binary=$taskBinary;startup_launcher=$taskLauncher;service='Running';backend_started=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'host-registration.json') -Encoding UTF8

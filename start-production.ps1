param(
    [string]$PythonPath,
    [string]$RuntimeDirectory,
    [string]$DatabaseDirectory,
    [string]$SourceDirectory,
    [string]$LogsDirectory,
    [string]$BackupDirectory,
    [string]$LanAddress,
    [int]$Port,
    [switch]$EnableSchedules,
    [switch]$SingleRun,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts\start-production.ps1') -ApplicationDirectory $PSScriptRoot @PSBoundParameters

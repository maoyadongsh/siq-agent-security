# Probe well-known platform dirs and call `agentshield adapter install`.
$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Find-Bin {
    if ($env:AGENTSHIELD_BIN -and (Test-Path $env:AGENTSHIELD_BIN)) {
        return $env:AGENTSHIELD_BIN
    }
    $cmd = Get-Command agentshield -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $repo = Join-Path $SkillDir "..\..\apps\agentshield\agentshield.exe"
    if (Test-Path $repo) { return (Resolve-Path $repo).Path }
    throw "adapter.ps1: run scripts/bootstrap.ps1 first"
}

$Bin = Find-Bin
if ($args.Count -gt 0) {
    & $Bin adapter install $args[0]
} else {
    & $Bin adapter install
}

# Probe well-known platform dirs and call `siq-agent-security adapter install`.
$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Find-Bin {
    foreach ($v in @($env:SIQ_AGENT_SECURITY_BIN, $env:AGENTSHIELD_BIN)) {
        if ($v -and (Test-Path $v)) { return $v }
    }
    foreach ($name in @("siq-agent-security", "agentshield")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    foreach ($leaf in @("siq-agent-security.exe", "agentshield.exe")) {
        $repo = Join-Path $SkillDir "..\..\apps\agentshield\$leaf"
        if (Test-Path $repo) { return (Resolve-Path $repo).Path }
    }
    throw "adapter.ps1: run scripts/bootstrap.ps1 first"
}

$Bin = Find-Bin
if ($args.Count -gt 0) {
    & $Bin adapter install $args[0]
} else {
    & $Bin adapter install
}

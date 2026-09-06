# Probe well-known platform dirs, verify release manifest, then call adapter install.
# Shares the same trust root and verify_manifest.py path as bootstrap.ps1 (DEV04-B).
$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Manifest = Join-Path $SkillDir "skill-manifest.json"
$VerifyPy = Join-Path $SkillDir "scripts\verify_manifest.py"
$ReleasePubKeyB64 = 'LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY='

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

function Find-Python {
    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "adapter.ps1: python3 required to verify skill-manifest.json"
}

if (-not (Test-Path $Manifest)) {
    throw "adapter.ps1: skill-manifest.json missing; refusing to run unverified binary"
}

$Bin = Find-Bin
$Py = Find-Python
$verifyArgs = @($VerifyPy, "--manifest", $Manifest, "--pubkey", $ReleasePubKeyB64, "--skill-dir", $SkillDir, "--bin", $Bin)
if (-not $env:SIQ_AGENT_SECURITY_REQUIRE_PINNED -and -not $env:AGENTSHIELD_REQUIRE_PINNED) {
    $verifyArgs += "--allow-local"
}
$stageRoot = if ($env:SIQ_AGENT_SECURITY_STAGE_DIR) { $env:SIQ_AGENT_SECURITY_STAGE_DIR } else { Join-Path $env:TEMP "siq-agent-security-stage-$PID" }
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
$verifyArgs += @("--stage-to", $stageRoot)
$staged = & $Py @verifyArgs | Select-Object -Last 1
if ($LASTEXITCODE -ne 0 -or -not $staged) {
    throw "adapter.ps1: skill-manifest.json verification or staging failed"
}
$Bin = "$staged".Trim()
if (-not (Test-Path $Bin)) {
    throw "adapter.ps1: staged binary missing: $Bin"
}

if ($args.Count -gt 0) {
    & $Bin adapter install $args[0]
} else {
    & $Bin adapter install
}

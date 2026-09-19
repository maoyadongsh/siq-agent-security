# Locate or verify siq-agent-security.exe, then start serve on loopback.
# Never run a downloaded file until its sha256 matches skill-manifest.json.
$ErrorActionPreference = "Stop"

$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Manifest = Join-Path $SkillDir "skill-manifest.json"
$VerifyPy = Join-Path $SkillDir "scripts\verify_manifest.py"
$Port = if ($env:SIQ_AGENT_SECURITY_PORT) { [int]$env:SIQ_AGENT_SECURITY_PORT } elseif ($env:AGENTSHIELD_PORT) { [int]$env:AGENTSHIELD_PORT } else { 47611 }

# v1 local trust root (Ed25519, base64). Used to verify skill-manifest.json.
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
        $local = Join-Path $env:LOCALAPPDATA "siq-agent-security\$leaf"
        if (Test-Path $local) { return $local }
        $legacy = Join-Path $env:LOCALAPPDATA "agentshield\$leaf"
        if (Test-Path $legacy) { return $legacy }
    }
    foreach ($leaf in @("siq-agent-security.exe", "agentshield.exe")) {
        $repo = Join-Path $SkillDir "..\..\apps\agentshield\$leaf"
        if (Test-Path $repo) { return (Resolve-Path $repo).Path }
    }
    return $null
}

function Find-Python {
    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "python3 required to verify skill-manifest.json"
}

if (-not (Test-Path $Manifest)) {
    throw "skill-manifest.json missing; refusing to start"
}

$Bin = Find-Bin
$Py = Find-Python
$stageRoot = if ($env:SIQ_AGENT_SECURITY_STAGE_DIR) { $env:SIQ_AGENT_SECURITY_STAGE_DIR } else { Join-Path $env:TEMP "siq-agent-security-stage-$PID" }
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
if ($Bin) {
    $verifyArgs = @($VerifyPy, "--manifest", $Manifest, "--pubkey", $ReleasePubKeyB64, "--skill-dir", $SkillDir, "--bin", $Bin)
    if (-not $env:SIQ_AGENT_SECURITY_REQUIRE_PINNED -and -not $env:AGENTSHIELD_REQUIRE_PINNED) {
        $verifyArgs += "--allow-local"
    }
    $verifyArgs += @("--stage-to", $stageRoot)
} elseif ($env:SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD -eq "1") {
    # DEV04-E: download only after signed-manifest verify; pin sha256+bytes.
    $verifyArgs = @($VerifyPy, "--manifest", $Manifest, "--pubkey", $ReleasePubKeyB64, "--skill-dir", $SkillDir, "--fetch-artifact", "--stage-to", $stageRoot)
} else {
    throw "siq-agent-security binary not found. Set SIQ_AGENT_SECURITY_BIN. To download a pinned release artifact after signed-manifest verify, set SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1."
}
$staged = & $Py @verifyArgs | Select-Object -Last 1
if ($LASTEXITCODE -ne 0 -or -not $staged) {
    throw "siq-agent-security-bootstrap: skill-manifest.json verification or staging failed"
}
$Bin = "$staged".Trim()
if (-not (Test-Path $Bin)) {
    throw "siq-agent-security-bootstrap: staged binary missing: $Bin"
}

Write-Host "siq-agent-security-bootstrap: using $Bin"
& $Bin version

$tcp = $null
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", $Port)
    Write-Host "siq-agent-security-bootstrap: serve already listening on 127.0.0.1:$Port"
} catch {
    Write-Host "siq-agent-security-bootstrap: starting serve on 127.0.0.1:$Port"
    Start-Process -FilePath $Bin -ArgumentList @("serve", "--port", "$Port") -WindowStyle Hidden
    Start-Sleep -Seconds 1
} finally {
    if ($tcp) { $tcp.Close() }
}

Write-Host "siq-agent-security-bootstrap: console http://127.0.0.1:$Port  (token is <state>/token; never print it)"
Write-Host "siq-agent-security-bootstrap: next scripts/adapter.ps1"
Write-Output $Bin

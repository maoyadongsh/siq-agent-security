# Locate or verify agentshield.exe, then start serve on loopback.
# Never run a downloaded file until its sha256 matches skill-manifest.json.
$ErrorActionPreference = "Stop"

$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Manifest = Join-Path $SkillDir "skill-manifest.json"
$VerifyPy = Join-Path $SkillDir "scripts\verify_manifest.py"
$Port = if ($env:AGENTSHIELD_PORT) { [int]$env:AGENTSHIELD_PORT } else { 47611 }

# v1 local trust root (Ed25519, base64). Used to verify skill-manifest.json.
$ReleasePubKeyB64 = 'LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY='

function Find-Bin {
    if ($env:AGENTSHIELD_BIN -and (Test-Path $env:AGENTSHIELD_BIN)) {
        return $env:AGENTSHIELD_BIN
    }
    $cmd = Get-Command agentshield -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $env:LOCALAPPDATA "agentshield\agentshield.exe"
    if (Test-Path $local) { return $local }
    $repo = Join-Path $SkillDir "..\..\apps\agentshield\agentshield.exe"
    if (Test-Path $repo) { return (Resolve-Path $repo).Path }
    throw "agentshield binary not found. Set AGENTSHIELD_BIN. Refusing to download without a signed skill-manifest.json."
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
$verifyArgs = @($VerifyPy, "--manifest", $Manifest, "--pubkey", $ReleasePubKeyB64, "--bin", $Bin)
if (-not $env:AGENTSHIELD_REQUIRE_PINNED) {
    $verifyArgs += "--allow-local"
}
& $Py @verifyArgs
if ($LASTEXITCODE -ne 0) {
    throw "skill-manifest.json verification failed"
}

Write-Host "agentshield-bootstrap: using $Bin"
& $Bin version

$tcp = $null
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", $Port)
    Write-Host "agentshield-bootstrap: serve already listening on 127.0.0.1:$Port"
} catch {
    Write-Host "agentshield-bootstrap: starting serve on 127.0.0.1:$Port"
    Start-Process -FilePath $Bin -ArgumentList @("serve", "--port", "$Port") -WindowStyle Hidden
    Start-Sleep -Seconds 1
} finally {
    if ($tcp) { $tcp.Close() }
}

Write-Host "agentshield-bootstrap: console http://127.0.0.1:$Port  (token is <state>/token; never print it)"
Write-Host "agentshield-bootstrap: next scripts/adapter.ps1"
Write-Output $Bin

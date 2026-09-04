# Locate or verify agentshield.exe, then start serve on loopback.
# Never run a downloaded file until its sha256 matches skill-manifest.json.
$ErrorActionPreference = "Stop"

$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Manifest = Join-Path $SkillDir "skill-manifest.json"
$Port = if ($env:AGENTSHIELD_PORT) { [int]$env:AGENTSHIELD_PORT } else { 47611 }

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

$Bin = Find-Bin
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

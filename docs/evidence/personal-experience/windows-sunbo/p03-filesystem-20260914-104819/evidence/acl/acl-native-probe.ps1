param(
    [Parameter(Mandatory)][string]$BinaryPath,
    [Parameter(Mandatory)][string]$FixtureRoot,
    [Parameter(Mandatory)][string]$OutputPath,
    [string]$SourceCandidate = 'ebc472f2e46aa7de837afe9d6a0ed422eef51cd0',
    [string]$ExpectedBinaryHash = '4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:ProbeRoot = [IO.Path]::GetFullPath($FixtureRoot)
$script:CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$script:SystemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$script:AdminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$script:EveryoneSid = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
$binary = [IO.Path]::GetFullPath($BinaryPath)
$actualBinaryHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualBinaryHash -ne $ExpectedBinaryHash) { throw 'Binary hash does not match supplied candidate' }
if (Test-Path -LiteralPath $script:ProbeRoot) { throw 'Fixture root already exists; choose a new path' }
if (Test-Path -LiteralPath $OutputPath) { throw 'Output already exists; preserve it and choose a new path' }
$repo = (Get-Location).Path
$expectedParent = [IO.Path]::GetFullPath((Join-Path $repo '.tmp/win-p03-next'))
if ([IO.Path]::GetDirectoryName($script:ProbeRoot) -cne $expectedParent) { throw 'Fixture root must be a direct child of this batch root' }
if ((Get-Item -LiteralPath $expectedParent).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Batch root must not be a reparse point' }
$sourceHeadStart = (& git rev-parse HEAD).Trim()
$sourceDirtyStart = -not [string]::IsNullOrWhiteSpace((& git status --porcelain | Out-String))

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SiqAclProbeNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct Trustee {
        public IntPtr Multiple;
        public int Operation;
        public int Form;
        public int Type;
        public IntPtr Name;
    }
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool GetSecurityDescriptorDacl(IntPtr descriptor, out bool present, out IntPtr dacl, out bool defaulted);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode)]
    static extern uint GetEffectiveRightsFromAclW(IntPtr dacl, ref Trustee trustee, out uint rights);
    public static uint[] Effective(byte[] descriptor, byte[] sid) {
        var descriptorHandle = GCHandle.Alloc(descriptor, GCHandleType.Pinned);
        var sidHandle = GCHandle.Alloc(sid, GCHandleType.Pinned);
        try {
            bool present, defaulted;
            IntPtr dacl;
            if (!GetSecurityDescriptorDacl(descriptorHandle.AddrOfPinnedObject(), out present, out dacl, out defaulted))
                return new uint[] { (uint)Marshal.GetLastWin32Error(), 0 };
            if (!present || dacl == IntPtr.Zero) return new uint[] { 0, 0xffffffff };
            var trustee = new Trustee { Form=0, Type=0, Name=sidHandle.AddrOfPinnedObject() };
            uint mask;
            uint error = GetEffectiveRightsFromAclW(dacl, ref trustee, out mask);
            return new uint[] { error, mask };
        } finally { sidHandle.Free(); descriptorHandle.Free(); }
    }
}
'@

function Assert-OwnedPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -cne $script:ProbeRoot -and -not $full.StartsWith($script:ProbeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw 'Operation escaped the newly owned fixture root'
    }
    if ((Test-Path -LiteralPath $full) -and ((Get-Item -LiteralPath $full -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Fixture path unexpectedly became a reparse point'
    }
    return $full
}
function Set-FixtureDirectoryAcl([string]$Path, [bool]$EveryoneRead = $false, [bool]$DenyCurrentCreate = $false) {
    $owned = Assert-OwnedPath $Path
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($script:CurrentSid)
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    foreach ($sid in @($script:CurrentSid, $script:SystemSid, $script:AdminSid)) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', $inherit, 'None', 'Allow'))
    }
    if ($EveryoneRead) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($script:EveryoneSid, 'ReadAndExecute', $inherit, 'None', 'Allow')) }
    if ($DenyCurrentCreate) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($script:CurrentSid, 'CreateFiles, CreateDirectories', 'None', 'None', 'Deny')) }
    Set-Acl -LiteralPath $owned -AclObject $acl
}
function Get-TrusteeAlias($Sid) {
    if ($Sid.Value -eq $script:CurrentSid.Value) { return 'current_user' }
    if ($Sid.Value -eq $script:SystemSid.Value) { return 'SYSTEM' }
    if ($Sid.Value -eq $script:AdminSid.Value) { return 'Administrators' }
    if ($Sid.Value -eq $script:EveryoneSid.Value) { return 'Everyone' }
    return 'other_trustee'
}
function Get-Snapshot([string]$Path) {
    $owned = Assert-OwnedPath $Path
    $item = Get-Item -LiteralPath $owned -Force
    $acl = Get-Acl -LiteralPath $owned
    $descriptor = $acl.GetSecurityDescriptorBinaryForm()
    $everyone = [byte[]]::new($script:EveryoneSid.BinaryLength)
    $script:EveryoneSid.GetBinaryForm($everyone, 0)
    $effective = [SiqAclProbeNative]::Effective($descriptor, $everyone)
    $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier])
    return [ordered]@{
        path = [IO.Path]::GetRelativePath($script:ProbeRoot, $owned).Replace('\','/')
        directory = [bool]$item.PSIsContainer
        attributes = [string]$item.Attributes
        owner = Get-TrusteeAlias $ownerSid
        inheritance_protected = $acl.AreAccessRulesProtected
        descriptor_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($descriptor)).ToLowerInvariant()
        entries = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | ForEach-Object {
            [ordered]@{trustee=Get-TrusteeAlias $_.IdentityReference;type=[string]$_.AccessControlType;rights=[string]$_.FileSystemRights;mask=[int64]$_.FileSystemRights;inherited=$_.IsInherited;inheritance=[string]$_.InheritanceFlags;propagation=[string]$_.PropagationFlags}
        })
        everyone_effective_rights = [ordered]@{api='GetEffectiveRightsFromAclW';win32_error=$effective[0];mask=('0x{0:x8}' -f $effective[1]);file_read_data=(($effective[1] -band 1) -ne 0);file_write_data=(($effective[1] -band 2) -ne 0);scope='DACL trustee calculation only; no second-user logon or access-token test'}
    }
}
function Invoke-Candidate([string]$Case, [string]$StatePath, [string[]]$Arguments) {
    $owned = Assert-OwnedPath $StatePath
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $binary
    $psi.WorkingDirectory = $script:ProbeRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $psi.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $psi.Environment.Clear()
    $psi.Environment['SystemRoot'] = $env:SystemRoot
    $psi.Environment['WINDIR'] = $env:WINDIR
    $psi.Environment['TEMP'] = Join-Path $script:ProbeRoot '_temp'
    $psi.Environment['TMP'] = $psi.Environment['TEMP']
    $psi.Environment['SIQ_AGENT_SECURITY_STATE_DIR'] = $owned
    foreach ($arg in $Arguments) { $psi.ArgumentList.Add($arg) }
    $proc = [Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw 'Failed to start owned candidate child' }
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $timedOut = -not $proc.WaitForExit(45000)
    if ($timedOut) { $proc.Kill(); $proc.WaitForExit() }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $proc.ExitCode
    $proc.Dispose()
    [IO.File]::WriteAllText((Join-Path $script:ProbeRoot ('_private-logs/'+$Case+'.stdout.txt')), $stdout, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $script:ProbeRoot ('_private-logs/'+$Case+'.stderr.txt')), $stderr, [Text.UTF8Encoding]::new($false))
    $summary = [ordered]@{case=$Case;command=@($Arguments);exit_code=$exitCode;timeout=$timedOut;stdout_bytes=[Text.Encoding]::UTF8.GetByteCount($stdout);stderr_bytes=[Text.Encoding]::UTF8.GetByteCount($stderr);access_denied_diagnostic=($stderr -match 'Access is denied|拒绝访问|Permission denied');error_raw_archived=$false}
    if ($Arguments[0] -eq 'init' -and $exitCode -eq 0) { $summary['initialization_status'] = ($stdout | ConvertFrom-Json).status }
    if ($Arguments[0] -eq 'pubkey' -and $exitCode -eq 0) { $summary['public_key_decodes_to_32_bytes'] = ([Convert]::FromBase64String($stdout.Trim()).Length -eq 32) }
    return $summary
}

New-Item -ItemType Directory -Path $script:ProbeRoot | Out-Null
Set-FixtureDirectoryAcl $script:ProbeRoot
foreach ($sub in @('_private-logs','_temp','private-generated','public-broad-parent','deny-create','attribute-marker','attribute-directory')) {
    New-Item -ItemType Directory -Path (Join-Path $script:ProbeRoot $sub) | Out-Null
}
$outerBefore = Get-Snapshot $script:ProbeRoot
if ($outerBefore.everyone_effective_rights.win32_error -ne 0 -or $outerBefore.everyone_effective_rights.file_read_data -or $outerBefore.entries.Count -ne 3) { throw 'Private outer ACL verification failed' }
$cases = [Collections.Generic.List[object]]::new()
$snapshots = [Collections.Generic.List[object]]::new()

$privateState = Join-Path $script:ProbeRoot 'private-generated/state'
$cases.Add((Invoke-Candidate 'private-init' $privateState @('init')))
$privateBeforeKey = Get-Snapshot (Join-Path $privateState 'keys')
if ($privateBeforeKey.everyone_effective_rights.win32_error -ne 0 -or $privateBeforeKey.everyone_effective_rights.file_read_data -or @($privateBeforeKey.entries | Where-Object {$_.trustee -eq 'other_trustee' -or $_.trustee -eq 'Everyone'}).Count -ne 0) { throw 'Private key parent is not restrictive' }
$cases.Add((Invoke-Candidate 'private-pubkey-generation' $privateState @('pubkey')))
foreach ($relative in @('','keys','keys/signing.seed','backups')) { $snapshots.Add((Get-Snapshot (Join-Path $privateState $relative))) }

$broadParent = Join-Path $script:ProbeRoot 'public-broad-parent'
Set-FixtureDirectoryAcl $broadParent $true
$broadState = Join-Path $broadParent 'state'
$cases.Add((Invoke-Candidate 'broad-init-no-secret-generation' $broadState @('init')))
$noRandomSecrets = (-not (Test-Path -LiteralPath (Join-Path $broadState 'keys/signing.seed'))) -and (-not (Test-Path -LiteralPath (Join-Path $broadState 'token')))
if (-not $noRandomSecrets) { throw 'Unexpected credential generation in public-only fixture' }
foreach ($relative in @('','keys','config.json','state-format.json','backups')) { $snapshots.Add((Get-Snapshot (Join-Path $broadState $relative))) }
# The following seed is deliberately public, deterministic test material, never a generated secret.
# No service is started and no admission/grant/receipt is issued under this test identity.
$publicSeedPath = Join-Path $broadState 'keys/signing.seed'
[IO.File]::WriteAllText($publicSeedPath, [Convert]::ToBase64String([byte[]]::new(32)), [Text.UTF8Encoding]::new($false))
$publicSeedBefore = Get-Snapshot $publicSeedPath
$publicSeedBytesHash = (Get-FileHash -LiteralPath $publicSeedPath).Hash
$cases.Add((Invoke-Candidate 'broad-preexisting-public-seed-load' $broadState @('pubkey')))
$publicSeedAfter = Get-Snapshot $publicSeedPath
$snapshots.Add($publicSeedBefore)
$publicSeedUnchanged = $publicSeedBytesHash -eq (Get-FileHash -LiteralPath $publicSeedPath).Hash -and $publicSeedBefore.descriptor_sha256 -eq $publicSeedAfter.descriptor_sha256
$backupMarker = Join-Path $broadState 'backups/public-marker.txt'
[IO.File]::WriteAllText($backupMarker, 'PUBLIC SYNTHETIC MARKER - NO SECRET', [Text.UTF8Encoding]::new($false))
$snapshots.Add((Get-Snapshot $backupMarker))

$deniedState = Join-Path $script:ProbeRoot 'deny-create'
Set-FixtureDirectoryAcl $deniedState $false $true
$denyBefore = Get-Snapshot $deniedState
$cases.Add((Invoke-Candidate 'explicit-dacl-deny-create-init' $deniedState @('init')))
$denyAfter = Get-Snapshot $deniedState
$snapshots.Add($denyAfter)
$denyPreserved = $denyBefore.descriptor_sha256 -eq $denyAfter.descriptor_sha256
$denyNoFiles = @(Get-ChildItem -LiteralPath $deniedState -Force).Count -eq 0

$marker = Join-Path $script:ProbeRoot 'attribute-marker/public-marker.txt'
[IO.File]::WriteAllText($marker, 'PUBLIC ATTRIBUTE MARKER', [Text.UTF8Encoding]::new($false))
$attributeBefore = Get-Snapshot $marker
[IO.File]::SetAttributes($marker, ([IO.File]::GetAttributes($marker) -bor [IO.FileAttributes]::ReadOnly))
$attributeReadonly = Get-Snapshot $marker
$writeRejected = $false
$writeError = $null
try { [IO.File]::AppendAllText($marker, 'APPEND') } catch { $writeRejected = $true; $writeError = $_.Exception.GetBaseException().HResult }
[IO.File]::SetAttributes($marker, ([IO.File]::GetAttributes($marker) -band (-bnot [IO.FileAttributes]::ReadOnly)))
[IO.File]::AppendAllText($marker, 'RESTORED')
$attributeRestored = Get-Snapshot $marker
$snapshots.Add($attributeReadonly)
$attributeObservation = [ordered]@{method='Win32 ReadOnly attribute via .NET; Go Chmod mapping separately source-reviewed';file_write_rejected=$writeRejected;write_error_hresult=$writeError;file_append_succeeded_after_attribute_restore=$true;dacl_unchanged=($attributeBefore.descriptor_sha256 -eq $attributeReadonly.descriptor_sha256 -and $attributeBefore.descriptor_sha256 -eq $attributeRestored.descriptor_sha256)}

$attributeDir = Join-Path $script:ProbeRoot 'attribute-directory'
[IO.File]::SetAttributes($attributeDir, ([IO.File]::GetAttributes($attributeDir) -bor [IO.FileAttributes]::ReadOnly))
$dirBefore = Get-Snapshot $attributeDir
$cases.Add((Invoke-Candidate 'readonly-directory-attribute-init' (Join-Path $attributeDir 'state') @('init')))
$dirAfter = Get-Snapshot $attributeDir
$snapshots.Add($dirAfter)
$attributeObservation['directory_readonly_attribute_retained'] = (($dirAfter.attributes -split ',\s*') -contains 'ReadOnly')
$attributeObservation['directory_dacl_unchanged'] = $dirBefore.descriptor_sha256 -eq $dirAfter.descriptor_sha256

$outerAfter = Get-Snapshot $script:ProbeRoot
$sourceHeadEnd = (& git rev-parse HEAD).Trim()
$sourceDirtyEnd = -not [string]::IsNullOrWhiteSpace((& git status --porcelain | Out-String))
$result = [ordered]@{
    schema_version='windows-acl-native-diagnostics/v1'
    observed_at_utc=[DateTime]::UtcNow.ToString('o')
    candidate_sha=$SourceCandidate
    binary_sha256=$actualBinaryHash
    worktree_head_start=$sourceHeadStart
    worktree_head_end=$sourceHeadEnd
    source_dirty_start=$sourceDirtyStart
    source_dirty_end=$sourceDirtyEnd
    method='Windows native candidate init/pubkey plus DACL trustee observation and public-marker attribute fixture'
    generated_random_secrets_only_under_verified_private_acl=$true
    broad_fixture_secret_files_absent_after_init=$noRandomSecrets
    broad_seed_type='Public deterministic 32-zero-byte seed; no server or signed business object; not a real secret'
    broad_random_secret_generation_tested=$false
    public_seed_bytes_and_dacl_preserved=$publicSeedUnchanged
    explicit_create_denial_dacl_preserved=$denyPreserved
    explicit_create_denial_no_files=$denyNoFiles
    readonly_attribute_observation=$attributeObservation
    outer_acl_before=$outerBefore
    outer_acl_after=$outerAfter
    outer_acl_preserved=($outerBefore.descriptor_sha256 -eq $outerAfter.descriptor_sha256)
    commands=$cases.ToArray()
    acl_observations=$snapshots.ToArray()
    second_user_access_tested=$false
    backup_acl_preservation_tested=$false
    system_users_created=0
    elevation_requested=$false
    system_tasks_created=0
    parent_acl_modified=$false
    production_host_configuration_modified=$false
    original_logs_archived=$false
    limits=@('GetEffectiveRightsFromAclW observes DACL trustee rights, not a real second-user token, privilege or logon session','Private outer directory is not assumed to prevent child access when traversal checks can be bypassed','Broad-ACL fresh random key generation remains source-based inference; only a known public fixture seed is loaded there','Backup directory/marker ACL observation is not real migration or backup permission-preservation acceptance','No live decision service, model call, approval or tool execution')
}
[IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), ($result | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
[ordered]@{result_written=$true;command_count=$cases.Count;outer_acl_preserved=$result.outer_acl_preserved;explicit_deny_no_files=$denyNoFiles;source_dirty_end=$sourceDirtyEnd} | ConvertTo-Json

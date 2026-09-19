param([string]$Root, [string]$Target, [string]$Mode, [string]$Restore)
$ErrorActionPreference = 'Stop'
$rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$targetFull = [IO.Path]::GetFullPath($Target)
if ($targetFull -ne $rootFull -and -not $targetFull.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Outside test root' }
if ($rootFull -notlike '*\skill-native-update-r1') { throw 'Unexpected fixture root' }
$acl = Get-Acl -LiteralPath $targetFull
if ($Mode -eq 'audit') {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $unknown = 0
    $classes = @()
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow) {
            $sid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($sid -eq $current) { $classes += 'current_user' }
            elseif ($sid -eq 'S-1-5-18') { $classes += 'system' }
            elseif ($sid -eq 'S-1-5-32-544') { $classes += 'administrators' }
            else { $unknown += 1 }
        }
    }
    @{owner_current=($owner -eq $current); protected=$acl.AreAccessRulesProtected; allowed_classes=$classes; unknown_allow_count=$unknown} | ConvertTo-Json -Compress
    exit
}
if ($Mode -eq 'read') { $acl.Sddl; exit }

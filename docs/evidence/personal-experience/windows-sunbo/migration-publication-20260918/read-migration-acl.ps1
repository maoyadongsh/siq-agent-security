param([string]$Root)
$ErrorActionPreference = 'Stop'
$rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
if ($rootFull -notlike '*\migration-native-acl-r1\journey\state\state-migration-v2') { throw 'Unexpected audit root' }
$current = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rows = @()
$items = @((Get-Item -LiteralPath $rootFull)) + @(Get-ChildItem -LiteralPath $rootFull -Recurse -Force)
foreach ($item in $items) {
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point rejected' }
    $acl = Get-Acl -LiteralPath $item.FullName
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
    $rows += @{relative_path=$item.FullName.Substring($rootFull.Length).TrimStart('\');directory=$item.PSIsContainer;owner_current=($owner -eq $current);protected=$acl.AreAccessRulesProtected;allowed_classes=$classes;unknown_allow_count=$unknown}
}
ConvertTo-Json -Depth 6 -InputObject $rows

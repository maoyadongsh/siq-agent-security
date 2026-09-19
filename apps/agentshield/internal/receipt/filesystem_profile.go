package receipt

import (
	"strings"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
)

func verifiedResourceProfile(c *IntentContract) runtimeaction.FilesystemProfile {
	if c != nil && c.Trusted != nil {
		return c.Trusted.ResourceProfile()
	}
	return runtimeaction.FilesystemPOSIXV1
}

// Invalid profile or unavailable signed file identity is an Authority failure,
// never an advisory policy denial that warn can relax.
func filesystemAuthority(req Request, g *grant.Grant, d runtimeaction.Descriptor, unselected bool) string {
	if g == nil {
		if req.resourceProfile == runtimeaction.FilesystemWindowsLocalDriveV1 {
			return "intent_grant_profile_mismatch"
		}
		return ""
	}
	if grant.ValidateFilesystemProfile(*g) != nil {
		return "intent_grant_profile_mismatch"
	}
	if g.SchemaVersion == "" {
		if req.resourceProfile == runtimeaction.FilesystemWindowsLocalDriveV1 {
			return "intent_grant_profile_mismatch"
		}
		return ""
	}
	if unselected || req.resourceProfile != runtimeaction.FilesystemWindowsLocalDriveV1 || g.FilesystemProfile != string(req.resourceProfile) {
		return "intent_grant_profile_mismatch"
	}
	if d.ResourceError != nil || grant.RecheckFilesystemBindings(*g) != nil {
		return "intent_filesystem_identity_unavailable"
	}
	for _, target := range d.Paths {
		if _, err := runtimepath.InspectWindows(target, d.FilesystemWriteHint); err != nil {
			return "intent_filesystem_identity_unavailable"
		}
	}
	return ""
}

func windowsPathGranted(g *grant.Grant, target string, write bool) (string, bool) {
	id, allowed, _ := windowsPathMatch(g, target, write)
	return id, allowed
}

func windowsPathMatch(g *grant.Grant, target string, write bool) (string, bool, error) {
	if grant.ValidateFilesystemProfile(*g) != nil || g.SchemaVersion != "grant/v2" {
		return "", false, runtimepath.ErrUnverified
	}
	observed, err := runtimepath.InspectWindows(target, write)
	if err != nil {
		return "", false, runtimepath.ErrUnverified
	}
	target = observed.Path()
	matched := ""
	for _, f := range g.Facts {
		if f.Domain != "filesystem" || (f.Action != "fs.read" && f.Action != "fs.write") || write && f.Action != "fs.write" {
			continue
		}
		pattern := f.Resource.Value
		if pattern == "*" && f.Effect == "deny" {
			return "", false, nil
		}
		if target != pattern && !strings.HasPrefix(target, strings.TrimSuffix(pattern, "/")+"/") {
			continue
		}
		actual, err := observed.AncestorIdentityDigest(pattern)
		if err != nil || actual != (*g.FilesystemBindings)[f.FactID] {
			return "", false, runtimepath.ErrUnverified
		}
		if f.Effect == "deny" {
			return "", false, nil
		}
		if f.Effect == "allow" {
			matched = f.FactID
		}
	}
	return matched, matched != "", nil
}

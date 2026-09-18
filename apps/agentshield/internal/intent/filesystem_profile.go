package intent

import (
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// ResourceProfile is selected exclusively by a validated, signed contract.
// Callers must never replace this with GOOS or a request-derived choice.
func (c Contract) ResourceProfile() runtimeaction.FilesystemProfile {
	if (c.SchemaVersion == "intent/v4" && c.AuthorityKind == "instance_permission" || c.SchemaVersion == RuntimeCheckSchema && c.AuthorityKind == "runtime_check") && c.FilesystemProfile == string(runtimeaction.FilesystemWindowsLocalDriveV1) {
		return runtimeaction.FilesystemWindowsLocalDriveV1
	}
	if (c.SchemaVersion == "intent/v2" || c.SchemaVersion == "intent/v3") && c.AuthorityKind == "" && c.FilesystemProfile == "" {
		return runtimeaction.FilesystemPOSIXV1
	}
	return ""
}

func (s *Store) checkProfileState(c Contract) error {
	if c.windowsProfileContract() && stateformat.RequireWindowsProfile(filepath.Dir(s.dir)) != nil {
		return violation("intent_filesystem_profile_unavailable")
	}
	return nil
}

func permissionDigestSchema(g *grant.Grant) string {
	if g != nil && g.SchemaVersion == "grant/v2" {
		return "grant-permissions/v2"
	}
	return ""
}

func bindingProfileMatches(c Contract, b Binding, g *grant.Grant) bool {
	if c.windowsProfileContract() {
		return b.SchemaVersion == "intent-grant-binding/v2" && g != nil && g.SchemaVersion == "grant/v2" && g.FilesystemProfile == c.FilesystemProfile && b.GrantRef != nil && b.GrantRef.PermissionDigestSchema == "grant-permissions/v2"
	}
	return b.SchemaVersion == "" && (g == nil || g.SchemaVersion == "") && (b.GrantRef == nil || b.GrantRef.PermissionDigestSchema == "")
}

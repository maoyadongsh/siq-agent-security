package server

import (
	"encoding/json"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// Interpretation is recovered from the exact signed authority that produced
// this action; current binding/Grant checks prevent a stale action reviving it.
func (s *Server) fileActionProfile(a effectevidence.Action) (runtimeaction.FilesystemProfile, error) {
	if a.IntentID == "" && a.IntentDigest == "" {
		return runtimeaction.FilesystemPOSIXV1, nil
	}
	if s.intents == nil || a.IntentID == "" || a.IntentDigest == "" {
		return "", effectevidence.ErrCorrelation
	}
	c, err := s.intents.Get(a.IntentID)
	if err != nil || c.SchemaVersion == intent.RuntimeCheckSchema || c.Digest != a.IntentDigest || c.TaskID != a.TaskID || c.Agent.ID != a.AgentID || c.Agent.Platform != a.Platform || c.Active(time.Now()) != nil {
		return "", effectevidence.ErrCorrelation
	}
	current, binding, err := s.intents.ResolveBinding(a.Platform, a.SessionID, a.AgentID)
	if err != nil || current == nil || binding == nil || current.IntentID != c.IntentID || current.Digest != c.Digest || binding.IntentDigest != c.Digest || binding.TaskID != a.TaskID {
		return "", effectevidence.ErrCorrelation
	}
	profile := c.ResourceProfile()
	if profile == runtimeaction.FilesystemWindowsLocalDriveV1 {
		if binding.SelectedGrant == nil || binding.SelectedGrant.SchemaVersion != "grant/v2" || binding.SelectedGrant.FilesystemProfile != string(profile) || grant.RecheckFilesystemBindings(*binding.SelectedGrant) != nil || s.runtimeIdentities == nil || s.runtimeIdentities.VerifySessionAuthority(c, a.SessionID) != nil {
			return "", effectevidence.ErrCorrelation
		}
	} else if profile != runtimeaction.FilesystemPOSIXV1 {
		return "", effectevidence.ErrCorrelation
	}
	return profile, nil
}

func fileResourceForProfile(profile runtimeaction.FilesystemProfile, path string) (string, error) {
	if profile == runtimeaction.FilesystemPOSIXV1 {
		return fileResource(path)
	}
	if profile != runtimeaction.FilesystemWindowsLocalDriveV1 || len(path) > 4096 {
		return "", effectevidence.ErrInvalid
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(profile, "filesystem", path)
	if err != nil {
		return "", effectevidence.ErrInvalid
	}
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: canonical}})
	return effectevidence.ResourceReference(refs[0])
}

func snapshotProfileMatches(snapshot effectevidence.FileSnapshot, profile runtimeaction.FilesystemProfile) bool {
	if profile == runtimeaction.FilesystemPOSIXV1 {
		return snapshot.SchemaVersion == "" && snapshot.FilesystemProfile == ""
	}
	return profile == runtimeaction.FilesystemWindowsLocalDriveV1 && snapshot.SchemaVersion == "file-snapshot/v2" && snapshot.FilesystemProfile == string(profile)
}

func recheckObservedFile(profile runtimeaction.FilesystemProfile, path string, maxBytes int64, before effectevidence.FileSnapshot) error {
	if !snapshotProfileMatches(before, profile) {
		return effectevidence.ErrCorrelation
	}
	if profile == runtimeaction.FilesystemPOSIXV1 {
		return nil
	}
	ref, err := fileResourceForProfile(profile, path)
	if err != nil || ref != before.ResourceRef {
		return effectevidence.ErrCorrelation
	}
	current, err := effectevidence.CaptureFileForProfile(profile, path, maxBytes)
	if err != nil || current.ResourceRef != before.ResourceRef || current.ParentIdentityDigest != before.ParentIdentityDigest {
		return effectevidence.ErrCorrelation
	}
	return nil
}

func pendingFileAuthorityMatches(p effectevidence.PendingFile, a effectevidence.Action, profile runtimeaction.FilesystemProfile) bool {
	if !snapshotProfileMatches(p.Before, profile) {
		return false
	}
	if profile == runtimeaction.FilesystemPOSIXV1 {
		return p.SchemaVersion == "file-observation-pending/v1" && p.IntentID == "" && p.IntentDigest == ""
	}
	return p.SchemaVersion == "file-observation-pending/v2" && p.IntentID == a.IntentID && p.IntentDigest == a.IntentDigest
}

type fileObservationRecoveryRequest struct {
	SchemaVersion string `json:"schema_version,omitempty"`
	Path          string `json:"path,omitempty"`
	ID            string `json:"observation_id"`
	ObserverID    string `json:"observer_id"`
	ExpectedOwner string `json:"expected_owner"`
}

func (r *fileObservationRecoveryRequest) UnmarshalJSON(raw []byte) error {
	type wire fileObservationRecoveryRequest
	var value wire
	if json.Unmarshal(raw, &value) != nil {
		return effectevidence.ErrInvalid
	}
	fields := []string{"observation_id", "observer_id", "expected_owner"}
	if value.SchemaVersion == "file-observation-recovery-request/v2" {
		fields = append(fields, "schema_version", "path")
		if value.Path == "" || len(value.Path) > 4096 {
			return effectevidence.ErrInvalid
		}
	} else if value.SchemaVersion != "" {
		return effectevidence.ErrInvalid
	}
	if !exactJSONObject(raw, fields...) {
		return effectevidence.ErrInvalid
	}
	*r = fileObservationRecoveryRequest(value)
	return nil
}

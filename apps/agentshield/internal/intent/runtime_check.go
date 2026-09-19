package intent

import (
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

const RuntimeCheckSchema = "intent/v5"
const RuntimeCheckPurpose = "Read SIQ generated runtime check files"

var runtimeCheckIntentID = regexp.MustCompile(`^rci-[a-f0-9]{32}$`)
var runtimeCheckRevision = regexp.MustCompile(`^[a-f0-9]{64}$`)

// This is a closed check envelope, not a second general authority issuer.
// Only the active Manager can authenticate its rca session at the HTTP edge.
func (c Contract) validateRuntimeCheck() error {
	if c.SchemaVersion != RuntimeCheckSchema {
		return nil
	}
	suffix := strings.TrimPrefix(c.IntentID, "rci-")
	if !runtimeCheckIntentID.MatchString(c.IntentID) || c.TaskID != "rct-"+suffix || c.Agent.ID != "rca-"+suffix || c.Agent.Platform != "hermes" || c.Purpose != RuntimeCheckPurpose || c.Authority.Issuer != "local-runtime-check" || !runtimeCheckRevision.MatchString(c.Authority.Revision) || len(c.Authority.EvidenceIDs) != 0 || len(c.ProvenanceRefs) != 0 || len(c.ParameterConstraints) != 0 || len(c.AllowedTools) != 1 || c.AllowedTools[0] != "read_file" || len(c.AllowedEffects) != 1 || c.AllowedEffects[0] != "file.read" || len(c.ResourceConstraints) != 1 {
		return violation("intent_invalid_runtime_check")
	}
	r := c.ResourceConstraints[0]
	path, ok := r.Value.(string)
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", path)
	if !ok || err != nil || path != canonical || r.Domain != "filesystem" || r.Operator != "prefix" || !strings.HasSuffix(path, "/runtime-check-materials/rc-"+suffix+"/allowed") {
		return violation("intent_invalid_runtime_check")
	}
	issued, e1 := time.Parse(time.RFC3339Nano, c.IssuedAt)
	from, e2 := time.Parse(time.RFC3339Nano, c.ValidFrom)
	until, e3 := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	if e1 != nil || e2 != nil || e3 != nil || !issued.Equal(from) || !until.After(issued) || until.Sub(issued) > 120*time.Second {
		return violation("intent_invalid_runtime_check")
	}
	return nil
}

func (c Contract) windowsProfileContract() bool {
	return c.SchemaVersion == "intent/v4" || c.SchemaVersion == RuntimeCheckSchema
}

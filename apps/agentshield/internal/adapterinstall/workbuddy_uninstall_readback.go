package adapterinstall

import (
	"encoding/json"

	"siq-agent-security/apps/agentshield/internal/state"
)

// A WorkBuddy settings file can legitimately survive uninstall. Confirm the
// authenticated operation and its actual post-images instead of treating the
// presence of the host's own file as an incomplete product installation.
func workBuddyUninstallReadback(o Options) bool {
	st := &state.Store{Dir: o.StateDir}
	revision, raw, err := st.LatestSeq("adapter-operations", operationKey(o))
	if err != nil || revision < 0 {
		return false
	}
	var claim operationClaim
	if json.Unmarshal(raw, &claim) != nil || claim.Schema != "adapter-operation/v1" || claim.Platform != WorkBuddy || claim.Action != "uninstall" {
		return false
	}
	status, err := endState(o.StateDir, claim)
	if err != nil || status != "committed" {
		return false
	}
	plan, err := unsealPlan(o.StateDir, claim)
	if err != nil || !workBuddyRecoveryMatches(plan, o) || len(plan.payload.Files) == 0 {
		return false
	}
	for _, op := range plan.payload.Files {
		current, err := readImage(o.Home, op.Path, true)
		if err != nil || !sameImage(current, op.After) {
			return false
		}
	}
	return true
}

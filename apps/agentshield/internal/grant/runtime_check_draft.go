package grant

import (
	"errors"
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
)

var ErrRuntimeCheckDraft = errors.New("grant_runtime_check_draft_invalid")
var runtimeCheckID = regexp.MustCompile(`^rc-[a-f0-9]{32}$`)

// BuildRuntimeCheckDraft creates the controller's short-lived baseline before
// its first signature. No existing Skill Grant or admission is rewritten.
func BuildRuntimeCheckDraft(adm admission.Admission, opts Options, checkID string) (*Result, error) {
	if opts.Now.IsZero() {
		opts.Now = time.Now().UTC()
	}
	suffix := strings.TrimPrefix(checkID, "rc-")
	if !runtimeCheckID.MatchString(checkID) || opts.Key == nil || !admission.Verify(opts.Key.Public(), adm) || !instanceDraftContentHash.MatchString(adm.ContentHash) || adm.AdmissionID != "adm-"+adm.ContentHash[:12] || adm.SkillName != checkID || adm.SkillID == "" || adm.Engine.Name != admission.EngineName || adm.Engine.Version != "runtime-check/v1" || (adm.Verdict != "admit" && adm.Verdict != "admit_with_conditions") || opts.Subject != (Subject{Type: "agent_instance", ID: "rca-" + suffix}) || opts.Platform != "hermes" || opts.Scenario != nil || opts.ExpiresAt == nil || !opts.ExpiresAt.After(opts.Now) || opts.ExpiresAt.Sub(opts.Now) > 120*time.Second || (opts.EnforcementMode != "" && opts.EnforcementMode != "block") || len(adm.DeclaredFacts) != 1 {
		return nil, ErrRuntimeCheckDraft
	}
	f := adm.DeclaredFacts[0]
	if f.Domain != "tool" || f.Action != "tool.invoke" || f.Resource.Type != "tool" || f.Resource.Value != "read_file" || f.Effect != "allow" || f.State != "declared" {
		return nil, ErrRuntimeCheckDraft
	}
	opts.instanceGrantID = "grt-rc-" + suffix
	return buildGrant(adm, opts)
}

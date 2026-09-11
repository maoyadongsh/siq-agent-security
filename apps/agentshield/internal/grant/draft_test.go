package grant

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestDraftFromPreservesLimitsWithoutApprovalOrAliasing(t *testing.T) {
	source := build(t, "openclaw", sampleAdmission())
	source.Grant.OverlapConflicts = []Overlap{}
	approved, err := Approve(source.Grant, human(), key(t))
	if err != nil {
		t.Fatal(err)
	}
	approved.Status = "effective"
	approved.EffectiveReadback = &Readback{Backend: "fixture", Revision: "1", EvidenceID: "rb1"}
	approved.Facts[0].State = "effective"
	r, e := "revision", "readback"
	approved.Facts[0].AuthorityRevision = &r
	approved.Facts[0].ReadbackEvidenceID = &e
	approved.Facts[0].Conditions = map[string]any{"require_approval": true, "nested": map[string]any{"retain": true}}
	expires := fixedNow.Add(-time.Hour).Format(time.RFC3339)
	approved.ExpiresAt = &expires
	resign(key(t), &approved)
	before, _ := json.Marshal(approved)
	out, err := DraftFrom(approved, source.DesiredPolicy, "grt-d-"+strings.Repeat("a", 64), fixedNow, key(t))
	if err != nil {
		t.Fatal(err)
	}
	g := out.Grant
	if g.Status != "pending_approval" || g.ApprovedBy != nil || g.EffectiveReadback != nil || !Verify(key(t).Public(), g) {
		t.Fatal("draft inherited authority", g)
	}
	if g.AdmissionID != approved.AdmissionID || g.Subject != approved.Subject || g.Platform != approved.Platform || *g.ExpiresAt != expires || !reflect.DeepEqual(g.OpenClawToolPolicy, approved.OpenClawToolPolicy) {
		t.Fatal("scope changed")
	}
	if g.Facts[0].State != "declared" || g.Facts[0].AuthorityRevision != nil || g.Facts[0].ReadbackEvidenceID != nil {
		t.Fatal("effective fact retained")
	}
	if g.DesiredPolicyRef.PolicyID == approved.DesiredPolicyRef.PolicyID || g.DesiredPolicyRef.Version != 1 || out.DesiredPolicy["policy_id"] != g.DesiredPolicyRef.PolicyID {
		t.Fatal("policy namespace reused")
	}
	g.Facts[0].Conditions["nested"].(map[string]any)["retain"] = false
	g.OpenClawToolPolicy.Deny = append(g.OpenClawToolPolicy.Deny, "changed")
	out.DesiredPolicy["selector"].(map[string]any)["agent_ids"].([]any)[0] = "changed"
	after, _ := json.Marshal(approved)
	if string(before) != string(after) {
		t.Fatal("draft mutated source")
	}
	if source.DesiredPolicy["selector"].(map[string]any)["agent_ids"].([]any)[0] != approved.Subject.ID {
		t.Fatal("policy alias")
	}
	if _, err := Approve(out.Grant, human(), key(t)); err != ErrExpired {
		t.Fatal("expired draft approved", err)
	}
}
func TestDraftFromRejectsInvalidSource(t *testing.T) {
	for _, kind := range []string{"pending", "signature", "policy", "id", "expiry", "default"} {
		t.Run(kind, func(t *testing.T) {
			source := build(t, "hermes", sampleAdmission())
			source.Grant.Status = "deployed"
			resign(key(t), &source.Grant)
			id := "grt-d-" + strings.Repeat("a", 64)
			switch kind {
			case "pending":
				source.Grant.Status = "pending_approval"
				resign(key(t), &source.Grant)
			case "signature":
				source.Grant.Platform = "other"
			case "policy":
				source.DesiredPolicy["version"] = 999
			case "id":
				id = source.Grant.GrantID
			case "expiry":
				invalid := "invalid"
				source.Grant.ExpiresAt = &invalid
				resign(key(t), &source.Grant)
			case "default":
				source.Grant.DefaultEffect = "allow"
				resign(key(t), &source.Grant)
			}
			if _, err := DraftFrom(source.Grant, source.DesiredPolicy, id, fixedNow, key(t)); err != ErrDraftSource {
				t.Fatal("invalid source accepted", err)
			}
		})
	}
}

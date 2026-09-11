package grant

import (
	"encoding/json"
	"testing"
)

func TestPermissionDigestPreservesReadbackButDetectsExecutionChanges(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	baseline, err := PermissionDigest(g)
	if err != nil {
		t.Fatal(err)
	}
	clone := func() Grant { raw, _ := json.Marshal(g); var out Grant; _ = json.Unmarshal(raw, &out); return out }
	readback := clone()
	readback.Status = "effective"
	readback.Signature = "readback changes full signature"
	readback.EffectiveReadback = &Readback{Backend: "fixture", Revision: "r2", EvidenceID: "ev-readback"}
	for i := range readback.Facts {
		if readback.Facts[i].State == "declared" {
			readback.Facts[i].State = "effective"
		}
		readback.Facts[i].Authority = "fixture"
		rev, ev := "r2", "ev-readback"
		readback.Facts[i].AuthorityRevision, readback.Facts[i].ReadbackEvidenceID = &rev, &ev
	}
	if digest, err := PermissionDigest(readback); err != nil || digest != baseline {
		t.Fatal("readback changed execution limits", err)
	}
	for name, mutate := range map[string]func(*Grant){
		"subject": func(g *Grant) { g.Subject.ID = "other" }, "platform": func(g *Grant) { g.Platform = "openclaw" },
		"admission": func(g *Grant) { g.AdmissionID = "new-version" }, "scope": func(g *Grant) { g.Facts[0].Resource.Value = "other" },
		"effect": func(g *Grant) { g.Facts[0].Effect = "deny" }, "condition": func(g *Grant) { g.Facts[0].Conditions = map[string]any{"require_approval": true} },
		"tool eligibility": func(g *Grant) { g.Facts[0].State = "inferred" }, "policy version": func(g *Grant) { g.DesiredPolicyRef.Version++ },
		"deadline":      func(g *Grant) { end := "2099-01-01T00:00:00Z"; g.ExpiresAt = &end },
		"platform deny": func(g *Grant) { g.OpenClawToolPolicy = &OpenClawToolPolicy{Deny: []string{"read_file"}} },
	} {
		t.Run(name, func(t *testing.T) {
			out := clone()
			mutate(&out)
			digest, err := PermissionDigest(out)
			if err != nil || digest == baseline {
				t.Fatal("changed limit retained digest", err)
			}
		})
	}
	g.Facts[0].Conditions = map[string]any{"number": json.Number("9007199254740992")}
	a, _ := PermissionDigest(g)
	g.Facts[0].Conditions["number"] = json.Number("9007199254740993")
	b, _ := PermissionDigest(g)
	if a == b {
		t.Fatal("permission digest lost integer precision")
	}
}

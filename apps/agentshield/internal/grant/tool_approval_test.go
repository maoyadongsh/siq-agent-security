package grant

import "testing"

func TestApprovalConditionOnlyTightensAndSurvivesPatch(t *testing.T) {
	original := build(t, "hermes", sampleAdmission()).Grant
	guarded, err := RequireToolApproval(original, []string{"read_file"}, key(t))
	if err != nil || !Verify(key(t).Public(), guarded) {
		t.Fatal(guarded, err)
	}
	for _, f := range original.Facts {
		if f.Conditions["require_approval"] == true {
			t.Fatal("mutated original")
		}
	}
	patched, _, err := PatchDesired(guarded, DesiredPatch{HasTools: true, Tools: []string{"read_file", "write_file"}}, key(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, g := range []Grant{guarded, patched} {
		found := false
		for _, f := range g.Facts {
			if f.Resource.Value == "read_file" && f.Domain == "tool" {
				found = f.Conditions["require_approval"] == true
			}
		}
		if !found {
			t.Fatal("approval floor lost")
		}
	}
	for _, tools := range [][]string{nil, {"not_granted"}, {"read_file", "read_file"}} {
		if _, err := RequireToolApproval(original, tools, key(t)); err == nil {
			t.Fatal("invalid approval accepted")
		}
	}
	guarded.Status = "deployed"
	if _, err := RequireToolApproval(guarded, []string{"read_file"}, key(t)); err == nil {
		t.Fatal("deployed grant rewritten")
	}
}

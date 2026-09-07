package receipt

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestPatchedGrantCannotExecuteWithoutPerUseApproval(t *testing.T) {
	// The fixture includes an explicit exec allow and a credential deny that
	// independently requires approval. Model routing edits must not drop it.
	pending := *deployedGrant(t, "openclaw", false)
	pending.Status = "pending_approval"
	patched, _, err := grant.PatchDesired(pending, grant.DesiredPatch{
		HasModels: true, Models: []string{"fixture-model"},
	}, key(t))
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(patched, grant.Approval{ActorType: "human", ActorID: "fixture-admin", ApprovedAt: "2026-09-04T06:00:00Z"}, key(t))
	if err != nil {
		t.Fatal(err)
	}
	deployed, err := grant.MarkDeployed(approved, key(t))
	if err != nil {
		t.Fatal(err)
	}
	fx := newFixture(t, "block", &deployed, false)
	request := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	decision, err := fx.eng.Decide(request)
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != ActionHold {
		t.Fatalf("model-only patch bypassed per-use approval: %s", decision.Action)
	}
	request = correlatedRequest(request, decision)
	_, err = fx.eng.Observe(request, "fixture")
	assertCorrelation(t, err, "observation_action_not_authorized")
	if _, err := fx.eng.ResolveHold(decision.Receipt, true, "fixture-admin"); err != nil {
		t.Fatal(err)
	}
	if _, err := fx.eng.Observe(request, "fixture"); err != nil {
		t.Fatal(err)
	}
}

package openshell

// Auxiliary control-plane driver, not candidate-binary B3 or session/enforcement
// acceptance. Opt in only for a disposable target owned by this run. Ordinary CI
// skips it. SIQ_O05_CONFIRM_TARGET must repeat that exact target.
import (
	"errors"
	"os"
	"testing"
	"time"
)

func liveRollbackAuthorizer(target string, rec DeploymentReceipt, base Snapshot) RollbackAuthorizer {
	return func(a RollbackAuthorization) error {
		if a.OperationID != rec.OperationID || a.Target != target || a.Restore.PolicyDigest != base.PolicyDigest {
			return errors.New("live rollback authorization binding mismatch")
		}
		return nil
	}
}

func TestO05LiveRollbackRestore(t *testing.T) {
	if os.Getenv("SIQ_O05_LIVE") != "1" {
		t.Skip("explicit live opt-in required")
	}
	target := os.Getenv("SIQ_O05_TARGET")
	if target == "" || os.Getenv("SIQ_O05_CONFIRM_TARGET") != target {
		t.Fatal("confirm exact disposable target ownership first")
	}
	c := New(Options{ProbeTimeout: 5 * time.Second, PollInterval: time.Second, PollAttempts: 15})
	base, err := c.ReadEffective(target)
	if err != nil {
		t.Fatalf("base readback: %v", err)
	}
	// Choose a rule distinct from the base before the first write.
	rules := []NetworkRule{{Endpoint: "127.0.0.1:8097", Effect: "allow", BinaryPaths: []string{"/usr/local/bin/python3"}}}
	projected, _ := networkRulesToGateway(rules)
	proposed := clonePolicy(base.Policy)
	proposed["network_policies"] = projected
	digest, err := policyDigest(proposed)
	if err != nil {
		t.Fatal(err)
	}
	if digest == base.PolicyDigest {
		rules[0].Endpoint = "127.0.0.1:8096"
	}
	rec, err := c.ApplyNetwork(target, rules, base.Revision)
	if err != nil {
		t.Fatalf("apply: %v; inspect owned target before cleanup", err)
	}
	authorize := liveRollbackAuthorizer(target, rec, base)
	restored := false
	t.Cleanup(func() {
		if restored {
			return
		}
		// Exact receipt + fresh authorization + drift checks; never force restoration
		// over an unrelated writer. Any failure is visible and requires inspection.
		if _, err := c.RollbackAuthorized(target, rec, authorize); err != nil {
			t.Errorf("owned target cleanup refused: %v", err)
		}
	})
	if rec.Result != "applied" || rec.BasePolicyDigest == rec.AppliedPolicyDigest {
		t.Fatal("changed apply required; no-op is not coverage")
	}
	if _, err := c.RollbackAuthorized(target, rec, nil); err == nil {
		t.Fatal("nil authorizer rollback succeeded")
	}
	unchanged, err := c.ReadEffective(target)
	if err != nil {
		t.Fatal(err)
	}
	if unchanged.Revision != rec.BackendRevision || unchanged.PolicyDigest != rec.AppliedPolicyDigest {
		t.Fatal("state changed after refused rollback")
	}
	rb, err := c.RollbackAuthorized(target, rec, authorize)
	if err != nil {
		t.Fatal(err)
	}
	restored = true // consumed receipt must not be replayed, even if final read fails
	final, err := c.ReadEffective(target)
	if err != nil {
		t.Fatal(err)
	}
	if rb.Result != "restored" || final.PolicyDigest != base.PolicyDigest || final.Revision != rb.RestoredRevision {
		t.Fatalf("exact restore not proven: result=%s", rb.Result)
	}
	t.Log("SIQ_AUX_CONTROL_PLANE_RESTORE_VERIFIED")
}

func TestLiveRollbackAuthorizerRejectsMismatch(t *testing.T) {
	base := Snapshot{PolicyDigest: "base"}
	rec := DeploymentReceipt{OperationID: "op"}
	authorize := liveRollbackAuthorizer("owned", rec, base)
	good := RollbackAuthorization{OperationID: "op", Target: "owned", Restore: base}
	if err := authorize(good); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []RollbackAuthorization{
		{OperationID: "other", Target: "owned", Restore: base},
		{OperationID: "op", Target: "other", Restore: base},
		{OperationID: "op", Target: "owned", Restore: Snapshot{PolicyDigest: "changed"}},
	} {
		if authorize(bad) == nil {
			t.Fatal("mismatch authorized")
		}
	}
}

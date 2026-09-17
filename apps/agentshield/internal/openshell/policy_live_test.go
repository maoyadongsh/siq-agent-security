package openshell

import (
	"errors"
	"os"
	"testing"
	"time"
)

// TestOpenShellLivePolicyFidelityAndRollback is an opt-in destructive live test
// for an explicitly dedicated sandbox. It never creates or deletes a sandbox.
// The exact pre-test policy is restored on both the success path and best-effort
// cleanup after a failed assertion.
func TestOpenShellLivePolicyFidelityAndRollback(t *testing.T) {
	if os.Getenv("SIQ_AS_OPENSHELL_LIVE") != "1" {
		t.Skip("set SIQ_AS_OPENSHELL_LIVE=1 for the explicit live policy test")
	}
	target := os.Getenv("SIQ_AS_OPENSHELL_LIVE_TARGET")
	envScript := os.Getenv("SIQ_AS_OPENSHELL_ENV_SH")
	if target == "" || envScript == "" {
		t.Fatal("SIQ_AS_OPENSHELL_LIVE_TARGET and SIQ_AS_OPENSHELL_ENV_SH are required")
	}
	client := New(Options{
		EnvScript:         envScript,
		Timeout:           30 * time.Second,
		PollInterval:      100 * time.Millisecond,
		PollAttempts:      20,
		MaxOutput:         2 << 20,
		policyCoordinator: newPolicyCoordinator(),
	})
	if _, err := client.Probe(); err != nil {
		t.Fatalf("live OpenShell probe failed: %v", err)
	}
	base, err := client.ReadEffective(target)
	if err != nil {
		t.Fatalf("read live base policy: %v", err)
	}
	restored := false
	t.Cleanup(func() {
		if restored {
			return
		}
		current, readErr := client.ReadEffective(target)
		if readErr != nil || current.PolicyDigest == base.PolicyDigest {
			return
		}
		_ = withPolicyFile(base.Policy, func(path string) error {
			_, setErr := client.cli("policy", "set", target, "--policy", path)
			return setErr
		})
	})

	// Unsupported restrictions and malformed revisions are zero-write rejects.
	for _, attempt := range []struct {
		rules    []NetworkRule
		revision string
	}{
		{rules: []NetworkRule{{Endpoint: "o01-o02.invalid:443", Effect: "deny", BinaryPaths: []string{"/usr/bin/curl"}}}, revision: base.Revision},
		{rules: []NetworkRule{{Endpoint: "o01-o02.invalid:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, revision: ""},
		{rules: []NetworkRule{{Endpoint: "o01-o02.invalid:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, revision: "01"},
	} {
		if _, applyErr := client.ApplyNetwork(target, attempt.rules, attempt.revision); applyErr == nil {
			t.Fatal("unsafe live policy input unexpectedly succeeded")
		}
		after, readErr := client.ReadEffective(target)
		if readErr != nil || after.Revision != base.Revision || after.PolicyDigest != base.PolicyDigest {
			t.Fatalf("unsafe input was not zero-write: revision=%q digest_match=%v err=%v", after.Revision, after.PolicyDigest == base.PolicyDigest, readErr)
		}
	}

	// A no-op is recorded but performs no gateway write; rollback is also no-op.
	noOp, err := client.ApplyNetwork(target, base.Network, base.Revision)
	if err != nil || noOp.Result != "no_op" || noOp.BackendRevision != base.Revision {
		t.Fatalf("live no-op apply failed: receipt=%+v err=%v", noOp, err)
	}
	noOpRollback, err := client.Rollback(target, noOp)
	if err != nil || noOpRollback.Result != "no_op" || noOpRollback.RestoredRevision != base.Revision {
		t.Fatalf("live no-op rollback failed: receipt=%+v err=%v", noOpRollback, err)
	}

	changedRules := []NetworkRule{{
		Endpoint: "o01-o02.invalid:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}, RuleName: "siq-o01-o02-live",
	}}
	applied, err := client.ApplyNetwork(target, changedRules, base.Revision)
	if err != nil || applied.Result != "applied" {
		t.Fatalf("live policy apply failed: receipt=%+v err=%v", applied, err)
	}
	changed, err := client.ReadEffective(target)
	if err != nil {
		t.Fatalf("read changed policy: %v", err)
	}
	if changed.StaticDigest != base.StaticDigest || changed.PolicyDigest != applied.AppliedPolicyDigest {
		t.Fatalf("full static policy fidelity failed: static_match=%v full_match=%v", changed.StaticDigest == base.StaticDigest, changed.PolicyDigest == applied.AppliedPolicyDigest)
	}

	forged := applied
	forged.AppliedPolicyDigest = base.PolicyDigest
	if _, rollbackErr := client.RollbackAuthorized(target, forged, func(RollbackAuthorization) error { return nil }); rollbackErr == nil {
		t.Fatal("forged receipt unexpectedly authorized rollback")
	}
	if _, rollbackErr := client.RollbackAuthorized(target, applied, func(RollbackAuthorization) error { return errors.New("revoked") }); rollbackErr == nil {
		t.Fatal("revoked current authority unexpectedly authorized rollback")
	}
	stillChanged, err := client.ReadEffective(target)
	if err != nil || stillChanged.Revision != changed.Revision || stillChanged.PolicyDigest != changed.PolicyDigest {
		t.Fatalf("rejected rollback changed live state: err=%v", err)
	}

	unknownClient := New(Options{
		EnvScript: envScript, Timeout: 30 * time.Second,
		PollInterval: 100 * time.Millisecond, PollAttempts: 20,
		policyCoordinator: newPolicyCoordinator(),
	})
	if _, rollbackErr := unknownClient.RollbackAuthorized(target, applied, func(RollbackAuthorization) error { return nil }); rollbackErr == nil {
		t.Fatal("restart-equivalent unknown operation unexpectedly authorized rollback")
	}

	rolledBack, err := client.RollbackAuthorized(target, applied, func(auth RollbackAuthorization) error {
		if auth.OperationID != applied.OperationID || auth.Target != target || auth.Restore.PolicyDigest != base.PolicyDigest {
			return errors.New("authorization binding mismatch")
		}
		return nil
	})
	if err != nil || rolledBack.Result != "restored" {
		t.Fatalf("live authorized rollback failed: receipt=%+v err=%v", rolledBack, err)
	}
	final, err := client.ReadEffective(target)
	if err != nil || final.PolicyDigest != base.PolicyDigest || final.StaticDigest != base.StaticDigest {
		t.Fatalf("live rollback did not restore exact base policy: err=%v", err)
	}
	if final.Revision == base.Revision || rolledBack.RestoredRevision != final.Revision {
		t.Fatalf("rollback must restore content at a new real revision: base=%s final=%s receipt=%s", base.Revision, final.Revision, rolledBack.RestoredRevision)
	}
	restored = true
	t.Logf("live O01/O02 pass target=%s base_revision=%s applied_revision=%s restored_revision=%s base_digest=%s", target, base.Revision, applied.BackendRevision, final.Revision, base.PolicyDigest)
}

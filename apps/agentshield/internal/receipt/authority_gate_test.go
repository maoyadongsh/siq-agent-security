package receipt

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestMandatoryAuthorityCannotBecomeAdvisoryAllow(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, code := range []string{"intent_binding_missing", "intent_not_found", "intent_digest_mismatch", "intent_signature_invalid", "intent_expired", "intent_agent_mismatch", "intent_principal_mismatch", "intent_task_mismatch", "intent_binding_revoked", "intent_binding_revocation_invalid", "intent_downgrade_attempt", "trusted_context_invalid", "trusted_context_expired", "trusted_context_scope_mismatch", "provenance_authority_invalid"} {
			t.Run(mode+"/"+code, func(t *testing.T) {
				fx := newFixture(t, mode, deployedGrant(t, "hermes", false), false)
				fx.eng.opts.IntentEnforcement = "required"
				if code != "intent_binding_missing" {
					fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) {
						return nil, &intent.Violation{Code: code}
					}
				}
				d, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/work/report"}))
				if err != nil || d.Action != ActionDeny || d.Receipt.AdvisoryAction != nil || d.Receipt.ReasonCode != code {
					t.Fatalf("mandatory authority became execution permission: decision=%+v err=%v", d, err)
				}
				if d.Receipt.AuthorityStatus != "invalid" || d.Receipt.AuthorityReasonCode != code || d.Receipt.EffectiveAction != ActionDeny || d.Receipt.PolicyAction != "" || d.Receipt.MatchedGrantID != nil {
					t.Fatal("invalid authority reached policy evaluation or lost signed metadata")
				}
			})
		}
	}
}

func TestOptionalNeverBoundKeepsPolicyModes(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		fx := newFixture(t, mode, deployedGrant(t, "hermes", false), false)
		allowed, err := fx.eng.Decide(req("hermes", "read_file", nil))
		if err != nil || allowed.Action != ActionAllow || allowed.Receipt.AuthorityStatus != "unbound_legacy" || allowed.Receipt.PolicyAction != ActionAllow {
			t.Fatal("optional legacy authorization changed", mode, err)
		}
		denied, err := fx.eng.Decide(req("hermes", "ungranted", nil))
		if err != nil || denied.Receipt.PolicyAction != ActionDeny || denied.Receipt.AuthorityStatus != "unbound_legacy" {
			t.Fatal("legacy policy result missing", mode, err)
		}
		if mode == "block" && denied.Action != ActionDeny || mode != "block" && (denied.Action != ActionAllow || str(denied.Receipt.AdvisoryAction) != ActionDeny) {
			t.Fatal("ordinary policy lost advisory behavior", mode)
		}
	}
}

func TestValidAuthorityConstraintRetainsAdvisoryPolicy(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		fx, _, _ := revocableEngine(t, "required", mode)
		d, err := fx.eng.Decide(req("hermes", "write_file", nil))
		if err != nil || d.Receipt.AuthorityStatus != "valid" || d.Receipt.PolicyAction != ActionDeny || d.Receipt.AuthorityReasonCode != "" || d.Receipt.ReasonCode != "intent_tool_not_allowed" {
			t.Fatal("valid authority constraint was treated as invalid identity", mode, err)
		}
		if mode == "block" && d.Action != ActionDeny || mode != "block" && d.Action != ActionAllow {
			t.Fatal("valid authority policy mode changed", mode)
		}
	}
}

func TestUnknownAuthorityErrorFailsClosed(t *testing.T) {
	fx := newFixture(t, "warn", deployedGrant(t, "hermes", false), false)
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return nil, errors.New("private resolver detail") }
	d, err := fx.eng.Decide(req("hermes", "read_file", nil))
	if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_authority_invalid" || d.Reason != "intent_authority_invalid" {
		t.Fatal("unknown authority error allowed or leaked details", err)
	}
}

func TestAuthorityReceiptSamplesAndHistoricalVerification(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/receipt.pre-authority-gate.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var historical Receipt
	if err = json.Unmarshal(raw, &historical); err != nil {
		t.Fatal(err)
	}
	if err = Verify([]Receipt{historical}, key(t).Public()); err != nil {
		t.Fatal(err)
	}
	fx := newFixture(t, "audit_only", nil, false)
	fx.eng.opts.IntentEnforcement = "required"
	d, err := fx.eng.Decide(req("hermes", "read_file", nil))
	if err != nil {
		t.Fatal(err)
	}
	if err = Verify([]Receipt{d.Receipt}, fx.k.Public()); err != nil {
		t.Fatal(err)
	}
	for _, edit := range []func(*Receipt){func(r *Receipt) { r.AuthorityStatus = "valid" }, func(r *Receipt) { r.EffectiveAction = ActionAllow }, func(r *Receipt) { r.PolicyAction = ActionAllow }, func(r *Receipt) { r.AuthorityReasonCode = "other" }} {
		bad := d.Receipt
		edit(&bad)
		if Verify([]Receipt{bad}, fx.k.Public()) == nil {
			t.Fatal("new authorization fields not signed")
		}
	}
	got, _ := json.MarshalIndent(d.Receipt, "", "  ")
	path := filepath.Join("../../testdata/contracts", "receipt.authority-invalid.sample.json")
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err = os.WriteFile(path, append(got, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(bytes.TrimSpace(want), got) {
		t.Fatal("authority receipt sample differs", err)
	}
}

func TestCallerCWDDoesNotGrantWorkspaceWrite(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	r := req("hermes", "exec", map[string]any{"command": "echo fixture > /secret/report.txt"})
	r.Context = map[string]any{"cwd": "/secret"}
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionDeny {
		t.Fatalf("caller cwd authorized a filesystem write: %+v %v", d, err)
	}
	_, err = fx.eng.Observe(correlatedRequest(r, d), "fake success")
	assertCorrelation(t, err, "observation_action_not_authorized")
}

func TestParameterBudgetHardDeniesEveryMode(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			fx := newFixture(t, mode, deployedGrant(t, "hermes", false), false)
			params := map[string]any{"path": "/home/u/proj/a.txt", "items": make([]any, 8192)}
			d, err := fx.eng.Decide(req("hermes", "read_file", params))
			if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "runtime_parameter_budget_exceeded" || d.Receipt.AdvisoryAction != nil || d.Receipt.AuthorityStatus != "invalid" {
				t.Fatalf("budget became allow: %+v %v", d, err)
			}
		})
	}
}

func TestSignedBoundSessionCannotDowngradeAcrossModesAndRestart(t *testing.T) {
	for _, enforcement := range []string{"required", "optional"} {
		for _, mode := range []string{"block", "warn", "audit_only"} {
			t.Run(enforcement+"/"+mode, func(t *testing.T) {
				fx, _, binding := revocableEngine(t, enforcement, mode)
				request := req("hermes", "read_file", map[string]any{"path": "/work/report"})
				initial, err := fx.eng.Decide(request)
				if err != nil || initial.Action != ActionAllow || initial.Receipt.IntentDigest != binding.IntentDigest {
					t.Fatal("signed binding not established", err)
				}
				fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return nil, nil }
				for _, restart := range []bool{false, true} {
					if restart {
						fx.eng, err = New(fx.eng.opts)
						if err != nil {
							t.Fatal(err)
						}
					}
					d, err := fx.eng.Decide(request)
					if err != nil || d == nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_downgrade_attempt" || d.Receipt.AdvisoryAction != nil || d.Receipt.IntentDigest != binding.IntentDigest || d.Receipt.IntentBinding != "bound" {
						t.Fatalf("bound authority downgraded restart=%v: %+v %v", restart, d, err)
					}
				}
			})
		}
	}
}

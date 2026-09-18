package receipt

import (
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
)

// Use the actual versioned preparation and approval path, with no filesystem
// scopes, so profile mismatch is tested independently of local file availability.
func windowsIntersectionBaseline(t *testing.T) *grant.Grant {
	t.Helper()
	k := key(t)
	built, err := grant.Build(admission.Admission{
		AdmissionID: "adm-windows-baseline", ContentHash: strings.Repeat("a", 64),
		Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-baseline"},
		DeclaredFacts: []admission.DeclaredFact{{
			Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: verifiedCall},
			Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "test", EvidenceIDs: []string{"ev-baseline"},
		}},
	}, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "inst_1"}, Platform: "hermes", Key: k})
	if err != nil {
		t.Fatal(err)
	}
	g, _, err := grant.PrepareWindowsResources(built.Grant, grant.ResourceEdit{
		Tools: []string{verifiedCall}, Network: []grant.NetworkPatch{}, Models: []string{},
		Filesystem: grant.FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{}},
	}, true, k)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.Approve(g, grant.Approval{ActorType: "human", ActorID: "test-owner", ApprovedAt: "2026-09-18T00:00:00Z"}, k)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, k)
	if err != nil || !grant.Verify(k.Public(), g) || g.Skill != nil {
		t.Fatalf("invalid Windows baseline fixture: %v", err)
	}
	return &g
}

func assertIntersectionReceiptPersisted(t *testing.T, fx *fixture, decision *Decision) {
	t.Helper()
	stored, err := fx.chain.Read()
	if err != nil || len(stored) != 1 {
		t.Fatalf("decision receipt was not persisted: count=%d err=%v", len(stored), err)
	}
	if err := Verify(stored, fx.k.Public()); err != nil {
		t.Fatalf("receipt signature/chain: %v", err)
	}
	r := stored[0]
	if r.Action != decision.Action || r.EffectiveAction != decision.Action ||
		r.AuthorityStatus != decision.Receipt.AuthorityStatus || r.AuthorityReasonCode != decision.Receipt.AuthorityReasonCode ||
		r.ReasonCode != decision.Receipt.ReasonCode || r.Hash != decision.Receipt.Hash {
		t.Fatal("persisted receipt does not preserve the decision and authority classification")
	}
}

func TestSECIntersectionAuthorityHardDeny(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, secPolicyDeny := range []bool{false, true} {
			name := "sec_allows"
			if secPolicyDeny {
				name = "sec_policy_denies"
			}
			t.Run(mode+"/"+name, func(t *testing.T) {
				secGrant := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
				baseline := windowsIntersectionBaseline(t)
				fx := newFixture(t, mode, nil, false)
				fx.eng.opts.SkillContexts = secLookup(validSEC(secGrant, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
				fx.eng.opts.BaselineGrants = func(_, _ string) *grant.Grant { return baseline }
				r := req("hermes", verifiedCall, readCallPath())
				if secPolicyDeny {
					r = req("hermes", "exec", map[string]any{"command": "echo test"})
				}
				d, err := fx.eng.Decide(r)
				if err != nil {
					t.Fatal(err)
				}
				if d.Action != ActionDeny || d.Receipt.EffectiveAction != ActionDeny || d.Receipt.AdvisoryAction != nil ||
					d.Receipt.AuthorityStatus != "invalid" || d.Receipt.AuthorityReasonCode != "intent_grant_profile_mismatch" ||
					d.Receipt.ReasonCode != "intent_grant_profile_mismatch" {
					t.Fatalf("baseline authority was relaxed: action=%s advisory=%v authority=%s code=%s reason=%s", d.Action, d.Receipt.AdvisoryAction, d.Receipt.AuthorityStatus, d.Receipt.AuthorityReasonCode, d.Reason)
				}
				if d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.Status != SkillAttributionVerified || d.Receipt.SkillAttribution.CallBinding == "" {
					t.Fatal("the trusted SEC and exact call must remain attributed on the denial")
				}
				assertIntersectionReceiptPersisted(t, fx, d)
			})
		}
	}
}

func TestSECIntersectionOrdinaryPolicyModes(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, scope := range []string{"both_allow", "baseline_denies", "sec_denies"} {
			t.Run(mode+"/"+scope, func(t *testing.T) {
				secGrant := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
				baseline := baselineGrant(t, "hermes", verifiedCall, "exec")
				r := req("hermes", verifiedCall, readCallPath())
				if scope == "baseline_denies" {
					baseline = baselineGrant(t, "hermes", "web_fetch")
				} else if scope == "sec_denies" {
					r = req("hermes", "exec", map[string]any{"command": "echo test"})
				}
				fx := newFixture(t, mode, nil, false)
				fx.eng.opts.SkillContexts = secLookup(validSEC(secGrant, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
				fx.eng.opts.BaselineGrants = func(_, _ string) *grant.Grant { return baseline }
				d, err := fx.eng.Decide(r)
				if err != nil {
					t.Fatal(err)
				}
				wantAction, wantPolicy := ActionAllow, ActionAllow
				wantAdvisory := scope != "both_allow" && mode != "block"
				if scope != "both_allow" {
					wantPolicy = ActionDeny
					if mode == "block" {
						wantAction = ActionDeny
					}
				}
				if d.Action != wantAction || d.Receipt.PolicyAction != wantPolicy || d.Receipt.AuthorityStatus != "unbound_legacy" || d.Receipt.AuthorityReasonCode != "" {
					t.Fatalf("ordinary policy behavior changed: action=%s policy=%s authority=%s code=%s", d.Action, d.Receipt.PolicyAction, d.Receipt.AuthorityStatus, d.Receipt.AuthorityReasonCode)
				}
				if (d.Receipt.AdvisoryAction != nil) != wantAdvisory || wantAdvisory && *d.Receipt.AdvisoryAction != ActionDeny {
					t.Fatalf("incorrect advisory: %v", d.Receipt.AdvisoryAction)
				}
				assertIntersectionReceiptPersisted(t, fx, d)
			})
		}
	}
}

func TestRedactionRecheckAuthorityHardDeny(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			legacy := deployedGrant(t, "hermes", true)
			replacement := windowsIntersectionBaseline(t)
			fx := newFixture(t, mode, nil, false)
			lookups := 0
			fx.eng.opts.Grants = func(_, _ string) *grant.Grant {
				lookups++
				// The initial evaluation and permission to attempt redaction
				// see the old grant; final parameter evaluation sees a changed
				// profile. That failure must not fall back to advisory allow.
				if lookups <= 2 {
					return legacy
				}
				return replacement
			}
			d, err := fx.eng.Decide(req("hermes", "web_fetch", map[string]any{
				"url": "https://api.github.com/report", "auth": "sk-" + strings.Repeat("A", 30),
			}))
			if err != nil {
				t.Fatal(err)
			}
			if lookups < 3 || d.Action != ActionDeny || d.Params != nil || d.Receipt.AdvisoryAction != nil ||
				d.Receipt.AuthorityStatus != "invalid" || d.Receipt.AuthorityReasonCode != "intent_grant_profile_mismatch" {
				t.Fatalf("redaction lost current authority: lookups=%d action=%s authority=%s code=%s", lookups, d.Action, d.Receipt.AuthorityStatus, d.Receipt.AuthorityReasonCode)
			}
			assertIntersectionReceiptPersisted(t, fx, d)
		})
	}
}

package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

func nativeRefForTest(t *testing.T, g *grant.Grant) NativeAuthorityRef {
	t.Helper()
	raw, err := json.Marshal(g)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if json.Unmarshal(raw, &m) != nil {
		t.Fatal("grant serialization")
	}
	b, err := canon.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256(b)
	return NativeAuthorityRef{GrantID: g.GrantID, GrantDigest: hex.EncodeToString(h[:])}
}

func nativeEngineFixture(t *testing.T, mode string, base *grant.Grant, skills ...*grant.Grant) (*fixture, Request, *NativeInvocationVerification) {
	t.Helper()
	fx := newFixture(t, mode, nil, false)
	r := req("hermes", "read_file", readCallPath())
	r.RuntimeTaskID = "native-task"
	v := &NativeInvocationVerification{AgentGrant: base, SkillGrants: skills, Evidence: &NativeInvocationEvidence{
		CallID: "ncall-" + strings.Repeat("a", 32), CallSignature: strings.Repeat("b", 128), SessionRegistrationID: "nsess-" + strings.Repeat("c", 32),
		SessionSignature: strings.Repeat("d", 128), AgentAuthority: nativeRefForTest(t, base), NoSkill: len(skills) == 0, Contexts: []NativeContextRef{}}}
	b, err := trustedcontext.CallBinding(r.Platform, r.SessionID, r.AgentID, r.RuntimeTaskID, r.Tool, r.ToolCallID, r.Params)
	if err != nil {
		t.Fatal(err)
	}
	v.Evidence.RequestBinding = b
	for i, g := range skills {
		v.Evidence.Contexts = append(v.Evidence.Contexts, NativeContextRef{ContextID: fmt.Sprintf("sec-%032x", i), ContextSignature: strings.Repeat("e", 128), Authority: nativeRefForTest(t, g)})
	}
	fx.eng.opts.NativeCalls = func(Request) (bool, *NativeInvocationVerification, error) { return true, v, nil }
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) {
		return &IntentContract{
			IntentID: "native-intent", TaskID: "trusted-envelope", Principal: "user", AgentID: r.AgentID, Purpose: "native controlled read",
			AllowedEffects: []string{"file.read", "exec", "network.request", "file.write"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "revision", SelectedGrant: base}, nil
	}
	return fx, r, v
}

func TestNativeEngineIntersectsPinnedBaselineAndEverySkill(t *testing.T) {
	for _, denied := range []int{-1, 0, 1, 2} {
		t.Run(fmt.Sprint(denied), func(t *testing.T) {
			base := baselineGrant(t, "hermes", "read_file")
			leaf := skillGrant(t, "hermes", "leaf", "1", strings.Repeat("a", 64))
			parent := skillGrant(t, "hermes", "parent", "2", strings.Repeat("b", 64))
			grants := []*grant.Grant{base, leaf, parent}
			if denied >= 0 {
				grants[denied].OpenClawToolPolicy = &grant.OpenClawToolPolicy{Deny: []string{"read_file"}}
			}
			fx, r, _ := nativeEngineFixture(t, "block", base, leaf, parent)
			fx.eng.opts.BaselineGrants = func(_, _ string) *grant.Grant { t.Fatal("native path used newest baseline lookup"); return nil }
			d, err := fx.eng.Decide(r)
			if err != nil {
				t.Fatal(err)
			}
			want := ActionAllow
			if denied >= 0 {
				want = ActionDeny
			}
			if d.Action != want {
				t.Fatalf("intersection lost leg %d: %+v", denied, d)
			}
			if d.Receipt.SchemaVersion != "runtime-receipt/v3" || d.Receipt.NativeInvocation == nil || len(d.Receipt.NativeInvocation.Contexts) != 2 ||
				d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.SkillID != "leaf" || d.Receipt.SkillAttribution.EvidenceLevel != "controlled_invocation" {
				t.Fatal("full native evidence missing")
			}
			rows, err := fx.chain.Read()
			if err != nil || Verify(rows, fx.k.Public()) != nil {
				t.Fatal("native chain did not verify", err)
			}
		})
	}
}

func TestProtectedNativeSkillLoaderRequiresLiveNativeProofAndStrictShape(t *testing.T) {
	for _, name := range []string{"valid", "support", "legacy", "missing-proof", "extra", "absolute", "traversal", "non-string", "empty", "backslash", "no-name"} {
		t.Run(name, func(t *testing.T) {
			base := baselineGrant(t, "hermes", "skill_view")
			fx, r, v := nativeEngineFixture(t, "block", base)
			r.Tool, r.Params = "skill_view", map[string]any{"name": "reader"}
			switch name {
			case "support":
				r.Params["file_path"] = "reference/notes.md"
			case "legacy":
				fx.eng.opts.NativeCalls = nil
			case "missing-proof":
				fx.eng.opts.NativeCalls = func(Request) (bool, *NativeInvocationVerification, error) { return true, nil, nil }
			case "extra":
				r.Params["command"] = "unapproved"
			case "absolute":
				r.Params["file_path"] = "/etc/passwd"
			case "traversal":
				r.Params["file_path"] = "../outside"
			case "non-string":
				r.Params["name"] = true
			case "empty":
				r.Params["name"] = ""
			case "backslash":
				r.Params["name"] = "a\\b"
			case "no-name":
				r.Params = map[string]any{"file_path": "notes.md"}
			}
			binding, err := trustedcontext.CallBinding(r.Platform, r.SessionID, r.AgentID, r.RuntimeTaskID, r.Tool, r.ToolCallID, r.Params)
			if err != nil {
				t.Fatal(err)
			}
			v.Evidence.RequestBinding = binding
			fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) {
				return &IntentContract{IntentID: "native-load", TaskID: "trusted-envelope", Principal: "user", AgentID: r.AgentID, Purpose: "load approved Skill", AllowedEffects: []string{"tool.invoke"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "revision", SelectedGrant: base}, nil
			}
			d, err := fx.eng.Decide(r)
			if err != nil {
				t.Fatal(err)
			}
			if name == "valid" || name == "support" {
				if d.Action != ActionAllow || d.Receipt.Operation != "skill.load" || d.Receipt.NativeInvocation == nil {
					t.Fatal("verified loader refused", d.Action, d.Reason)
				}
			} else if d.Action != ActionDeny {
				t.Fatal("unverified loader accepted", name, d.Action)
			}
		})
	}
}

func TestNativeEngineResourceIntersectionAndApprovalPrecedence(t *testing.T) {
	for _, restricted := range []int{0, 1, 2} {
		t.Run(fmt.Sprint(restricted), func(t *testing.T) {
			base := baselineGrant(t, "hermes", "read_file")
			leaf := skillGrant(t, "hermes", "leaf", "1", strings.Repeat("a", 64))
			parent := skillGrant(t, "hermes", "parent", "2", strings.Repeat("b", 64))
			grants := []*grant.Grant{base, leaf, parent}
			// A hold on one leg must never override a resource denial on another.
			leaf.OpenClawToolPolicy = &grant.OpenClawToolPolicy{Allow: []string{"read_file"}, RequireApproval: []string{"read_file"}}
			for i := range grants[restricted].Facts {
				if grants[restricted].Facts[i].Domain == "filesystem" {
					grants[restricted].Facts[i].Resource.Value = "/not-this-task"
				}
			}
			fx, r, _ := nativeEngineFixture(t, "block", base, leaf, parent)
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny {
				t.Fatal("resource cap lost in intersection", err)
			}
		})
	}
	base := baselineGrant(t, "hermes", "read_file")
	leaf := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	base.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
	fx, r, _ := nativeEngineFixture(t, "block", base, leaf)
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal("baseline approval floor lost", err)
	}
	if !fx.eng.holdAuthorityCurrent(HoldStatusRequest{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, Tool: r.Tool,
		ToolCallID: r.ToolCallID, TaskID: d.Receipt.TaskID, RuntimeTaskID: r.RuntimeTaskID, Params: r.Params}, d.Receipt, fx.clock) {
		t.Fatal("original full native authority no longer verifies")
	}
}

func TestNativeEngineNoSkillAndRequiredFailure(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			base := baselineGrant(t, "hermes", "read_file")
			fx, r, _ := nativeEngineFixture(t, mode, base)
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionAllow || d.Receipt.SkillAttribution != nil || d.Receipt.NativeInvocation == nil || !d.Receipt.NativeInvocation.NoSkill {
				t.Fatal("no-skill baseline failed", err)
			}
			for _, lookup := range []NativeCallLookup{
				func(Request) (bool, *NativeInvocationVerification, error) { return true, nil, nil },
				func(Request) (bool, *NativeInvocationVerification, error) {
					return false, nil, errors.New("unavailable")
				},
			} {
				fx.eng.opts.NativeCalls = lookup
				r.ToolCallID += "next"
				d, err = fx.eng.Decide(r)
				if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityStatus != "invalid" || d.Receipt.NativeInvocation != nil {
					t.Fatal("required authority fell back", err)
				}
			}
		})
	}
}

func TestNativeEngineMalformedLookupHardDenies(t *testing.T) {
	for name, change := range map[string]func(*NativeInvocationVerification){
		"missing_evidence":  func(v *NativeInvocationVerification) { v.Evidence = nil },
		"missing_baseline":  func(v *NativeInvocationVerification) { v.AgentGrant = nil },
		"missing_ancestor":  func(v *NativeInvocationVerification) { v.SkillGrants = nil },
		"binding":           func(v *NativeInvocationVerification) { v.Evidence.RequestBinding = strings.Repeat("0", 64) },
		"context_signature": func(v *NativeInvocationVerification) { v.Evidence.Contexts[0].ContextSignature = "" },
		"call_signature":    func(v *NativeInvocationVerification) { v.Evidence.CallSignature = "" },
		"grant_digest": func(v *NativeInvocationVerification) {
			v.Evidence.Contexts[0].Authority.GrantDigest = strings.Repeat("0", 64)
		},
		"baseline_digest": func(v *NativeInvocationVerification) { v.Evidence.AgentAuthority.GrantDigest = strings.Repeat("0", 64) },
		"no_skill_lie":    func(v *NativeInvocationVerification) { v.Evidence.NoSkill = true },
		"cross_agent":     func(v *NativeInvocationVerification) { v.SkillGrants[0].Subject.ID = "other" },
	} {
		t.Run(name, func(t *testing.T) {
			base := baselineGrant(t, "hermes", "read_file")
			skill := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
			fx, r, v := nativeEngineFixture(t, "audit_only", base, skill)
			change(v)
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityStatus != "invalid" {
				t.Fatal("malformed native authority accepted", err)
			}
		})
	}
}

func TestNativeEngineBaselineIntentConflictAndClaimConflict(t *testing.T) {
	for _, kind := range []string{"selected_skill", "missing_intent", "false_claim", "no_skill_claim"} {
		t.Run(kind, func(t *testing.T) {
			base := baselineGrant(t, "hermes", "read_file")
			skill := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
			fx, r, _ := nativeEngineFixture(t, "audit_only", base, skill)
			switch kind {
			case "selected_skill":
				old := fx.eng.opts.IntentLookup
				fx.eng.opts.IntentLookup = func(p, s, a string) (*IntentContract, error) {
					i, e := old(p, s, a)
					i.SelectedGrant = skill
					return i, e
				}
			case "missing_intent":
				fx.eng.opts.IntentLookup = nil
			case "false_claim":
				r.Skill = claim("other", skillVersion, skillHash)
			case "no_skill_claim":
				fx, r, _ = nativeEngineFixture(t, "audit_only", base)
				r.Skill = claim(skillID, skillVersion, skillHash)
			}
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityStatus != "invalid" {
				t.Fatal("baseline or claim conflict accepted", err)
			}
		})
	}
}

func TestNativeEngineSnapshotsEvidenceAndKeepsLegacyOptional(t *testing.T) {
	base := baselineGrant(t, "hermes", "read_file")
	fx, r, v := nativeEngineFixture(t, "block", base)
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatal(err)
	}
	v.Evidence.CallSignature = strings.Repeat("f", 128)
	if d.Receipt.NativeInvocation.CallSignature == v.Evidence.CallSignature {
		t.Fatal("callback mutated prior signed evidence")
	}
	if Verify([]Receipt{d.Receipt}, fx.k.Public()) != nil {
		t.Fatal("signed receipt no longer verifies")
	}
	legacy := newFixture(t, "block", base, false)
	legacy.eng.opts.NativeCalls = func(Request) (bool, *NativeInvocationVerification, error) { return false, nil, nil }
	d, err = legacy.eng.Decide(req("hermes", "read_file", readCallPath()))
	if err != nil || d.Action != ActionAllow || d.Receipt.SchemaVersion != "" || d.Receipt.NativeInvocation != nil {
		t.Fatal("optional legacy path changed", err)
	}
}

func TestNativeEngineBudgetsParametersBeforeHostLookup(t *testing.T) {
	base := baselineGrant(t, "hermes", "read_file")
	fx, r, _ := nativeEngineFixture(t, "audit_only", base)
	called := false
	fx.eng.opts.NativeCalls = func(Request) (bool, *NativeInvocationVerification, error) { called = true; return true, nil, nil }
	var nested any = "synthetic"
	for i := 0; i < 70; i++ {
		nested = map[string]any{"nested": nested}
	}
	r.Params = map[string]any{"deep": nested}
	d, err := fx.eng.Decide(r)
	if err != nil || called || d.Action != ActionDeny || d.Receipt.ReasonCode != "runtime_parameter_budget_exceeded" {
		t.Fatal("unbounded parameters reached native canonicalization", err)
	}
}

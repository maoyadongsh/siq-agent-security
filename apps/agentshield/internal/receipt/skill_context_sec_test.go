package receipt

import (
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

// secLookup returns a SkillContextLookup that verifies exactly one subject.
func secLookup(v *SkillContextVerification, platform, agent, session, task string) SkillContextLookup {
	return func(p, a, s, taskID string, claim *SkillClaim) *SkillContextVerification {
		if p == platform && a == agent && s == session && (task == "" || taskID == task) {
			return v
		}
		return nil
	}
}

func validSEC(g *grant.Grant, skillID, version, hash string) *SkillContextVerification {
	return &SkillContextVerification{
		ContextID: "sec-" + strings.Repeat("ab", 16), EvidenceLevel: "controlled_task",
		SkillID: skillID, Version: version, ContentHash: hash, Grant: g,
	}
}

func TestSECVerifiedAttributionAllowsAndBindsCall(t *testing.T) {
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(g, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	r := req("hermes", verifiedCall, readCallPath())
	r.TaskID = "task-9"
	r.Skill = claim(skillID, skillVersion, skillHash)
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatalf("SEC-verified call must allow: %v %+v", err, d)
	}
	a := d.Receipt.SkillAttribution
	if a == nil || a.Status != SkillAttributionVerified || a.SkillID != skillID || a.EvidenceLevel != "controlled_task" || !strings.HasPrefix(a.ContextID, "sec-") {
		t.Fatalf("receipt must carry verified attribution with evidence level: %+v", a)
	}
	want, err := trustedcontext.CallBinding("hermes", "sess-1", "inst_1", "task-9", verifiedCall, "tc-1", readCallPath())
	if err != nil || a.CallBinding != want {
		t.Fatalf("call binding must be recomputable from receipt fields: %v %q want %q", err, a.CallBinding, want)
	}
	if d.Receipt.MatchedGrantID == nil || *d.Receipt.MatchedGrantID != g.GrantID {
		t.Fatalf("SEC grant must serve the call: %+v", d.Receipt.MatchedGrantID)
	}
}

func TestSECUsesRuntimeTaskWithoutWeakeningTrustedIntentTask(t *testing.T) {
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.IntentLookup = func(platform, sessionID, agentID string) (*IntentContract, error) {
		return &IntentContract{
			IntentID: "intent-runtime-envelope", TaskID: "task-trusted-envelope", Principal: "user-1",
			AgentID: "inst_1", Purpose: "read through managed runtime", AllowedEffects: []string{"file.read"},
			ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "rev-runtime", SelectedGrant: g,
		}, nil
	}
	var lookedUpTask string
	fx.eng.opts.SkillContexts = func(p, a, s, taskID string, claim *SkillClaim) *SkillContextVerification {
		lookedUpTask = taskID
		if taskID == "task-hermes-native" {
			return validSEC(g, skillID, skillVersion, skillHash)
		}
		return nil
	}
	r := req("hermes", verifiedCall, readCallPath())
	r.RuntimeTaskID = "task-hermes-native"
	r.Skill = claim(skillID, skillVersion, skillHash)
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatalf("separate trusted and runtime task must allow: %v %+v", err, d)
	}
	if lookedUpTask != r.RuntimeTaskID || d.Receipt.TaskID != "task-trusted-envelope" || d.Receipt.RuntimeTaskID != r.RuntimeTaskID {
		t.Fatalf("task identities were collapsed: lookup=%q receipt=%+v", lookedUpTask, d.Receipt)
	}
	want, err := trustedcontext.CallBinding(r.Platform, r.SessionID, r.AgentID, r.RuntimeTaskID, r.Tool, r.ToolCallID, r.Params)
	if err != nil || d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.CallBinding != want {
		t.Fatalf("SEC call binding did not use runtime task: %v %+v", err, d.Receipt.SkillAttribution)
	}

	// RuntimeTaskID is additive context, not a way to replace or evade the
	// trusted Intent task hint. A conflicting TaskID must keep failing closed.
	bad := r
	bad.ToolCallID = "tc-intent-spoof"
	bad.TaskID = r.RuntimeTaskID
	d, err = fx.eng.Decide(bad)
	if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_task_mismatch" {
		t.Fatalf("runtime task bypassed trusted Intent task: %v %+v", err, d)
	}
}

func TestMalformedRuntimeTaskFailsBeforeSECLookup(t *testing.T) {
	fx := newFixture(t, "audit_only", deployedGrant(t, "hermes", false), false)
	called := false
	fx.eng.opts.SkillContexts = func(_, _, _, _ string, _ *SkillClaim) *SkillContextVerification {
		called = true
		return nil
	}
	r := req("hermes", verifiedCall, readCallPath())
	r.RuntimeTaskID = "bad\nidentity"
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "runtime_task_invalid" || called {
		t.Fatalf("malformed runtime task reached authority lookup: %v called=%v %+v", err, called, d)
	}
}

func TestSECAppliesWithoutClaimAndWithoutFlag(t *testing.T) {
	// No skill claim on the request, enforcement flag off: the SEC alone
	// establishes the verified attribution (server-side subject match).
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(g, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	d, err := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if err != nil || d.Action != ActionAllow {
		t.Fatalf("SEC must authorize without a claim: %v %+v", err, d)
	}
	if d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.Status != SkillAttributionVerified {
		t.Fatalf("attribution must be SEC-derived: %+v", d.Receipt.SkillAttribution)
	}
}

func TestSECInvalidHardDeniesEvenInAuditMode(t *testing.T) {
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "audit_only", g, false)
	fx.eng.opts.SkillContexts = secLookup(&SkillContextVerification{Invalid: true, ReasonCode: "skill_context_revoked"}, "hermes", "inst_1", "sess-1", "")
	d, err := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if err != nil || d.Action != ActionDeny {
		t.Fatalf("invalid SEC must hard deny in every mode: %v %+v", err, d)
	}
	if d.Receipt.ReasonCode != "skill_context_revoked" || d.Receipt.AuthorityStatus != "invalid" {
		t.Fatalf("denial must be authority-class with the SEC code: %+v", d.Receipt)
	}
}

func TestSECBogusLookupFailsClosed(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(&SkillContextVerification{ContextID: "", Grant: nil, EvidenceLevel: "controlled_task"}, "hermes", "inst_1", "sess-1", "")
	d, _ := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if d.Action != ActionDeny || d.Receipt.ReasonCode != "skill_context_invalid" {
		t.Fatalf("contract-violating lookup must fail closed: %+v", d)
	}
}

func TestSECGrantConflictWithIntentSelection(t *testing.T) {
	skillG := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	other := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(skillG, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	fx.eng.opts.IntentLookup = func(platform, sessionID, agentID string) (*IntentContract, error) {
		return &IntentContract{
			IntentID: "i-conflict", TaskID: "t-conflict", Principal: "user-1", AgentID: "inst_1",
			Purpose: "read", AllowedEffects: []string{"file.read"}, ValidUntil: "2027-01-01T00:00:00Z",
			AuthorityRevision: "rev-1", EvidenceIDs: []string{"ev-1"}, SelectedGrant: other,
		}, nil
	}
	d, _ := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if d.Action != ActionDeny || d.Receipt.ReasonCode != "skill_context_grant_conflict" {
		t.Fatalf("conflicting intent grant selection must deny: %+v", d)
	}
}

// baselineGrant builds a live non-skill grant with the given tool allowlist
// plus the shared fs.read /home/u/proj fact used by readCallPath.
func baselineGrant(t *testing.T, platform string, tools ...string) *grant.Grant {
	t.Helper()
	facts := []admission.DeclaredFact{
		{Domain: "filesystem", Action: "fs.read", Resource: admission.Resource{Type: "path", Value: "/home/u/proj"},
			Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "t", EvidenceIDs: []string{"ev-1"}},
	}
	for _, tool := range tools {
		facts = append(facts, admission.DeclaredFact{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: tool},
			Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "t", EvidenceIDs: []string{"ev-1"}})
	}
	adm := admission.Admission{AdmissionID: "adm-base", ContentHash: strings.Repeat("c", 64), Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-1"}, DeclaredFacts: facts}
	k, err := signing.FromSeed([]byte(strings.Repeat("b", 32)))
	if err != nil {
		t.Fatal(err)
	}
	res, err := grant.Build(adm, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "inst_1"}, Platform: platform, Key: k})
	if err != nil {
		t.Fatal(err)
	}
	g, _ := grant.Approve(res.Grant, grant.Approval{ActorType: "human", ActorID: "u", ApprovedAt: "2026-09-13T00:00:00Z"}, k)
	g, _ = grant.MarkDeployed(g, k)
	return &g
}

func TestSECIntersectionBaselineNarrows(t *testing.T) {
	// The skill grant allows read_file; the baseline does not. Intersection denies.
	skillG := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	baseline := baselineGrant(t, "hermes", "web_fetch")
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(skillG, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	fx.eng.opts.BaselineGrants = func(p, a string) *grant.Grant { return baseline }
	d, _ := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if d.Action != ActionDeny || !strings.Contains(d.Reason, "baseline grant") {
		t.Fatalf("baseline must narrow the skill grant: %+v", d)
	}
	if d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.Status != SkillAttributionVerified {
		t.Fatalf("denial still records the verified attribution: %+v", d.Receipt.SkillAttribution)
	}
}

func TestSECIntersectionSkillNarrowsBaseline(t *testing.T) {
	// Baseline allows exec; the skill grant does not. The narrower skill wins.
	skillG := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	baseline := baselineGrant(t, "hermes", verifiedCall, "exec")
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(skillG, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	fx.eng.opts.BaselineGrants = func(p, a string) *grant.Grant { return baseline }
	d, _ := fx.eng.Decide(req("hermes", "exec", map[string]any{"cmd": "true"}))
	if d.Action != ActionDeny {
		t.Fatalf("skill grant must restrict the wider baseline: %+v", d)
	}
	d, _ = fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if d.Action != ActionAllow || !strings.Contains(d.Reason, "intersect") {
		t.Fatalf("both allow: %+v", d)
	}
}

func TestSECNoBaselineDegeneratesToSkillGrant(t *testing.T) {
	skillG := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillContexts = secLookup(validSEC(skillG, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	d, _ := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if d.Action != ActionAllow {
		t.Fatalf("no baseline: skill grant alone: %+v", d)
	}
	d, _ = fx.eng.Decide(req("hermes", "exec", map[string]any{"cmd": "true"}))
	if d.Action != ActionDeny {
		t.Fatalf("skill grant still restricts: %+v", d)
	}
}

func TestSECCrossSubjectCopyDenied(t *testing.T) {
	// A SEC for sess-1 does not cover sess-2; the skill grant must not serve
	// the copied subject and no tool side effect may occur.
	skillG := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.SkillAttributionEnforced = true
	fx.eng.opts.SkillContexts = secLookup(validSEC(skillG, skillID, skillVersion, skillHash), "hermes", "inst_1", "sess-1", "")
	fx.eng.opts.Grants = func(p, a string) *grant.Grant { return skillG }
	r := req("hermes", verifiedCall, readCallPath())
	r.SessionID = "sess-2"
	r.Skill = claim(skillID, skillVersion, skillHash)
	d, _ := fx.eng.Decide(r)
	if d.Action != ActionDeny {
		t.Fatalf("copied subject must deny: %+v", d)
	}
}

func TestInstalledSkillGrantRequiresSECWithoutLegacyFlag(t *testing.T) {
	// Installation grants are the authority R01 protects. Their reserved
	// admission marks them as installation-bound, so a copied claim cannot use
	// the grant while the legacy global attribution flag remains disabled.
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	g.AdmissionID = "adm-si-installed-skill"
	fx := newFixture(t, "block", g, false)
	r := req("hermes", verifiedCall, readCallPath())
	r.Skill = claim(skillID, skillVersion, skillHash)
	d, err := fx.eng.Decide(r)
	if err != nil {
		t.Fatal(err)
	}
	if d.Action != ActionDeny || d.Receipt.SkillAttribution == nil || d.Receipt.SkillAttribution.Status == SkillAttributionVerified {
		t.Fatalf("installed Skill grant without SEC must deny: %+v", d)
	}
}

func TestSECHoldResumeFailsWhenContextInvalidated(t *testing.T) {
	// Hold at decision time; the SEC is revoked before the approval resolves,
	// so the resume check must report the authority change instead of consuming.
	g := skillGrant(t, "hermes", skillID, skillVersion, skillHash)
	g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{Allow: []string{verifiedCall}, RequireApproval: []string{verifiedCall}}
	fx := newFixture(t, "block", nil, false)
	sec := validSEC(g, skillID, skillVersion, skillHash)
	live := true
	fx.eng.opts.SkillContexts = func(p, a, s, taskID string, claim *SkillClaim) *SkillContextVerification {
		if !live || p != "hermes" || a != "inst_1" || s != "sess-1" {
			return nil
		}
		return sec
	}
	d, err := fx.eng.Decide(req("hermes", verifiedCall, readCallPath()))
	if err != nil || d.Action != ActionHold {
		t.Fatalf("skill tool requires approval: %v %+v", err, d)
	}
	live = false
	st, err := fx.eng.ReadHoldStatus(HoldStatusRequest{
		Platform: "hermes", SessionID: "sess-1", AgentID: "inst_1", Tool: verifiedCall,
		ToolCallID: "tc-1", ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID, Params: readCallPath(),
	})
	if err != nil {
		t.Fatal(err)
	}
	// Unresolved hold is pending; the consumption gate must report the
	// authority change once the SEC no longer verifies.
	if st.Status != "pending" {
		t.Fatalf("unresolved hold stays pending: %+v", st)
	}
	if fx.eng.holdAuthorityCurrent(HoldStatusRequest{
		Platform: "hermes", SessionID: "sess-1", AgentID: "inst_1", Tool: verifiedCall,
		ToolCallID: "tc-1", ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID, Params: readCallPath(),
	}, d.Receipt, fx.clock) {
		t.Fatal("invalidated SEC must fail the resume authority check")
	}
}

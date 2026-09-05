package grant

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

var fixedNow = time.Date(2026, 9, 4, 6, 0, 0, 0, time.UTC)

func key(t *testing.T) *signing.Key {
	t.Helper()
	k, err := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func fact(domain, action, rtype, value string) admission.DeclaredFact {
	return admission.DeclaredFact{Domain: domain, Action: action, Resource: admission.Resource{Type: rtype, Value: value},
		Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "test", EvidenceIDs: []string{"ev-1"}}
}

func sampleAdmission() admission.Admission {
	return admission.Admission{
		AdmissionID: "adm-4af17a9f9719", ContentHash: "4af17a9f97199f397e267a992f07d36fdd1c01c9d6d618a87cf44c7e10108ab3",
		Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-1"},
		DeclaredFacts: []admission.DeclaredFact{
			fact("tool", "tool.invoke", "tool", "terminal"),
			fact("tool", "tool.invoke", "tool", "read_file"),
			fact("network", "http.request", "endpoint", "api.github.com:443"),
			fact("process", "process.exec", "tool", "shell"),
			fact("resource", "package.install", "package", "pip"),
			fact("filesystem", "fs.write", "path", "~/work/out"),
			fact("credential", "credential.read", "credential_ref", ".env"),
			fact("model", "model.generate", "model", "nemotron-local"),
		},
	}
}

func build(t *testing.T, platform string, adm admission.Admission) *Result {
	t.Helper()
	res, err := Build(adm, Options{Subject: Subject{Type: "agent_instance", ID: "inst_1"}, Platform: platform, Now: fixedNow, Key: key(t)})
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func human() Approval {
	return Approval{ActorType: "human", ActorID: "u-admin", ApprovedAt: "2026-09-04T06:05:00Z", Channel: "console"}
}

// artifact_hash produced by apps/control-api compile_policy for the same
// desired policy + capabilities (see PR notes); Go must reproduce it.
const pyArtifactHash = "60e90e56ea34fe46081f3c055b03e18b7a7cb135ced8edc57d5e0e9da38575b6"

func TestCompilePolicyParityWithPython(t *testing.T) {
	dp := `{"policy_id":"pol-grt-1","selector":{"agent_ids":["inst_1"]},"version":1,"status":"validated","enforcement_mode":"block",
	 "filesystem":{"read_only":["/skills/github-triage"],"read_write":["~/work/out"]},
	 "network":[{"endpoint":"api.github.com:443","effect":"allow"},{"endpoint":"astral.sh:443","effect":"allow"}],
	 "process":{"forbid_privilege_escalation":true},
	 "model_routing":{"allowed_models":["nemotron-local"]},
	 "tools":["terminal","read_file","web_extract"]}`
	v, err := canon.Decode([]byte(dp))
	if err != nil {
		t.Fatal(err)
	}
	caps := Capabilities{Backend: "openshell", SchemaVersion: "siq.openshell.policy.v1", DynamicNetworkUpdate: true,
		Items: map[string]CapabilityItem{
			"enforcement_mode.block": {"supported", "enforce", "test"},
			"model_routing":          {"unknown", "none", "not probed"},
			"tools_mcp":              {"unsupported", "none", "cli"},
		}}
	c, err := CompilePolicy(v.(map[string]any), caps)
	if err != nil {
		t.Fatal(err)
	}
	if c.ArtifactHash != pyArtifactHash {
		raw, _ := canon.Marshal(c.Artifact)
		t.Fatalf("artifact_hash differs from Python\n got %s\nwant %s\nartifact %s", c.ArtifactHash, pyArtifactHash, raw)
	}
	if !c.NeedsGeneration {
		t.Fatal("filesystem/process must set needs_generation")
	}
	want := []string{
		"model_routing.inference_routing: capability unknown（fail-closed）: not probed",
		"tools: capability tools_mcp=unsupported: cli",
	}
	if len(c.Unsupported) != len(want) || c.Unsupported[0] != want[0] || c.Unsupported[1] != want[1] {
		t.Fatalf("unsupported list differs: %v", c.Unsupported)
	}
}

func TestCompilePolicyRejectsUnknownKeys(t *testing.T) {
	_, err := CompilePolicy(map[string]any{"policy_id": "p", "bogus": 1}, Capabilities{})
	var ue *ErrUnsupported
	if err == nil || !errorsAs(err, &ue) {
		t.Fatalf("unknown key must refuse to compile, got %v", err)
	}
}

func TestCompilePolicyStaticNetworkWhenNoDynamicUpdate(t *testing.T) {
	c, err := CompilePolicy(map[string]any{"network": []any{map[string]any{"endpoint": "a:443", "effect": "allow"}}},
		Capabilities{Items: map[string]CapabilityItem{"enforcement_mode.audit_only": {"supported", "observe", "t"}}})
	if err != nil {
		t.Fatal(err)
	}
	if !c.NeedsGeneration || c.Unsupported[0] != "network.dynamic_update" {
		t.Fatalf("network without dynamic update must be static + unsupported: %+v", c)
	}
}

func TestIsLiveStatus(t *testing.T) {
	if !IsLiveStatus("pending_approval") || !IsLiveStatus("approved") || !IsLiveStatus("deployed") || !IsLiveStatus("effective") {
		t.Fatal("live statuses")
	}
	if IsLiveStatus("rejected") || IsLiveStatus("revoked") || IsLiveStatus("draft") || IsLiveStatus("") {
		t.Fatal("terminal/empty must not be live")
	}
}

func TestBuildTransformsDeclaredFactsPerTable(t *testing.T) {
	res := build(t, "hermes", sampleAdmission())
	g := res.Grant
	if g.DefaultEffect != "deny" || g.Status != "pending_approval" || g.Platform != "hermes" {
		t.Fatalf("%+v", g)
	}
	if g.HermesToolsetAllowlist == nil {
		t.Fatal("hermes grant must carry allowlist")
	}
	al := *g.HermesToolsetAllowlist
	if len(al) != 2 || al[0] != "read_file" || al[1] != "terminal" {
		t.Fatalf("allowlist %v", al) // process.exec adds terminal; already declared → deduped
	}
	// credential → inferred deny, never allow
	var credDeny, privDeny bool
	for _, f := range g.Facts {
		if f.State == "effective" {
			t.Fatal("no fact may be effective before readback")
		}
		if f.Domain == "credential" {
			if f.Effect != "deny" || f.State != "inferred" || f.Authority != "agentshield" {
				t.Fatalf("credential must become inferred deny: %+v", f)
			}
			credDeny = true
		}
		if f.Action == "process.privilege_escalation" && f.Effect == "deny" && f.State == "inferred" {
			privDeny = true
		}
	}
	if !credDeny || !privDeny {
		t.Fatal("missing credential deny or privilege-escalation deny")
	}
	// desired policy shape
	dp := res.DesiredPolicy
	if dp["network"] == nil || dp["filesystem"] == nil || dp["process"] == nil || dp["model_routing"] == nil || dp["tools"] == nil {
		t.Fatalf("desired policy missing domains: %v", dp)
	}
	sd := g.DesiredPolicyRef.StaticDomainsUnavailable
	if len(sd) != 2 || sd[0] != "filesystem" || sd[1] != "process" {
		t.Fatalf("static domains must be declared unavailable: %v", sd)
	}
	if _, err := CompilePolicy(dp, Capabilities{DynamicNetworkUpdate: true}); err != nil {
		t.Fatalf("desired policy must compile: %v", err)
	}
}

func TestBuildOpenClawPolicy(t *testing.T) {
	g := build(t, "openclaw", sampleAdmission()).Grant
	if g.OpenClawToolPolicy == nil || g.HermesToolsetAllowlist != nil {
		t.Fatal("openclaw grant must carry openclaw_tool_policy only")
	}
	p := g.OpenClawToolPolicy
	if len(p.Allow) != 2 || p.Allow[0] != "read_file" {
		t.Fatalf("allow %v", p.Allow)
	}
	if len(p.RequireApproval) != 1 || p.RequireApproval[0] != "exec" {
		t.Fatalf("exec (process/package/credential) must require approval: %v", p.RequireApproval)
	}
}

func TestBuildRefusesQuarantine(t *testing.T) {
	adm := sampleAdmission()
	adm.Verdict = "quarantine"
	if _, err := Build(adm, Options{Subject: Subject{"agent_instance", "x"}, Platform: "hermes", Key: key(t)}); err == nil {
		t.Fatal("quarantined admission must not be grantable")
	}
	if _, err := Build(sampleAdmission(), Options{Subject: Subject{"agent_instance", "x"}, Platform: "windows95", Key: key(t)}); err == nil {
		t.Fatal("unknown platform must be rejected")
	}
}

func TestDenyOverridesAllowOnOverlap(t *testing.T) {
	adm := sampleAdmission()
	adm.DeclaredFacts = []admission.DeclaredFact{
		fact("filesystem", "fs.write", "path", "~/work/"),
		fact("filesystem", "fs.write", "path", "~/work/out"),
	}
	res := build(t, "hermes", adm)
	if len(res.Grant.OverlapConflicts) != 1 || res.Grant.OverlapConflicts[0].Resolution != "unresolved" {
		t.Fatalf("same-effect overlap must be unresolved: %+v", res.Grant.OverlapConflicts)
	}
	// deny vs allow overlap: allow is dropped
	facts, overlaps := resolveOverlaps([]Fact{
		{FactID: "a", Domain: "network", Resource: admission.Resource{Type: "endpoint", Value: "*.example.com"}, Effect: "deny"},
		{FactID: "b", Domain: "network", Resource: admission.Resource{Type: "endpoint", Value: "api.example.com:443"}, Effect: "allow"},
	})
	if len(overlaps) != 1 || overlaps[0].Resolution != "deny_overrides" {
		t.Fatalf("%+v", overlaps)
	}
	if len(facts) != 1 || facts[0].FactID != "a" {
		t.Fatalf("allow fact must be dropped, kept %+v", facts)
	}
}

func TestApprovalRequiresHumanAndResolvedOverlaps(t *testing.T) {
	k := key(t)
	adm := sampleAdmission()
	adm.DeclaredFacts = []admission.DeclaredFact{fact("filesystem", "fs.write", "path", "~/w/"), fact("filesystem", "fs.write", "path", "~/w/x")}
	g := build(t, "hermes", adm).Grant
	if _, err := Approve(g, human(), k); err == nil {
		t.Fatal("unresolved overlap must block approval")
	}
	if _, err := ResolveOverlap(g, 0, Approval{ActorType: "model", ActorID: "llm"}, k); err == nil {
		t.Fatal("model must not resolve overlaps")
	}
	g, err := ResolveOverlap(g, 0, human(), k)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Approve(g, Approval{ActorType: "model", ActorID: "llm", ApprovedAt: "x"}, k); err == nil {
		t.Fatal("model must not approve (ADR-003)")
	}
	if _, err := Approve(g, Approval{ActorType: "human", ActorID: "", ApprovedAt: "x"}, k); err == nil {
		t.Fatal("anonymous human must not approve")
	}
	g, err = Approve(g, human(), k)
	if err != nil || g.Status != "approved" || g.ApprovedBy == nil {
		t.Fatalf("%v %+v", err, g.Status)
	}
	if !Verify(k.Public(), g) {
		t.Fatal("approved grant must verify")
	}
}

func TestStateMachineRejectsIllegalTransitions(t *testing.T) {
	k := key(t)
	g := build(t, "hermes", sampleAdmission()).Grant
	if _, err := MarkDeployed(g, k); err == nil {
		t.Fatal("pending → deployed must be illegal")
	}
	if _, err := MarkEffective(g, Readback{"openshell", "7", "t", "ev-9"}, map[string]string{}, k); err == nil {
		t.Fatal("pending → effective must be illegal")
	}
	g, _ = Approve(g, human(), k)
	if _, err := Approve(g, human(), k); err == nil {
		t.Fatal("double approve must fail")
	}
	g, err := MarkDeployed(g, k)
	if err != nil {
		t.Fatal(err)
	}
	g, err = Revoke(g, k)
	if err != nil || g.Status != "revoked" {
		t.Fatal(err)
	}
	if _, err := MarkEffective(g, Readback{"openshell", "7", "t", "ev-9"}, nil, k); err == nil {
		t.Fatal("revoked is terminal")
	}
}

func TestEffectiveRequiresReadbackAndSkipsStaticDomains(t *testing.T) {
	k := key(t)
	g := build(t, "hermes", sampleAdmission()).Grant
	g, _ = Approve(g, human(), k)
	g, _ = MarkDeployed(g, k)
	var netID, fsID string
	for _, f := range g.Facts {
		if f.Domain == "network" {
			netID = f.FactID
		}
		if f.Domain == "filesystem" {
			fsID = f.FactID
		}
	}
	if _, err := MarkEffective(g, Readback{Backend: "openshell", Revision: "", VerifiedAt: "t", EvidenceID: "ev-9"}, map[string]string{netID: "ev-9"}, k); err == nil {
		t.Fatal("empty revision must be rejected")
	}
	if _, err := MarkEffective(g, Readback{"openshell", "7", "t", "ev-9"}, map[string]string{}, k); err == nil {
		t.Fatal("no confirmed fact must be rejected")
	}
	if _, err := MarkEffective(g, Readback{"openshell", "7", "t", "ev-9"}, map[string]string{fsID: "ev-9"}, k); err == nil {
		t.Fatal("static filesystem fact must never become effective (create_generation unavailable)")
	}
	g2, err := MarkEffective(g, Readback{"openshell", "7", "2026-09-04T06:10:00Z", "ev-9"}, map[string]string{netID: "ev-9"}, k)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range g2.Facts {
		switch f.FactID {
		case netID:
			if f.State != "effective" || f.Authority != "openshell" || f.AuthorityRevision == nil || *f.AuthorityRevision != "7" || f.ReadbackEvidenceID == nil {
				t.Fatalf("network fact not promoted correctly: %+v", f)
			}
		default:
			if f.State == "effective" {
				t.Fatalf("unconfirmed fact promoted: %+v", f)
			}
		}
	}
	if g2.EffectiveReadback == nil || g2.Status != "effective" || !Verify(k.Public(), g2) {
		t.Fatal("effective grant incomplete or unsigned")
	}
}

func TestSignatureTamperFails(t *testing.T) {
	k := key(t)
	g := build(t, "hermes", sampleAdmission()).Grant
	g.DefaultEffect = "allow"
	if Verify(k.Public(), g) {
		t.Fatal("tampered grant must not verify")
	}
}

// Contract samples for apps/control-api schema validation (pending + effective).
func TestContractSamplesAreCurrent(t *testing.T) {
	k := key(t)
	res := build(t, "hermes", sampleAdmission())
	g := res.Grant
	pending, _ := json.MarshalIndent(g, "", "  ")
	g, _ = Approve(g, human(), k)
	g, _ = MarkDeployed(g, k)
	var netID string
	for _, f := range g.Facts {
		if f.Domain == "network" {
			netID = f.FactID
		}
	}
	g, err := MarkEffective(g, Readback{"openshell", "7", "2026-09-04T06:10:00Z", "ev-9"}, map[string]string{netID: "ev-9"}, k)
	if err != nil {
		t.Fatal(err)
	}
	effective, _ := json.MarshalIndent(g, "", "  ")
	dp, _ := json.MarshalIndent(res.DesiredPolicy, "", "  ")
	dir := filepath.Join("..", "..", "testdata", "contracts")
	files := map[string][]byte{"grant.pending.sample.json": pending, "grant.effective.sample.json": effective, "desired-policy.sample.json": dp}
	for name, got := range files {
		p := filepath.Join(dir, name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			_ = os.WriteFile(p, append(got, '\n'), 0o644)
		}
		want, err := os.ReadFile(p)
		if err != nil {
			t.Fatalf("missing sample %s (run with AGENTSHIELD_UPDATE_SAMPLES=1)", name)
		}
		if !bytes.Equal(bytes.TrimSpace(want), got) {
			t.Fatalf("%s drifted; regenerate with AGENTSHIELD_UPDATE_SAMPLES=1", name)
		}
	}
}

func TestPatchDesiredPendingOnlyAndStatic(t *testing.T) {
	k := key(t)
	g := build(t, "hermes", sampleAdmission()).Grant
	patched, dp, err := PatchDesired(g, DesiredPatch{
		HasTools: true, Tools: []string{"web_fetch"},
		HasNetwork: true, Network: []NetworkPatch{{Endpoint: "api.example.com:443", Effect: "allow"}},
		HasFilesystem: true, Filesystem: &FilesystemPatch{ReadWrite: []string{"/tmp"}},
	}, k)
	if err != nil {
		t.Fatal(err)
	}
	if patched.Status != "pending_approval" {
		t.Fatalf("status %s", patched.Status)
	}
	static := strings.Join(patched.DesiredPolicyRef.StaticDomainsUnavailable, ",")
	if !strings.Contains(static, "filesystem") {
		t.Fatalf("fs patch must mark static: %s", static)
	}
	if dp["network"] == nil {
		t.Fatal("desired policy missing network")
	}
	g, _ = Approve(patched, human(), k)
	if _, _, err := PatchDesired(g, DesiredPatch{HasTools: true, Tools: []string{"read_file"}}, k); err == nil {
		t.Fatal("approved grant must not accept patch-desired")
	}
}

func errorsAs(err error, target **ErrUnsupported) bool {
	e, ok := err.(*ErrUnsupported)
	if ok {
		*target = e
	}
	return ok
}

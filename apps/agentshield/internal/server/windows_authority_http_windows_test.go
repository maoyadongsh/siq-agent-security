package server

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type windowsAuthorityHTTPFixture struct {
	s                                                                           *Server
	st                                                                          *state.Store
	instance, agent, credential, identityID, session, grantID, intentID, taskID string
	root, input, output, outside                                                string
	revision                                                                    int
}

// Send the exact bearer without the legacy call helper's admin substitution.
func windowsAuthorityHTTP(t *testing.T, s *Server, method, route, bearer string, body any, want int) map[string]any {
	t.Helper()
	started := time.Now()
	r := loopbackRequest(method, route, body)
	if bearer != "" {
		r.Header.Set("Authorization", "Bearer "+bearer)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	t.Logf("%s %s: status=%d elapsed=%s", method, route, w.Code, time.Since(started).Round(time.Millisecond))
	if w.Code != want {
		t.Fatalf("%s %s: status=%d want=%d response=%s", method, route, w.Code, want, w.Body.String())
	}
	var out map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func (f windowsAuthorityHTTPFixture) decision(tool, callID, path string) map[string]any {
	return map[string]any{
		"platform": "hermes", "agent_id": f.agent, "session_id": f.session,
		"task_id": f.taskID, "runtime_task_id": f.session + "-task",
		"tool": tool, "tool_call_id": callID, "params": map[string]any{"path": path},
	}
}

// A real initialized state and the production stores/resolvers are retained.
// Only the initial pending Grant is seeded directly; all versioned edits,
// approval, deployment, identity issuance and enrollment use HTTP handlers.
// No desktop, host process or model is started by this component fixture.
func newWindowsAuthorityHTTPFixture(t *testing.T, mode string, requireApproval bool) windowsAuthorityHTTPFixture {
	t.Helper()
	started := time.Now()
	stage := func(name string) {
		t.Helper()
		t.Logf("Windows Authority setup %s: total=%s", name, time.Since(started).Round(time.Millisecond))
	}
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 47611)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	// Complete first-use credential bootstrap before creating migration
	// history; established state must never silently create a replacement key.
	k, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	decisionToken, err := st.Token()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.ActivateWindowsProfile(true, "windows-authority-http-test"); err != nil {
		t.Fatal(err)
	}
	stage("initialized and explicitly activated")
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(st.Dir, "local", k)
	if err != nil {
		t.Fatal(err)
	}
	// Match serve's wiring: the engine obtains authority from the committed
	// state resolver, and Server.New independently opens the same stores.
	intents, err := st.IntentAuthority(k)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{
		Pack: pack, Chain: chain, Grants: st.ActiveGrant, BaselineGrants: st.BaselineGrant,
		EnforcementMode: mode, IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(intents),
		ContextLookup: intents.GetContext, HoldChannel: "console", HoldTimeoutMS: 120000,
	})
	if err != nil {
		t.Fatal(err)
	}
	home := filepath.Join(t.TempDir(), "Home")
	profile := filepath.Join(home, ".hermes", "profiles", "windows-test")
	if err := os.MkdirAll(profile, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profile, "config.yaml"), []byte("model: component-fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := New(Deps{Store: st, Engine: engine, Chain: chain, Pack: pack, Key: k, Token: decisionToken,
		Version: "windows-authority-test", Mode: mode, Home: home, LocalAppData: filepath.Join(home, "AppData", "Local"),
		HermesCLI: filepath.Join(home, "missing-hermes.exe"), Binary: filepath.Join(home, "unused-agentshield.exe"),
		ListenHost: "127.0.0.1", ListenPort: 47611, PairingCode: testPairingCode})
	if err != nil {
		t.Fatal(err)
	}
	s.bootAdmin, err = s.RedeemPairing(testPairingCode)
	if err != nil {
		t.Fatal(err)
	}
	stage("server opened")
	listed := windowsAuthorityHTTP(t, s, "GET", "/v1/adapter/instances?platform=hermes", s.bootAdmin, nil, 200)
	var instance string
	for _, item := range listed["instances"].([]any) {
		row := item.(map[string]any)
		if row["name"] == "windows-test" && row["detected"] == true && row["source"] == "named_profile" {
			if instance != "" {
				t.Fatal("profile discovery was ambiguous")
			}
			instance = row["instance_id"].(string)
		}
	}
	if instance == "" {
		t.Fatal("actual named Hermes profile was not discovered")
	}
	agent, err := runtimeidentity.AgentID(instance)
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "Approved")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	input := filepath.Join(root, "Input.txt")
	if err := os.WriteFile(input, []byte("controlled Windows input"), 0600); err != nil {
		t.Fatal(err)
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", root)
	if err != nil {
		t.Fatal(err)
	}
	facts := []admission.DeclaredFact{}
	for _, tool := range []string{"read_file", "write_file"} {
		facts = append(facts, admission.DeclaredFact{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: tool}, Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "fixture", EvidenceIDs: []string{"fixture-permission"}})
	}
	built, err := grant.Build(admission.Admission{AdmissionID: "adm-windows-http", ContentHash: strings.Repeat("a", 64), Verdict: "admit_with_conditions", EvidenceIDs: []string{"fixture-permission"}, DeclaredFacts: facts}, grant.Options{Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}, Key: k})
	if err != nil {
		t.Fatal(err)
	}
	if requireApproval {
		built.Grant, err = grant.RequireToolApproval(built.Grant, []string{"write_file"}, k)
		if err != nil {
			t.Fatal(err)
		}
	}
	seq, err := st.CommitGrant(state.GrantCommit{Grant: built.Grant, DesiredPolicy: built.DesiredPolicy, ExpectedRevision: -1,
		Audit: &state.AuditEvent{Event: "grant_create", Target: built.Grant.GrantID, ActorID: "fixture-owner", At: time.Now().UTC().Format(time.RFC3339Nano)}})
	if err != nil {
		t.Fatal(err)
	}
	stage("pending Grant committed")
	pending, persistedSeq, err := st.GetGrantWithSeq(built.Grant.GrantID)
	if err != nil || pending == nil {
		t.Fatal("pending Grant unavailable", err)
	}
	if persistedSeq != seq || pending.Status != "pending_approval" || pending.SchemaVersion != "" || pending.Skill != nil || pending.Subject.Type != "agent_instance" || pending.Platform != "hermes" || !grant.Verify(k.Public(), *pending) {
		t.Fatalf("pending Grant preconditions: seq=%d/%d status=%s schema=%s skill=%t subject=%s platform=%s signature=%t", persistedSeq, seq, pending.Status, pending.SchemaVersion, pending.Skill != nil, pending.Subject.Type, pending.Platform, grant.Verify(k.Public(), *pending))
	}
	snapshot, err := runtimepath.InspectWindows(canonical, false)
	if err != nil || !snapshot.IsDirectory() {
		t.Fatal("actual approved directory could not be verified; TEMP must use its final native path", err)
	}
	if _, err := snapshot.IdentityDigest(); err != nil {
		t.Fatal("actual approved directory identity unavailable", err)
	}
	route := "/v1/grants/" + built.Grant.GrantID
	edited := windowsAuthorityHTTP(t, s, "POST", route+"/resources", s.bootAdmin, map[string]any{
		"schema_version": "grant-resource-edit/v2", "expected_revision": seq, "actor_id": "fixture-owner", "confirm_filesystem_profile": true,
		"tools": []string{"read_file", "write_file"}, "network": []any{}, "models": []string{},
		"filesystem": map[string]any{"read_only": []string{}, "read_write": []string{canonical}},
	}, 200)
	seq = stateRevision(t, edited)
	challenge := windowsAuthorityHTTP(t, s, "POST", route+"/challenge", s.bootAdmin, withRevision(nil, seq), 200)["challenge"].(map[string]any)
	approved := windowsAuthorityHTTP(t, s, "POST", route+"/approve", s.bootAdmin, withRevision(map[string]any{"actor_id": "fixture-owner", "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"]}, seq), 200)
	deployed := windowsAuthorityHTTP(t, s, "POST", route+"/deploy", s.bootAdmin, withRevision(nil, stateRevision(t, approved)), 200)
	seq = stateRevision(t, deployed)
	g, currentSeq, err := st.RuntimeGrantWithSeq(built.Grant.GrantID)
	if err != nil || g == nil || currentSeq != seq || g.SchemaVersion != "grant/v2" || !grant.Verify(k.Public(), *g) {
		t.Fatal("HTTP deployment did not produce committed Windows authority", err)
	}
	stage("new Grant edited, challenged, approved and deployed")
	issued := windowsAuthorityHTTP(t, s, "POST", "/v1/runtime-identities", s.bootAdmin, map[string]any{
		"schema_version": "local-runtime-identity-create/v2", "confirm_filesystem_profile": true,
		"instance_id": instance, "grant_id": g.GrantID, "expected_grant_revision": seq, "actor_id": "fixture-owner", "session_ttl_seconds": 3600,
	}, 201)
	identity := issued["identity"].(map[string]any)
	if issued["schema_version"] != "local-runtime-identity-issued/v2" || identity["filesystem_profile"] != "windows-local-drive/v1" {
		t.Fatal("identity response lost the Windows interpretation")
	}
	credential, err := os.ReadFile(issued["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	session := "windows-authority-http"
	enrolled := windowsAuthorityHTTP(t, s, "POST", "/v1/runtime-sessions", string(credential), map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session}, 200)
	c, binding, err := s.intents.ResolveBinding("hermes", session, agent)
	if err != nil || c == nil || binding == nil || c.SchemaVersion != "intent/v4" || binding.SchemaVersion != "intent-grant-binding/v2" || binding.GrantRef == nil || binding.GrantRef.PermissionDigestSchema != "grant-permissions/v2" || enrolled["intent_id"] != c.IntentID {
		t.Fatal("HTTP enrollment lost the signed profile chain", err)
	}
	stage("identity issued and native session enrolled")
	return windowsAuthorityHTTPFixture{s: s, st: st, instance: instance, agent: agent, credential: string(credential), identityID: identity["identity_id"].(string),
		session: session, grantID: g.GrantID, revision: seq, intentID: c.IntentID, taskID: c.TaskID,
		root: root, input: input, output: filepath.Join(root, "Output.txt"), outside: filepath.Join(filepath.Dir(root), "Outside.txt")}
}

func TestWindowsAuthorityHTTPProductionChain(t *testing.T) {
	f := newWindowsAuthorityHTTPFixture(t, "block", false)
	allowed := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, f.decision("read_file", "approved-read", f.input), 200)
	if allowed["action"] != "allow" || allowed["authority_status"] != "valid" || allowed["task_id"] != f.taskID {
		t.Fatal("actual managed HTTP read did not use its enrolled authority", allowed)
	}
	for _, bearer := range []string{f.s.d.Token, f.s.bootAdmin} {
		want := 403
		if bearer == f.s.bootAdmin {
			want = 401
		}
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", bearer, f.decision("read_file", "borrow-attempt", f.input), want)
	}
	denied := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, f.decision("write_file", "outside-write", f.outside), 200)
	if denied["action"] != "deny" || denied["policy_action"] != "deny" {
		t.Fatal("out-of-scope write allowed", denied)
	}
	if _, err := os.Stat(f.outside); !os.IsNotExist(err) {
		t.Fatal("component denial unexpectedly changed the outside target", err)
	}
	c, err := f.s.intents.Get(f.intentID)
	if err != nil {
		t.Fatal(err)
	}
	c.IntentID = "int-forged-managed-http"
	c.Digest, c.Signature, c.SigningSchema = "", "", ""
	refused := windowsAuthorityHTTP(t, f.s, "POST", "/v1/intents", f.s.bootAdmin, c, 400)
	if refused["error"] != "intent_managed_issuer_required" {
		t.Fatal("wrong managed issuer rejection", refused)
	}
	if _, err := f.s.intents.Get(c.IntentID); !os.IsNotExist(err) {
		t.Fatal("ordinary HTTP route published managed authority", err)
	}
	create := map[string]any{"schema_version": "local-runtime-identity-create/v2", "confirm_filesystem_profile": true, "instance_id": f.instance,
		"grant_id": f.grantID, "expected_grant_revision": f.revision, "actor_id": "fixture-owner", "session_ttl_seconds": 3600}
	raw, err := json.Marshal(create)
	if err != nil {
		t.Fatal(err)
	}
	for _, malformed := range []string{
		strings.Replace(string(raw), `"confirm_filesystem_profile":true,`, "", 1),
		strings.Replace(string(raw), `"confirm_filesystem_profile":true`, `"confirm_filesystem_profile":false`, 1),
		strings.Replace(string(raw), `"confirm_filesystem_profile":`, `"Confirm_Filesystem_Profile":`, 1),
		`{"confirm_filesystem_profile":false,` + string(raw)[1:],
	} {
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities", f.s.bootAdmin, malformed, 400)
	}
	create["schema_version"] = "local-runtime-identity-create/v1"
	delete(create, "confirm_filesystem_profile")
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities", f.s.bootAdmin, create, 400)
	listed := windowsAuthorityHTTP(t, f.s, "GET", "/v1/runtime-identities", f.s.bootAdmin, nil, 200)
	if listed["schema_version"] != "local-runtime-identities/v2" || len(listed["items"].([]any)) != 1 {
		t.Fatal("refused create mutated issued identities")
	}
	resourceEdit := map[string]any{"schema_version": "grant-resource-edit/v2", "expected_revision": f.revision, "actor_id": "fixture-owner", "confirm_filesystem_profile": true,
		"tools": []string{"read_file", "write_file"}, "network": []any{}, "models": []string{},
		"filesystem": map[string]any{"read_only": []string{}, "read_write": []string{filepath.ToSlash(f.root)}}}
	resourceRaw, err := json.Marshal(resourceEdit)
	if err != nil {
		t.Fatal(err)
	}
	for _, malformed := range []string{
		strings.Replace(string(resourceRaw), `"confirm_filesystem_profile":true,`, "", 1),
		strings.Replace(string(resourceRaw), `"read_write":`, `"Read_Write":`, 1),
		`{"confirm_filesystem_profile":false,` + string(resourceRaw)[1:],
	} {
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/grants/"+f.grantID+"/resources", f.s.bootAdmin, malformed, 400)
	}
	if _, seq, err := f.st.GetGrantWithSeq(f.grantID); err != nil || seq != f.revision {
		t.Fatal("refused resource edit changed the deployed Grant", err)
	}
	events, err := f.st.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, event := range events {
		if event.Target == f.grantID {
			seen[event.Event] = true
		}
	}
	for _, event := range []string{"grant_create", "grant_resources", "grant_approve", "grant_deploy"} {
		if !seen[event] {
			t.Fatalf("missing committed audit %s", event)
		}
	}
	records, err := f.s.d.Chain.Read()
	if err != nil || len(records) != 2 || records[0].IntentID != f.intentID || records[1].IntentID != f.intentID || receipt.Verify(records, f.s.d.Key.Public()) != nil {
		t.Fatal("managed decisions missing from verified receipt chain", err)
	}
}

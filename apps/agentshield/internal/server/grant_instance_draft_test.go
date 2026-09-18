package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

const instanceDraftRoute = "/v1/grants/instance-drafts"

func instanceDraftFixture(t *testing.T) (*Server, *state.Store, map[string]any) {
	t.Helper()
	t.Setenv("WORKBUDDY_CONFIG_DIR", "")
	t.Setenv("HERMES_HOME", "")
	s, store := newServer(t, "block")
	profile := filepath.Join(s.d.Home, ".hermes", "profiles", "instance-draft")
	if err := os.MkdirAll(profile, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profile, "config.yaml"), []byte("model: component-fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	code, listed := call(t, s, "GET", "/v1/adapter/instances?platform=hermes", token, nil)
	if code != 200 {
		t.Fatal(code, listed)
	}
	instance := ""
	for _, raw := range listed["instances"].([]any) {
		row := raw.(map[string]any)
		if row["name"] == "instance-draft" && row["detected"] == true {
			if instance != "" {
				t.Fatal("ambiguous fixture instance")
			}
			instance = row["instance_id"].(string)
		}
	}
	if instance == "" {
		t.Fatal("real fixture profile not discovered")
	}
	skill := filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like")
	code, admitted := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	if code != 200 {
		t.Fatal(code, admitted)
	}
	a := admitted["admission"].(map[string]any)
	if a["skill_id"] == "" || a["content_hash"] == "" || a["verdict"] == "quarantine" {
		t.Fatal("fixture must be an actual admitted Skill", a)
	}
	return s, store, map[string]any{"schema_version": "grant-instance-draft-create/v1", "actor_id": "fixture-operator", "instance_id": instance, "admission_id": a["admission_id"], "request_id": "gid-" + strings.Repeat("a", 32), "confirm_instance_scope": true}
}

func copyInstanceDraftRequest(body map[string]any) map[string]any {
	copy := map[string]any{}
	for k, v := range body {
		copy[k] = v
	}
	return copy
}

func TestInstanceDraftHTTPRealAdmissionIndependentConcurrentAndAudited(t *testing.T) {
	s, store, body := instanceDraftFixture(t)
	admissionPath := filepath.Join(store.Dir, "admissions", body["admission_id"].(string)+".json")
	admissionBefore, err := os.ReadFile(admissionPath)
	if err != nil {
		t.Fatal(err)
	}
	instance := body["instance_id"].(string)
	subject := "hri-" + strings.TrimPrefix(instance, "hi-")
	code, legacy := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": body["admission_id"], "platform": "hermes", "subject_id": subject, "redact_secrets": true})
	if code != 200 {
		t.Fatal(code, legacy)
	}
	oldID := legacy["grant"].(map[string]any)["grant_id"].(string)
	old, oldRev, err := store.GetGrantWithSeq(oldID)
	if err != nil || old.Skill == nil {
		t.Fatal("real legacy Skill grant was not preserved", err)
	}
	oldBefore, _ := json.Marshal(old)
	type result struct {
		code int
		out  map[string]any
	}
	results := make(chan result, 3)
	var wg sync.WaitGroup
	for range 3 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			code, out := call(t, s, "POST", instanceDraftRoute, token, body)
			results <- result{code, out}
		}()
	}
	wg.Wait()
	close(results)
	newID, created := "", 0
	for result := range results {
		if result.code != 200 && result.code != 201 {
			t.Fatal("concurrent draft failed", result.code, result.out)
		}
		if result.code == 201 {
			created++
		}
		id := result.out["grant"].(map[string]any)["grant_id"].(string)
		if newID != "" && newID != id {
			t.Fatal("duplicate concurrent draft")
		}
		newID = id
	}
	if created != 1 || newID == oldID {
		t.Fatal("new independent draft count", created)
	}
	g, revision, err := store.GetGrantWithSeq(newID)
	if err != nil || revision != 0 || g.Skill != nil || g.Status != "pending_approval" || g.ApprovedBy != nil || g.EffectiveReadback != nil || g.AdmissionID != body["admission_id"] || g.Subject.ID != subject || g.Platform != "hermes" || !grant.Verify(s.d.Key.Public(), *g) {
		t.Fatal("new draft authority is wrong", g, revision, err)
	}
	oldFacts, _ := json.Marshal(old.Facts)
	newFacts, _ := json.Marshal(g.Facts)
	if !bytes.Equal(oldFacts, newFacts) || old.DesiredPolicyRef.PolicyID == g.DesiredPolicyRef.PolicyID {
		t.Fatal("source facts or policy namespace changed")
	}
	code, edited := call(t, s, "POST", "/v1/grants/"+newID+"/expiry", token, map[string]any{"schema_version": "grant-expiry-edit/v1", "actor_id": "fixture-operator", "expected_revision": revision, "duration_seconds": 600})
	if code != 200 {
		t.Fatal(code, edited)
	}
	code, replay := call(t, s, "POST", instanceDraftRoute, token, body)
	if code != 200 || replay["reused"] != true || stateRevision(t, replay) != stateRevision(t, edited) {
		t.Fatal("replay reset edited draft", code, replay)
	}
	code, approved := approveChallenged(t, s, newID, "fixture-operator", stateRevision(t, edited))
	if code != 200 {
		t.Fatal("independent approval failed", code, approved)
	}
	code, replay = call(t, s, "POST", instanceDraftRoute, token, body)
	if code != 200 || replay["reused"] != true || stateRevision(t, replay) != stateRevision(t, approved) || replay["grant"].(map[string]any)["status"] != "approved" {
		t.Fatal("replay reset independently approved grant", code, replay)
	}
	old, afterRev, err := store.GetGrantWithSeq(oldID)
	oldAfter, _ := json.Marshal(old)
	admissionAfter, readErr := os.ReadFile(admissionPath)
	if err != nil || readErr != nil || afterRev != oldRev || !bytes.Equal(oldBefore, oldAfter) || !bytes.Equal(admissionBefore, admissionAfter) {
		t.Fatal("original admission or Skill grant changed")
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, event := range events {
		if event.Event == "grant_instance_draft" {
			count++
			if event.Target != newID || event.ActorID != "fixture-operator" || !strings.Contains(event.Note, "instance="+instance) || !strings.Contains(event.Note, "admission="+g.AdmissionID) {
				t.Fatal("missing instance provenance audit", event)
			}
		}
	}
	if count != 1 {
		t.Fatal("duplicate draft audit", count)
	}
}

func TestInstanceDraftHTTPRejectsMalformedNonAdminAndUnavailableSource(t *testing.T) {
	s, store, body := instanceDraftFixture(t)
	req := loopbackRequest("POST", instanceDraftRoute, body)
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("decision token created instance permissions", w.Code)
	}
	good, _ := json.Marshal(body)
	for _, raw := range []string{`{}`, strings.Replace(string(good), `"confirm_instance_scope":true`, `"confirm_instance_scope":false`, 1), strings.Replace(string(good), `"actor_id":"fixture-operator"`, `"actor_id":null`, 1), strings.Replace(string(good), `"actor_id":"fixture-operator"`, `"actor_id":"fixture-operator","actor_id":"other"`, 1), strings.Replace(string(good), `"actor_id"`, `"Actor_ID"`, 1), strings.Replace(string(good), `"actor_id":"fixture-operator"`, `"actor_id":"fixture-operator","subject_id":"forged"`, 1), string(good) + ` {}`, strings.Repeat(" ", 16385)} {
		if code, out := call(t, s, "POST", instanceDraftRoute, token, raw); code != 400 {
			t.Fatal("malformed input accepted", code, out)
		}
	}
	for _, patch := range []map[string]any{{"actor_id": " operator"}, {"actor_id": "operator\x00"}, {"actor_id": strings.Repeat("a", 129)}, {"instance_id": "../escape"}, {"admission_id": "adm-si-" + strings.Repeat("a", 64)}, {"platform": "hermes"}, {"path": "C:/forged"}, {"confirm_instance_scope": "true"}} {
		bad := copyInstanceDraftRequest(body)
		for k, v := range patch {
			bad[k] = v
		}
		if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 400 {
			t.Fatal("unsafe input accepted", code, out)
		}
	}
	bad := copyInstanceDraftRequest(body)
	bad["instance_id"] = "hi-" + strings.Repeat("f", 32)
	if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 409 || out["error"] != "grant_instance_draft_target_unavailable" {
		t.Fatal(code, out)
	}
	bad = copyInstanceDraftRequest(body)
	bad["admission_id"] = "adm-" + strings.Repeat("f", 12)
	if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 404 {
		t.Fatal(code, out)
	}
	code, quarantined := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": filepath.Join("..", "admission", "testdata", "skills", "malicious", "env-webhook")})
	if code != 200 || quarantined["admission"].(map[string]any)["verdict"] != "quarantine" {
		t.Fatal("actual quarantine fixture failed", code, quarantined)
	}
	bad = copyInstanceDraftRequest(body)
	bad["admission_id"] = quarantined["admission"].(map[string]any)["admission_id"]
	if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 409 || out["error"] != "grant_instance_draft_admission_unavailable" {
		t.Fatal("quarantined source authorized", code, out)
	}
	path := filepath.Join(store.Dir, "admissions", body["admission_id"].(string)+".json")
	raw, _ := os.ReadFile(path)
	var tampered map[string]any
	_ = json.Unmarshal(raw, &tampered)
	tampered["signature"] = strings.Repeat("0", 128)
	raw, _ = json.Marshal(tampered)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", instanceDraftRoute, token, body); code != 409 || out["error"] != "grant_instance_draft_admission_unavailable" {
		t.Fatal("bad signature accepted", code, out)
	}
	grants, err := store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("negative input published permissions", err)
	}
}

func TestInstanceDraftHTTPRequestBindingAndAuditFailure(t *testing.T) {
	s, store, body := instanceDraftFixture(t)
	code, original := call(t, s, "POST", instanceDraftRoute, token, body)
	if code != 201 {
		t.Fatal(code, original)
	}
	other := filepath.Join(s.d.Home, ".hermes", "profiles", "other-instance")
	if err := os.MkdirAll(other, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(other, "config.yaml"), []byte("model: fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	_, listed := call(t, s, "GET", "/v1/adapter/instances?platform=hermes", token, nil)
	bad := copyInstanceDraftRequest(body)
	for _, raw := range listed["instances"].([]any) {
		row := raw.(map[string]any)
		if row["name"] == "other-instance" {
			bad["instance_id"] = row["instance_id"]
		}
	}
	if bad["instance_id"] == body["instance_id"] {
		t.Fatal("second fixture undiscovered")
	}
	if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 409 || out["error"] != "grant_instance_draft_request_conflict" {
		t.Fatal("request rebound target", code, out)
	}
	otherSkill := filepath.Join(s.d.Home, "second-admission")
	if err := os.Mkdir(otherSkill, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(otherSkill, "SKILL.md"), []byte("---\nname: second-draft-source\ndescription: Read a local fixture.\nallowed-tools: read_file\n---\nRead only the selected fixture.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	code, otherAdmission := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": otherSkill})
	if code != 200 {
		t.Fatal(code, otherAdmission)
	}
	bad = copyInstanceDraftRequest(body)
	bad["admission_id"] = otherAdmission["admission"].(map[string]any)["admission_id"]
	if code, out := call(t, s, "POST", instanceDraftRoute, token, bad); code != 409 || out["error"] != "grant_instance_draft_request_conflict" {
		t.Fatal("request rebound admission", code, out)
	}
	broken := copyInstanceDraftRequest(body)
	broken["request_id"] = "gid-" + strings.Repeat("b", 32)
	id, err := grant.InstanceDraftID(broken["actor_id"].(string), broken["request_id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(store.Dir, "commit-audit", fmt.Sprintf("%s.0.json", id)), 0700); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", instanceDraftRoute, token, broken); code != 500 || out["error"] != "incomplete_commit" {
		t.Fatal("audit failure not refused", code, out)
	}
	if _, _, err := store.GetGrantWithSeq(id); err == nil {
		t.Fatal("unaudited draft exposed")
	}
	if code, _ := call(t, s, "POST", instanceDraftRoute, token, broken); code < 400 {
		t.Fatal("torn draft reconstructed on retry")
	}
}

func TestInstanceDraftContractSamples(t *testing.T) {
	s, _, body := instanceDraftFixture(t)
	code, out := call(t, s, "POST", instanceDraftRoute, token, body)
	if code != 201 {
		t.Fatal(code, out)
	}
	// Only fixture location and server-generated signing/time fields vary. The
	// preceding test verifies the actual returned target and signature first.
	body["instance_id"] = "hi-" + strings.Repeat("a", 32)
	out["instance_id"] = body["instance_id"]
	g := out["grant"].(map[string]any)
	g["subject"].(map[string]any)["id"] = "hri-" + strings.Repeat("a", 32)
	g["created_at"] = "2026-09-18T00:00:00Z"
	g["signature"] = strings.Repeat("0", 128)
	for name, value := range map[string]any{"grant-instance-draft-create.json": body, "grant-instance-draft-created.json": out} {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0644); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("instance draft contract drift", name, err)
		}
	}
}

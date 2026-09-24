package server

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestTaskActivitySecurityViewIsEvidenceBoundAndRedacted(t *testing.T) {
	s, _ := newServer(t, "block")
	contract := apiIntent()
	contract.Purpose = "PRIVATE BUSINESS PURPOSE MUST NOT ENTER SECURITY VIEW"
	issued, err := s.intents.Issue(contract)
	if err != nil {
		t.Fatal(err)
	}
	agent, grant, sandbox, model := issued.Agent.ID, "grant-safe-ref", "sandbox-private-id", "nemotron-local-governed"
	private := "PRIVATE PARAMETER AND DESTINATION"
	base := receipt.Receipt{
		Platform: issued.Agent.Platform, SessionID: "security-view-session", AgentID: &agent,
		TaskID: issued.TaskID, IntentID: issued.IntentID, IntentDigest: issued.Digest,
		AuthorityRevision: issued.Authority.Revision, IntentBinding: "bound", AuthorityStatus: "valid",
		EnforcementMode: "block", SandboxID: &sandbox, ModelKey: &model, MatchedGrantID: &grant, ParamsExcerpt: &private,
	}
	allowed := base
	allowed.ReceiptID, allowed.ActionID, allowed.Action, allowed.EffectiveAction = "security-allow", "action-allow", receipt.ActionAllow, receipt.ActionAllow
	allowed.Tool, allowed.Operation, allowed.Effects = "web_fetch", "request", []string{"network.request"}
	allowed.ResourceRefs = []runtimeaction.ResourceRef{{Domain: "network", Digest: strings.Repeat("a", 64)}}
	if err := s.d.Chain.Append(&allowed); err != nil {
		t.Fatal(err)
	}
	denied := base
	denied.ReceiptID, denied.ActionID, denied.Action, denied.EffectiveAction = "security-deny", "action-deny", receipt.ActionDeny, receipt.ActionDeny
	denied.Tool, denied.Operation, denied.Effects = "write_file", "write", []string{"file.write"}
	denied.MatchedGrantID = nil
	if err := s.d.Chain.Append(&denied); err != nil {
		t.Fatal(err)
	}
	list := effectCall(t, s, "GET", "/v1/task-activities", s.bootAdmin, nil, 200)
	item := list["items"].([]any)[0].(map[string]any)
	id, snapshot := item["activity_id"].(string), list["snapshot"].(string)
	route := "/v1/task-activities/" + id + "/security-view?view=tasks&snapshot=" + snapshot
	request := func(method, path, credential string) *httptest.ResponseRecorder {
		t.Helper()
		req := loopbackRequest(method, path, nil)
		if credential != "" {
			req.Header.Set("Authorization", "Bearer "+credential)
		}
		out := httptest.NewRecorder()
		s.Handler().ServeHTTP(out, req)
		return out
	}
	out := request("GET", route, s.bootAdmin)
	if out.Code != 200 || out.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("security view unavailable", out.Code, out.Body.String())
	}
	for _, secret := range []string{private, contract.Purpose, sandbox} {
		if bytes.Contains(out.Body.Bytes(), []byte(secret)) {
			t.Fatalf("security view leaked %q", secret)
		}
	}
	var view taskSecurityView
	if err := json.Unmarshal(out.Body.Bytes(), &view); err != nil {
		t.Fatal(err)
	}
	if view.BusinessObject.Status != "verified" || view.BusinessObject.Contract != "verified" || view.BusinessObject.TaskID == nil || *view.BusinessObject.TaskID != issued.TaskID || view.BusinessObject.DisplayLabel != "unavailable" {
		t.Fatalf("business object was invented or lost: %+v", view.BusinessObject)
	}
	if view.RunMode.Platform == nil || *view.RunMode.Platform != "hermes" || view.RunMode.ModeStatus != "consistent" || len(view.RunMode.EnforcementModes) != 1 || view.RunMode.EnforcementModes[0] != "block" || view.RunMode.ModelStatus != "consistent" || len(view.RunMode.ModelKeys) != 1 || view.RunMode.ModelKeys[0] != model || view.RunMode.ExecutionContext != "sandbox_bound" || view.RunMode.SandboxBoundCount != 2 {
		t.Fatalf("wrong run mode: %+v", view.RunMode)
	}
	if view.DataDestinations.Status != "partial" || view.DataDestinations.PlaintextExposed || view.DataDestinations.UnresolvedReceiptCount != 1 || len(view.DataDestinations.Destinations) != 1 || view.DataDestinations.Destinations[0].Domain != "network" || view.DataDestinations.Destinations[0].ResourceRef != strings.Repeat("a", 64) {
		t.Fatalf("wrong destination summary: %+v", view.DataDestinations)
	}
	if view.Authorization.Status != "mixed" || view.Authorization.Decisions.Authorized != 1 || view.Authorization.Decisions.Denied != 1 || view.Authorization.Decisions.Pending != 0 || view.Authorization.Decisions.Unknown != 0 || view.Authorization.MatchedGrantCount != 1 {
		t.Fatalf("wrong authorization summary: %+v", view.Authorization)
	}
	if view.ActualResult.Status != "unknown" || view.ActualResult.EvaluationStatus != "evaluated" || view.ActualResult.ReasonCode != "not_required" || view.ActualResult.Result == nil {
		t.Fatalf("authorization was confused with effect completion: %+v", view.ActualResult)
	}
	if view.ReleaseAssurance.Status != "not_evaluated" || view.EvidenceIntegrity.PrefixValid != true {
		t.Fatalf("release or evidence state was overstated: %+v %+v", view.ReleaseAssurance, view.EvidenceIntegrity)
	}

	// Normalize observation time for the shared Go/TypeScript response fixture.
	view.EvaluatedAt = "2026-09-21T00:00:00Z"
	raw, _ := json.MarshalIndent(view, "", "  ")
	raw = append(raw, '\n')
	fixture := filepath.Join("..", "..", "testdata", "contracts", "local-task-security-view.json")
	if os.Getenv("SIQ_UPDATE_ACTIVITY_FIXTURES") == "1" {
		if err := os.WriteFile(fixture, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(fixture)
	if err != nil || !bytes.Equal(raw, want) {
		t.Fatal("fixture differs", err)
	}

	for _, tc := range []struct {
		method, path, credential string
		code                     int
	}{
		{"GET", route, "", 401}, {"GET", route, token, 403}, {"POST", route, s.bootAdmin, 405},
		{"GET", strings.Split(route, "?")[0], s.bootAdmin, 400},
		{"GET", route + "&offset=0", s.bootAdmin, 400},
		{"GET", strings.Split(route, "?")[0] + "?view=tasks&snapshot=" + strings.Repeat("0", 64), s.bootAdmin, 409},
		{"GET", "/v1/task-activities/" + strings.Repeat("0", 64) + "/security-view?view=tasks&snapshot=" + snapshot, s.bootAdmin, 404},
	} {
		if got := request(tc.method, tc.path, tc.credential); got.Code != tc.code {
			t.Fatalf("%s: got %d, want %d: %s", tc.path, got.Code, tc.code, got.Body.String())
		}
	}
}

func TestTaskActivitySecurityViewKeepsUnassignedStateUnknown(t *testing.T) {
	s, _ := newServer(t, "block")
	agent := "unknown-agent"
	rc := receipt.Receipt{ReceiptID: "unknown-security", Platform: "openclaw", SessionID: "unknown-session", AgentID: &agent, IntentBinding: "unbound", Action: receipt.ActionAllow, EffectiveAction: receipt.ActionAllow, EnforcementMode: "warn"}
	if err := s.d.Chain.Append(&rc); err != nil {
		t.Fatal(err)
	}
	list := effectCall(t, s, "GET", "/v1/task-activities?view=unassigned", s.bootAdmin, nil, 200)
	id := list["items"].([]any)[0].(map[string]any)["activity_id"].(string)
	out := effectCall(t, s, "GET", "/v1/task-activities/"+id+"/security-view?view=unassigned&snapshot="+list["snapshot"].(string), s.bootAdmin, nil, 200)
	if out["business_object"].(map[string]any)["status"] != "unknown" || out["actual_result"].(map[string]any)["status"] != "unknown" || out["authorization"].(map[string]any)["status"] != "unknown" {
		t.Fatal("unassigned receipt was upgraded", out)
	}
}

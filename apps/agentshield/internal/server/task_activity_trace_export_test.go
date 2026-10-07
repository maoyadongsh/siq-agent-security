package server

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	exportpkg "siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestTaskActivityTraceExport(t *testing.T) {
	s, st := newServer(t, "block")
	seedRawExportSentinel(t, st.Dir)
	contract, err := s.intents.Issue(apiIntent())
	if err != nil {
		t.Fatal(err)
	}
	sign := func(value any) string {
		t.Helper()
		raw, _ := json.Marshal(value)
		decoded, err := canon.Decode(raw)
		if err != nil {
			t.Fatal(err)
		}
		doc := decoded.(map[string]any)
		delete(doc, "signature")
		signature, err := s.d.Key.SignCanonical(doc)
		if err != nil {
			t.Fatal(err)
		}
		return signature
	}
	private := "PRIVATE_TRACE_SOURCE"
	version := "PRIVATE_TRACE_VERSION"
	a := admission.Admission{AdmissionID: "adm-trace", SkillName: private, SkillVersion: &version, ContentHash: strings.Repeat("a", 64), Verdict: "admit", SigningSchema: "local_canonical/v1"}
	a.Signature = sign(a)
	if err := st.PutAdmission(&admission.Result{Admission: a}); err != nil {
		t.Fatal(err)
	}
	g := grant.Grant{GrantID: "grt-trace", AdmissionID: a.AdmissionID, Platform: contract.Agent.Platform, Subject: grant.Subject{Type: "agent_instance", ID: contract.Agent.ID}, Status: "deployed", CreatedAt: "2026-01-01T00:00:00Z", SigningSchema: "local_canonical/v1"}
	g.Signature = sign(g)
	if err := st.PutGrant(g); err != nil {
		t.Fatal(err)
	}
	_, revision, err := st.GetGrantWithSeq(g.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	binding, err := s.intents.BindWithGrant(intent.Binding{Platform: contract.Agent.Platform, SessionID: "trace-session", AgentID: contract.Agent.ID, IntentID: contract.IntentID}, g.GrantID, revision)
	if err != nil {
		t.Fatal(err)
	}
	privateReceipt, privateTool := "PRIVATE_TRACE_RECEIPT", "PRIVATE_TRACE_TOOL"
	rc := receipt.Receipt{
		ReceiptID: privateReceipt, Tool: privateTool, Reason: private, Platform: binding.Platform, SessionID: binding.SessionID,
		AgentID: &binding.AgentID, TaskID: binding.TaskID, IntentID: binding.IntentID, IntentDigest: binding.IntentDigest,
		AuthorityRevision: binding.AuthorityRevision, IntentBinding: "bound", MatchedGrantID: &g.GrantID, Action: "allow",
	}
	if err := s.d.Chain.Append(&rc); err != nil {
		t.Fatal(err)
	}
	list := effectCall(t, s, "GET", "/v1/task-activities", s.bootAdmin, nil, 200)
	id := list["items"].([]any)[0].(map[string]any)["activity_id"].(string)
	route := "/v1/task-activities/" + id + "/trace-export"
	url := route + "?snapshot=" + list["snapshot"].(string)
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
	out := request("GET", url, s.bootAdmin)
	if out.Code != 200 || out.Header().Get("Cache-Control") != "no-store" || !strings.HasPrefix(out.Header().Get("Content-Disposition"), "attachment;") {
		t.Fatal("trace unavailable", out.Code, out.Body.String())
	}
	for _, secret := range []string{private, version, privateReceipt, privateTool, contract.TaskID, g.GrantID, a.AdmissionID} {
		if bytes.Contains(out.Body.Bytes(), []byte(secret)) {
			t.Fatalf("trace leaked %q", secret)
		}
	}
	if bytes.Contains(out.Body.Bytes(), []byte(rawExportSentinel)) || bytes.Contains(out.Body.Bytes(), []byte("raw-task-content")) {
		t.Fatal("raw content store entered default trace export")
	}
	var doc exportpkg.TraceDocument
	if err := json.Unmarshal(out.Body.Bytes(), &doc); err != nil || exportpkg.VerifyTrace(s.d.Key.Public(), doc) != nil {
		t.Fatal("trace signature invalid", err)
	}
	if len(doc.Receipts) != 1 || len(doc.Sources) != 1 || doc.Sources[0].Source == nil || doc.Sources[0].Status != "verified_source" || doc.Completion.Status != "unknown" || !doc.Incomplete || len(doc.Effects) != 0 {
		t.Fatalf("wrong trace projection: %+v", doc)
	}
	// A legacy source exists above, but must not be re-used as native Skill
	// attribution: the Intent pins the baseline, not the invoked Skill ancestry.
	for _, sample := range []string{"native-receipt-with-skill-v3.sample.json", "native-receipt-no-skill-v3.sample.json"} {
		raw, err := os.ReadFile("../../testdata/contracts/" + sample)
		var native receipt.Receipt
		if err != nil || json.Unmarshal(raw, &native) != nil {
			t.Fatal("native fixture", err)
		}
		for _, kind := range []string{"complete", "missing-proof", "missing-version"} {
			input := rc
			input.SchemaVersion, input.NativeInvocation = native.SchemaVersion, native.NativeInvocation
			if kind == "missing-proof" {
				input.NativeInvocation = nil
			}
			if kind == "missing-version" {
				input.SchemaVersion = ""
			}
			rows, code := s.traceSources([]receipt.Receipt{input}, []int{0})
			if code != "" || len(rows) != 1 || rows[0].Status != "unavailable" || rows[0].Source != nil || rows[0].ReceiptHash != rc.Hash {
				t.Fatal("legacy admission misattributed as native Skill source", sample, kind)
			}
		}
	}
	if err := os.Remove(filepath.Join(st.Dir, "admissions", a.AdmissionID+".json")); err != nil {
		t.Fatal(err)
	}
	missing := request("GET", url, s.bootAdmin)
	if missing.Code != 200 {
		t.Fatal("missing source hidden", missing.Code, missing.Body.String())
	}
	var missingDoc exportpkg.TraceDocument
	if err := json.Unmarshal(missing.Body.Bytes(), &missingDoc); err != nil || missingDoc.Sources[0].Status != "unavailable" || missingDoc.Sources[0].Source != nil || !missingDoc.Incomplete {
		t.Fatal("missing source invented", err)
	}
	for _, tc := range []struct {
		method, path, credential string
		code                     int
	}{
		{"GET", url, "", 401}, {"GET", url, token, 403}, {"POST", url, s.bootAdmin, 405},
		{"GET", route, s.bootAdmin, 400}, {"GET", url + "&offset=0", s.bootAdmin, 400},
		{"GET", url + "&view=unassigned", s.bootAdmin, 400},
		{"GET", route + "?snapshot=" + strings.Repeat("0", 64), s.bootAdmin, 409},
		{"GET", "/v1/task-activities/" + strings.Repeat("0", 64) + "/trace-export?snapshot=" + list["snapshot"].(string), s.bootAdmin, 404},
	} {
		if got := request(tc.method, tc.path, tc.credential); got.Code != tc.code {
			t.Fatalf("%s: got %d, want %d", tc.path, got.Code, tc.code)
		}
	}
	rc.ReceiptID = "trace-new"
	if err := s.d.Chain.Append(&rc); err != nil {
		t.Fatal(err)
	}
	if stale := request("GET", url, s.bootAdmin); stale.Code != 409 || stale.Header().Get("Content-Disposition") != "" {
		t.Fatal("stale trace downloaded", stale.Code, stale.Body.String())
	}
}

func TestTaskActivityTraceSourceBudget(t *testing.T) {
	s, _ := newServer(t, "block")
	contract, err := s.intents.Issue(apiIntent())
	if err != nil {
		t.Fatal(err)
	}
	binding, err := s.intents.Bind(intent.Binding{Platform: contract.Agent.Platform, SessionID: "budget-session", AgentID: contract.Agent.ID, IntentID: contract.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < taskTraceSourceLimit+1; i++ {
		grantID := "trace-budget-" + string(rune('a'+i))
		rc := receipt.Receipt{ReceiptID: grantID, Platform: binding.Platform, SessionID: binding.SessionID, AgentID: &binding.AgentID, TaskID: binding.TaskID, IntentID: binding.IntentID, IntentDigest: binding.IntentDigest, AuthorityRevision: binding.AuthorityRevision, IntentBinding: "bound", MatchedGrantID: &grantID}
		if err := s.d.Chain.Append(&rc); err != nil {
			t.Fatal(err)
		}
	}
	list := effectCall(t, s, "GET", "/v1/task-activities", s.bootAdmin, nil, 200)
	id := list["items"].([]any)[0].(map[string]any)["activity_id"].(string)
	effectCall(t, s, "GET", "/v1/task-activities/"+id+"/trace-export?snapshot="+list["snapshot"].(string), s.bootAdmin, nil, 413)
}

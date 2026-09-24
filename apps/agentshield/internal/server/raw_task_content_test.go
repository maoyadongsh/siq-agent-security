package server

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/rawcontent"
)

func copyRawMap(source map[string]any) map[string]any {
	out := make(map[string]any, len(source))
	for key, value := range source {
		out[key] = value
	}
	return out
}

func TestRawTaskContentActivationRequiresAdminAndExplicitRequest(t *testing.T) {
	s, stateStore := newServer(t, "block")
	statusPath := "/v1/raw-task-content/status"
	activationPath := "/v1/raw-task-content/activation"
	for _, path := range []string{statusPath, activationPath} {
		method := http.MethodGet
		if path == activationPath {
			method = http.MethodPost
		}
		if w := sessionRequest(t, s, method, path, nil, "", nil, nil); w.Code != http.StatusUnauthorized {
			t.Fatal("missing admin credential", path, w.Code)
		}
		if w := sessionRequest(t, s, method, path, nil, token, nil, nil); w.Code != http.StatusForbidden {
			t.Fatal("decision credential reached raw-content management", path, w.Code)
		}
	}
	w := sessionRequest(t, s, http.MethodGet, statusPath, nil, s.bootAdmin, nil, nil)
	body := sessionBody(t, w)
	if w.Code != http.StatusOK || body["schema_version"] != "local-raw-task-content-status/v1" || body["status"] != "disabled" || body["default_capture"] != false || body["retention_seconds"] != nil || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("wrong disabled status", w.Code, body)
	}
	for _, path := range []string{
		filepath.Join(stateStore.Dir, "keys", "raw-content.key"),
		filepath.Join(stateStore.Dir, "raw-task-content"),
		filepath.Join(stateStore.Dir, "raw-task-content-authority"),
	} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatal("status read initialized raw content", path, err)
		}
	}
}

func TestRawTaskContentActivationStrictLifecycle(t *testing.T) {
	s, stateStore := newServer(t, "block")
	path := "/v1/raw-task-content/activation"
	valid := `{"schema_version":"local-raw-task-content-activate/v1","actor_id":"PRIVATE_OPERATOR","retention_seconds":86400,"budget_bytes":67108864}`
	for _, body := range []string{
		`{}`,
		`{"schema_version":"local-raw-task-content-activate/v1","actor_id":null,"retention_seconds":86400,"budget_bytes":67108864}`,
		`{"schema_version":"local-raw-task-content-activate/v1","actor_id":"operator","retention_seconds":3599,"budget_bytes":67108864}`,
		`{"schema_version":"local-raw-task-content-activate/v1","actor_id":"operator","retention_seconds":86400,"budget_bytes":1048575}`,
		`{"schema_version":"local-raw-task-content-activate/v1","actor_id":"operator","actor_id":"duplicate","retention_seconds":86400,"budget_bytes":67108864}`,
		strings.TrimSuffix(valid, "}") + `,"capture_by_default":true}`,
		valid + `{}`,
	} {
		w := sessionRequest(t, s, http.MethodPost, path, body, s.bootAdmin, nil, nil)
		if w.Code != http.StatusBadRequest || sessionBody(t, w)["error"] != "raw_task_content_invalid_request" {
			t.Fatal("invalid activation accepted", w.Code, w.Body.String())
		}
	}
	if _, err := os.Stat(filepath.Join(stateStore.Dir, "keys", "raw-content.key")); !os.IsNotExist(err) {
		t.Fatal("invalid request initialized encryption state", err)
	}
	w := sessionRequest(t, s, http.MethodPost, path, valid, s.bootAdmin, nil, nil)
	activation := sessionBody(t, w)
	if w.Code != http.StatusCreated || activation["schema_version"] != "local-raw-task-content-activation/v1" || activation["enabled"] != true || activation["retention_seconds"] != float64(86400) || activation["budget_bytes"] != float64(67108864) {
		t.Fatal("activation failed", w.Code, activation)
	}
	if activation["actor_ref"] == "PRIVATE_OPERATOR" || len(activation["signature"].(string)) != 128 {
		t.Fatal("activation exposed actor or lacks signature", activation)
	}
	raw, err := os.ReadFile(filepath.Join(stateStore.Dir, "raw-task-content-authority", "activation.json"))
	if err != nil || bytes.Contains(raw, []byte("PRIVATE_OPERATOR")) {
		t.Fatal("activation leaked raw operator", err)
	}
	w = sessionRequest(t, s, http.MethodGet, path, nil, s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK || sessionBody(t, w)["signature"] != activation["signature"] {
		t.Fatal("activation read changed signed record", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodGet, "/v1/raw-task-content/status", nil, s.bootAdmin, nil, nil)
	status := sessionBody(t, w)
	if w.Code != http.StatusOK || status["status"] != "ready" || status["default_capture"] != false || status["activated_at"] != activation["activated_at"] {
		t.Fatal("ready status", w.Code, status)
	}
	w = sessionRequest(t, s, http.MethodPost, path, strings.Replace(valid, "PRIVATE_OPERATOR", "RETRY_OPERATOR", 1), s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK || sessionBody(t, w)["signature"] != activation["signature"] {
		t.Fatal("idempotent activation replaced record", w.Code, w.Body.String())
	}
	conflict := strings.Replace(valid, `"retention_seconds":86400`, `"retention_seconds":7200`, 1)
	w = sessionRequest(t, s, http.MethodPost, path, conflict, s.bootAdmin, nil, nil)
	if w.Code != http.StatusConflict || sessionBody(t, w)["error"] != "raw_task_content_activation_conflict" {
		t.Fatal("limit conflict accepted", w.Code, w.Body.String())
	}
	if w := sessionRequest(t, s, http.MethodDelete, path, nil, s.bootAdmin, nil, nil); w.Code != http.StatusMethodNotAllowed {
		t.Fatal("unexpected method accepted", w.Code)
	}
}

func TestRawTaskContentActivationTamperIsVisibleAndNotOverwritten(t *testing.T) {
	s, stateStore := newServer(t, "block")
	path := "/v1/raw-task-content/activation"
	request := map[string]any{
		"schema_version": "local-raw-task-content-activate/v1",
		"actor_id":       "operator", "retention_seconds": 86400, "budget_bytes": 67108864,
	}
	if w := sessionRequest(t, s, http.MethodPost, path, request, s.bootAdmin, nil, nil); w.Code != http.StatusCreated {
		t.Fatal(w.Code, w.Body.String())
	}
	recordPath := filepath.Join(stateStore.Dir, "raw-task-content-authority", "activation.json")
	raw, _ := os.ReadFile(recordPath)
	var document map[string]any
	_ = json.Unmarshal(raw, &document)
	document["budget_bytes"] = float64(2 << 20)
	tampered, _ := json.Marshal(document)
	if err := os.WriteFile(recordPath, tampered, 0600); err != nil {
		t.Fatal(err)
	}
	w := sessionRequest(t, s, http.MethodGet, "/v1/raw-task-content/status", nil, s.bootAdmin, nil, nil)
	status := sessionBody(t, w)
	if w.Code != http.StatusOK || status["status"] != "error" || status["retention_seconds"] != nil || status["budget_bytes"] != nil {
		t.Fatal("tamper not visible in status", w.Code, status)
	}
	if w := sessionRequest(t, s, http.MethodGet, path, nil, s.bootAdmin, nil, nil); w.Code != http.StatusServiceUnavailable {
		t.Fatal("tampered activation returned", w.Code, w.Body.String())
	}
	if w := sessionRequest(t, s, http.MethodPost, path, request, s.bootAdmin, nil, nil); w.Code != http.StatusServiceUnavailable {
		t.Fatal("tampered activation overwritten", w.Code, w.Body.String())
	}
	after, _ := os.ReadFile(recordPath)
	if !bytes.Equal(after, tampered) {
		t.Fatal("tampered authority was silently replaced")
	}
}

func TestRawTaskContentHTTPContractFixtures(t *testing.T) {
	retention, budget, activatedAt := 86400, int64(67108864), "2026-09-13T02:30:00Z"
	permitRaw, err := os.ReadFile(filepath.Join("../../testdata/contracts", "local-raw-task-content-capture-permit.json"))
	if err != nil {
		t.Fatal(err)
	}
	var permit map[string]any
	if err := json.Unmarshal(permitRaw, &permit); err != nil {
		t.Fatal(err)
	}
	values := map[string]any{
		"local-raw-task-content-activate.json": rawTaskContentActivateRequest{
			SchemaVersion: "local-raw-task-content-activate/v1", ActorID: "fixture-operator",
			RetentionSeconds: retention, BudgetBytes: budget,
		},
		"local-raw-task-content-status.json": rawTaskContentStatus{
			SchemaVersion: "local-raw-task-content-status/v1", Status: "ready", DefaultCapture: false,
			RetentionSeconds: &retention, BudgetBytes: &budget, ActivatedAt: &activatedAt,
		},
		"local-raw-task-content-grant-create.json": rawTaskContentGrantCreateRequest{
			SchemaVersion: "local-raw-task-content-grant-create/v1", TaskID: "fixture-task",
			Kinds: []string{"input", "output"}, ActorID: "fixture-operator", DurationSeconds: 3600,
			RetentionSeconds: 7200, MaxPlaintextBytes: 4096,
		},
		"local-raw-task-content-revoke.json": rawTaskContentRevokeRequest{
			SchemaVersion:          "local-raw-task-content-revoke/v1",
			ExpectedGrantSignature: "a15068fd82bfca732d8c2690084850d9176d05a2a587609cb604996adebfee9e50cfdbd2ceb22eb708e1e581b04352e2a55f082ea9cbe546da6377b38d7f9f09",
			ActorID:                "fixture-revoker",
		},
		"local-raw-task-content-capture-permit-create.json": rawTaskContentCapturePermitRequest{
			SchemaVersion: "local-raw-task-content-capture-permit-create/v1", Platform: "hermes",
			AgentID: "hri-" + strings.Repeat("1", 32), SessionID: "fixture-session", TaskID: "fixture-runtime-task",
			GrantID: permit["grant_id"].(string), ExpectedGrantSignature: permit["expected_grant_signature"].(string), Kind: "input", TTLSeconds: 60,
		},
		"local-raw-task-content-capture.json": rawTaskContentCaptureRequest{
			SchemaVersion: "local-raw-task-content-capture/v1", Platform: "hermes", AgentID: "hri-" + strings.Repeat("1", 32),
			SessionID: "fixture-session", TaskID: "fixture-runtime-task",
			Permit: func() rawcontent.CapturePermit {
				var typed rawcontent.CapturePermit
				if err := json.Unmarshal(permitRaw, &typed); err != nil {
					t.Fatal(err)
				}
				return typed
			}(),
			Fields: []rawcontent.Field{{Path: "/prompt", Value: "fixture prompt", Secret: false}},
		},
		"local-raw-task-content-native-capture.json": rawTaskContentNativeCaptureRequest{
			SchemaVersion: "local-raw-task-content-native-capture/v1", Platform: "hermes",
			AgentID: "hri-" + strings.Repeat("1", 32), SessionID: "fixture-session", Kind: "parameters",
			Fields: []rawcontent.Field{{Path: "/tool/arguments", Value: `{"path":"report.md"}`, Secret: false}},
		},
		"local-raw-task-content-capture-result.json": rawTaskContentCaptureResult{
			SchemaVersion: "local-raw-task-content-capture-result/v1", RecordID: "raw-" + strings.Repeat("c", 32),
			TaskRef: permit["task_ref"].(string), Kind: "input", CreatedAt: "2026-09-13T13:00:05Z", ExpiresAt: "2026-09-13T14:00:05Z",
			PlaintextHash: strings.Repeat("d", 64), PlaintextSize: 96, OmittedCount: 0,
		},
		"local-raw-task-content-record-list.json": rawTaskContentRecordListRequest{
			SchemaVersion: "local-raw-task-content-record-list/v1", TaskID: "fixture-runtime-task",
		},
		"local-raw-task-content-records.json": map[string]any{
			"schema_version": "local-raw-task-content-records/v1",
			"items": []rawcontent.Metadata{{
				SchemaVersion: "local-raw-task-content-record/v1", Status: "active", RecordID: "raw-" + strings.Repeat("c", 32),
				TaskRef: permit["task_ref"].(string), Kind: "input", CreatedAt: "2026-09-13T13:00:05Z", ExpiresAt: "2026-09-13T14:00:05Z",
				PlaintextHash: strings.Repeat("d", 64), PlaintextSize: 96, OmittedCount: 0,
			}},
		},
		"local-raw-task-content-record-read.json": rawTaskContentRecordListRequest{
			SchemaVersion: "local-raw-task-content-record-read/v1", TaskID: "fixture-runtime-task",
		},
		"local-raw-task-content-record-content.json": rawTaskContentRecordContent{
			SchemaVersion: "local-raw-task-content-record-content/v1", ContainsPlaintext: true,
			Record: rawcontent.Metadata{
				SchemaVersion: "local-raw-task-content-record/v1", Status: "active", RecordID: "raw-" + strings.Repeat("c", 32),
				TaskRef: permit["task_ref"].(string), Kind: "input", CreatedAt: "2026-09-13T13:00:05Z", ExpiresAt: "2026-09-13T14:00:05Z",
				PlaintextHash: strings.Repeat("d", 64), PlaintextSize: 96, OmittedCount: 0,
			},
			Fields: []rawTaskContentPlainField{{Path: "/prompt", Value: "fixture prompt"}},
		},
		"local-raw-task-content-record-delete.json": rawTaskContentRecordDeleteRequest{
			SchemaVersion: "local-raw-task-content-record-delete/v1", TaskID: "fixture-runtime-task", ConfirmRecordID: "raw-" + strings.Repeat("c", 32),
		},
		"local-raw-task-content-record-deleted.json": map[string]any{
			"schema_version": "local-raw-task-content-record-deleted/v1", "record_id": "raw-" + strings.Repeat("c", 32), "deleted": true,
		},
		"local-raw-task-content-purge-expired.json": rawTaskContentPurgeRequest{
			SchemaVersion: "local-raw-task-content-purge-expired/v1", ConfirmExpiredOnly: true,
		},
		"local-raw-task-content-purge-result.json": map[string]any{
			"schema_version": "local-raw-task-content-purge-result/v1", "deleted_records": 2, "released_bytes": 4096,
		},
	}
	for name, value := range values {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		want, err := os.ReadFile(filepath.Join("../../testdata/contracts", name))
		if err != nil || !bytes.Equal(raw, want) {
			t.Fatalf("%s fixture differs: %v\n%s", name, err, raw)
		}
	}
}

func activateRawTaskContent(t *testing.T, s *Server) map[string]any {
	t.Helper()
	w := sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/activation", map[string]any{
		"schema_version": "local-raw-task-content-activate/v1",
		"actor_id":       "operator", "retention_seconds": 86400, "budget_bytes": 67108864,
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusCreated {
		t.Fatal("activation", w.Code, w.Body.String())
	}
	return sessionBody(t, w)
}

func TestRawTaskContentGrantManagementLifecycle(t *testing.T) {
	s, stateStore := newServer(t, "block")
	collection := "/v1/raw-task-content/grants"
	create := map[string]any{
		"schema_version": "local-raw-task-content-grant-create/v1",
		"task_id":        "PRIVATE_TASK", "kinds": []string{"output", "input"}, "actor_id": "PRIVATE_ISSUER",
		"duration_seconds": 3600, "retention_seconds": 7200, "max_plaintext_bytes": 4096,
	}
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		if w := sessionRequest(t, s, method, collection, create, s.bootAdmin, nil, nil); w.Code != http.StatusConflict || sessionBody(t, w)["error"] != "raw_task_content_disabled" {
			t.Fatal("disabled authority accepted", method, w.Code, w.Body.String())
		}
	}
	activateRawTaskContent(t, s)
	for _, path := range []string{collection, collection + "/rawgrant-" + strings.Repeat("0", 32)} {
		method := http.MethodGet
		if path == collection {
			method = http.MethodPost
		}
		if w := sessionRequest(t, s, method, path, create, "", nil, nil); w.Code != http.StatusUnauthorized {
			t.Fatal("missing admin session", path, w.Code)
		}
		if w := sessionRequest(t, s, method, path, create, token, nil, nil); w.Code != http.StatusForbidden {
			t.Fatal("decision credential reached raw authority", path, w.Code)
		}
	}
	w := sessionRequest(t, s, http.MethodPost, collection, create, s.bootAdmin, nil, nil)
	grant := sessionBody(t, w)
	if w.Code != http.StatusCreated || grant["schema_version"] != "local-raw-task-content-grant/v1" || grant["task_ref"] == "PRIVATE_TASK" || grant["actor_ref"] == "PRIVATE_ISSUER" {
		t.Fatal("grant create", w.Code, grant)
	}
	kinds := grant["kinds"].([]any)
	if len(kinds) != 2 || kinds[0] != "input" || kinds[1] != "output" || len(grant["signature"].(string)) != 128 {
		t.Fatal("grant not normalized or signed", grant)
	}
	id := grant["grant_id"].(string)
	item := collection + "/" + id
	w = sessionRequest(t, s, http.MethodGet, item, nil, s.bootAdmin, nil, nil)
	view := sessionBody(t, w)
	if w.Code != http.StatusOK || view["schema_version"] != "local-raw-task-content-grant-view/v1" || view["status"] != "active" || view["revocation"] != nil || view["grant"].(map[string]any)["signature"] != grant["signature"] {
		t.Fatal("active grant view", w.Code, view)
	}
	w = sessionRequest(t, s, http.MethodGet, collection, nil, s.bootAdmin, nil, nil)
	list := sessionBody(t, w)
	items := list["items"].([]any)
	if w.Code != http.StatusOK || list["schema_version"] != "local-raw-task-content-grants/v1" || len(items) != 1 || items[0].(map[string]any)["status"] != "active" {
		t.Fatal("grant list", w.Code, list)
	}
	wrong := map[string]any{
		"schema_version":           "local-raw-task-content-revoke/v1",
		"expected_grant_signature": strings.Repeat("0", 128), "actor_id": "PRIVATE_REVOKER",
	}
	w = sessionRequest(t, s, http.MethodPost, item+"/revoke", wrong, s.bootAdmin, nil, nil)
	if w.Code != http.StatusConflict || sessionBody(t, w)["error"] != "raw_task_content_authority_conflict" {
		t.Fatal("wrong revoke precondition accepted", w.Code, w.Body.String())
	}
	validRevokeJSON := `{"schema_version":"local-raw-task-content-revoke/v1","expected_grant_signature":"` + grant["signature"].(string) + `","actor_id":"PRIVATE_REVOKER"}`
	for _, body := range []string{
		`{}`,
		strings.Replace(validRevokeJSON, `"actor_id":"PRIVATE_REVOKER"`, `"actor_id":null`, 1),
		strings.TrimSuffix(validRevokeJSON, "}") + `,"task_id":"PRIVATE_TASK"}`,
		validRevokeJSON + `{}`,
	} {
		w = sessionRequest(t, s, http.MethodPost, item+"/revoke", body, s.bootAdmin, nil, nil)
		if w.Code != http.StatusBadRequest || sessionBody(t, w)["error"] != "raw_task_content_invalid_request" {
			t.Fatal("invalid revoke accepted", w.Code, w.Body.String())
		}
	}
	revoke := map[string]any{
		"schema_version":           "local-raw-task-content-revoke/v1",
		"expected_grant_signature": grant["signature"], "actor_id": "PRIVATE_REVOKER",
	}
	w = sessionRequest(t, s, http.MethodPost, item+"/revoke", revoke, s.bootAdmin, nil, nil)
	revocation := sessionBody(t, w)
	if w.Code != http.StatusOK || revocation["schema_version"] != "local-raw-task-content-revocation/v1" || revocation["expected_grant_signature"] != grant["signature"] || revocation["actor_ref"] == "PRIVATE_REVOKER" {
		t.Fatal("grant revoke", w.Code, revocation)
	}
	w = sessionRequest(t, s, http.MethodPost, item+"/revoke", map[string]any{
		"schema_version":           "local-raw-task-content-revoke/v1",
		"expected_grant_signature": grant["signature"], "actor_id": "retry-operator",
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK || sessionBody(t, w)["signature"] != revocation["signature"] {
		t.Fatal("revoke retry replaced tombstone", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodGet, item, nil, s.bootAdmin, nil, nil)
	view = sessionBody(t, w)
	if w.Code != http.StatusOK || view["status"] != "revoked" || view["revocation"].(map[string]any)["signature"] != revocation["signature"] {
		t.Fatal("revoked grant view", w.Code, view)
	}
	for _, filename := range []string{id + ".grant.json", id + ".revocation.json"} {
		raw, err := os.ReadFile(filepath.Join(stateStore.Dir, "raw-task-content-authority", filename))
		if err != nil {
			t.Fatal(err)
		}
		for _, private := range []string{"PRIVATE_TASK", "PRIVATE_ISSUER", "PRIVATE_REVOKER"} {
			if bytes.Contains(raw, []byte(private)) {
				t.Fatal("authority record leaked raw identifier", filename, private)
			}
		}
	}
}

func TestRawTaskContentGrantManagementRejectsInvalidShapes(t *testing.T) {
	s, _ := newServer(t, "block")
	activateRawTaskContent(t, s)
	path := "/v1/raw-task-content/grants"
	valid := `{"schema_version":"local-raw-task-content-grant-create/v1","task_id":"task","kinds":["input"],"actor_id":"actor","duration_seconds":60,"retention_seconds":3600,"max_plaintext_bytes":4096}`
	for _, body := range []string{
		`{}`,
		strings.Replace(valid, `"task_id":"task"`, `"task_id":null`, 1),
		strings.Replace(valid, `"kinds":["input"]`, `"kinds":["input","input"]`, 1),
		strings.Replace(valid, `"duration_seconds":60`, `"duration_seconds":59`, 1),
		strings.Replace(valid, `"retention_seconds":3600`, `"retention_seconds":86401`, 1),
		strings.Replace(valid, `"max_plaintext_bytes":4096`, `"max_plaintext_bytes":1048577`, 1),
		strings.Replace(valid, `"actor_id":"actor"`, `"actor_id":" actor "`, 1),
		strings.TrimSuffix(valid, "}") + `,"enabled":true}`,
		valid + `{}`,
	} {
		w := sessionRequest(t, s, http.MethodPost, path, body, s.bootAdmin, nil, nil)
		if w.Code != http.StatusBadRequest || sessionBody(t, w)["error"] != "raw_task_content_invalid_request" {
			t.Fatal("invalid grant accepted", w.Code, w.Body.String())
		}
	}
	w := sessionRequest(t, s, http.MethodGet, path, nil, s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK || len(sessionBody(t, w)["items"].([]any)) != 0 {
		t.Fatal("invalid requests created grants", w.Code, w.Body.String())
	}
	if w := sessionRequest(t, s, http.MethodGet, path+"/rawgrant-"+strings.Repeat("0", 32), nil, s.bootAdmin, nil, nil); w.Code != http.StatusNotFound {
		t.Fatal("unknown grant status", w.Code)
	}
	if w := sessionRequest(t, s, http.MethodGet, path+"/bad/escape", nil, s.bootAdmin, nil, nil); w.Code != http.StatusNotFound {
		t.Fatal("invalid grant path accepted", w.Code)
	}
	if w := sessionRequest(t, s, http.MethodDelete, path, nil, s.bootAdmin, nil, nil); w.Code != http.StatusMethodNotAllowed {
		t.Fatal("collection method accepted", w.Code)
	}
}

func TestRawTaskContentRuntimePermitAndCaptureLifecycle(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	sessionID := "raw-capture-session"
	code, enrolled := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{
		"schema_version": "local-runtime-session-enroll/v1", "session_id": sessionID,
	})
	if code != http.StatusOK {
		t.Fatal("session enrollment", code, enrolled)
	}
	record, binding, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, sessionID)
	if err != nil || binding.TaskID == "" {
		t.Fatal("runtime binding", binding, err)
	}
	permitRequest := map[string]any{
		"schema_version": "local-raw-task-content-capture-permit-create/v1",
		"platform":       "hermes", "agent_id": agent, "session_id": sessionID, "task_id": binding.TaskID,
		"grant_id": "rawgrant-" + strings.Repeat("0", 32), "expected_grant_signature": strings.Repeat("0", 128),
		"kind": "input", "ttl_seconds": 60,
	}
	w := sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", permitRequest, credential, nil, nil)
	if w.Code != http.StatusConflict || sessionBody(t, w)["error"] != "raw_task_content_disabled" {
		t.Fatal("disabled raw store issued permit", w.Code, w.Body.String())
	}
	activateRawTaskContent(t, s)
	grantRequest := map[string]any{
		"schema_version": "local-raw-task-content-grant-create/v1",
		"task_id":        binding.TaskID, "kinds": []string{"input"}, "actor_id": "PRIVATE_OPERATOR",
		"duration_seconds": 3600, "retention_seconds": 3600, "max_plaintext_bytes": 4096,
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/grants", grantRequest, s.bootAdmin, nil, nil)
	grant := sessionBody(t, w)
	if w.Code != http.StatusCreated {
		t.Fatal("grant", w.Code, grant)
	}
	permitRequest["grant_id"] = grant["grant_id"]
	permitRequest["expected_grant_signature"] = grant["signature"]
	for _, wrongCredential := range []string{"", token, s.bootAdmin} {
		w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", permitRequest, wrongCredential, nil, nil)
		if w.Code != http.StatusUnauthorized {
			t.Fatal("non-runtime credential issued permit", w.Code, w.Body.String())
		}
	}
	crossSession := copyRawMap(permitRequest)
	crossSession["session_id"] = "other-session"
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", crossSession, credential, nil, nil)
	if w.Code != http.StatusUnauthorized {
		t.Fatal("cross-session permit", w.Code, w.Body.String())
	}
	crossTask := copyRawMap(permitRequest)
	crossTask["task_id"] = "other-task"
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", crossTask, credential, nil, nil)
	if w.Code != http.StatusForbidden {
		t.Fatal("cross-task permit", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", permitRequest, credential, nil, nil)
	permit := sessionBody(t, w)
	if w.Code != http.StatusCreated || permit["schema_version"] != "local-raw-task-content-capture-permit/v1" || permit["grant_id"] != grant["grant_id"] || len(permit["signature"].(string)) != 128 {
		t.Fatal("permit issuance", w.Code, permit)
	}
	permitJSON, _ := json.Marshal(permit)
	for _, private := range []string{record.IdentityID, sessionID, binding.BindingID, binding.TaskID} {
		if bytes.Contains(permitJSON, []byte(private)) {
			t.Fatal("permit leaked runtime identity", private)
		}
	}
	capture := map[string]any{
		"schema_version": "local-raw-task-content-capture/v1",
		"platform":       "hermes", "agent_id": agent, "session_id": sessionID, "task_id": binding.TaskID,
		"permit": permit,
		"fields": []map[string]any{
			{"path": "/prompt", "value": "PRIVATE_CAPTURE_VALUE", "secret": false},
			{"path": "/api_token", "value": "PRIVATE_SECRET", "secret": false},
			{"path": "/explicit", "value": "PRIVATE_EXPLICIT", "secret": true},
		},
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", capture, credential, nil, nil)
	result := sessionBody(t, w)
	if w.Code != http.StatusCreated || result["schema_version"] != "local-raw-task-content-capture-result/v1" || result["kind"] != "input" || result["omitted_secret_count"] != float64(2) {
		t.Fatal("capture", w.Code, result)
	}
	resultJSON, _ := json.Marshal(result)
	for _, forbidden := range []string{"PRIVATE_CAPTURE_VALUE", "PRIVATE_SECRET", "ciphertext_base64", "nonce_base64"} {
		if bytes.Contains(resultJSON, []byte(forbidden)) {
			t.Fatal("capture response exposed content", forbidden)
		}
	}
	fields, _, err := s.rawStore.Read(binding.TaskID, result["record_id"].(string), time.Now())
	if err != nil || len(fields) != 1 || fields[0].Value != "PRIVATE_CAPTURE_VALUE" {
		t.Fatal("encrypted capture unreadable", fields, err)
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/grants/"+grant["grant_id"].(string)+"/revoke", map[string]any{
		"schema_version": "local-raw-task-content-revoke/v1", "expected_grant_signature": grant["signature"], "actor_id": "operator",
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK {
		t.Fatal("revoke", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", capture, credential, nil, nil)
	if w.Code != http.StatusConflict || sessionBody(t, w)["error"] != "raw_task_content_authority_revoked" {
		t.Fatal("revoked grant captured", w.Code, w.Body.String())
	}
	identityID := issued["identity"].(map[string]any)["identity_id"].(string)
	if w = sessionRequest(t, s, http.MethodPost, "/v1/runtime-identities/"+identityID+"/revoke", map[string]any{
		"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "operator",
	}, s.bootAdmin, nil, nil); w.Code != http.StatusOK {
		t.Fatal("runtime revoke", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", capture, credential, nil, nil)
	if w.Code != http.StatusUnauthorized {
		t.Fatal("revoked runtime identity captured", w.Code, w.Body.String())
	}
}

func TestRawTaskContentRuntimeCaptureRejectsStrictAndTamperedInputs(t *testing.T) {
	s, _, credential, agent := managedIdentityFixture(t, "block")
	sessionID := "strict-raw-session"
	if code, out := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{
		"schema_version": "local-runtime-session-enroll/v1", "session_id": sessionID,
	}); code != http.StatusOK {
		t.Fatal(code, out)
	}
	_, binding, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, sessionID)
	if err != nil {
		t.Fatal(err)
	}
	activateRawTaskContent(t, s)
	w := sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/grants", map[string]any{
		"schema_version": "local-raw-task-content-grant-create/v1", "task_id": binding.TaskID,
		"kinds": []string{"output"}, "actor_id": "operator", "duration_seconds": 3600, "retention_seconds": 3600, "max_plaintext_bytes": 4096,
	}, s.bootAdmin, nil, nil)
	grant := sessionBody(t, w)
	permitRequest := map[string]any{
		"schema_version": "local-raw-task-content-capture-permit-create/v1", "platform": "hermes", "agent_id": agent,
		"session_id": sessionID, "task_id": binding.TaskID, "grant_id": grant["grant_id"],
		"expected_grant_signature": grant["signature"], "kind": "output", "ttl_seconds": 60,
	}
	for _, body := range []string{
		`{}`,
		`{"schema_version":"local-raw-task-content-capture-permit-create/v1","platform":"hermes","agent_id":null,"session_id":"s","task_id":"t","grant_id":"rawgrant-00000000000000000000000000000000","expected_grant_signature":"` + strings.Repeat("0", 128) + `","kind":"output","ttl_seconds":60}`,
		`{"schema_version":"local-raw-task-content-capture-permit-create/v1","platform":"hermes","agent_id":"a","session_id":"s","task_id":"t","grant_id":"rawgrant-00000000000000000000000000000000","expected_grant_signature":"` + strings.Repeat("0", 128) + `","kind":"output","ttl_seconds":60,"ttl_seconds":61}`,
	} {
		w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", body, credential, nil, nil)
		if w.Code != http.StatusBadRequest {
			t.Fatal("invalid permit request", w.Code, w.Body.String())
		}
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/capture-permits", permitRequest, credential, nil, nil)
	permit := sessionBody(t, w)
	if w.Code != http.StatusCreated {
		t.Fatal(w.Code, permit)
	}
	badNested := `{"schema_version":"local-raw-task-content-capture/v1","platform":"hermes","agent_id":"` + agent + `","session_id":"` + sessionID + `","task_id":"` + binding.TaskID + `","permit":{},"fields":[{"path":"/result","value":"one","value":"two","secret":false}]}`
	for _, body := range []string{
		badNested,
		`{"schema_version":"local-raw-task-content-capture/v1","platform":"hermes","agent_id":"` + agent + `","session_id":"` + sessionID + `","task_id":"` + binding.TaskID + `","permit":{},"fields":[{"Path":"/result","value":"one","secret":false}]}`,
	} {
		w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", body, credential, nil, nil)
		if w.Code != http.StatusBadRequest {
			t.Fatal("non-strict nested field accepted", w.Code, w.Body.String())
		}
	}
	tampered := copyRawMap(permit)
	tampered["kind"] = "input"
	capture := map[string]any{
		"schema_version": "local-raw-task-content-capture/v1", "platform": "hermes", "agent_id": agent,
		"session_id": sessionID, "task_id": binding.TaskID, "permit": tampered,
		"fields": []map[string]any{{"path": "/result", "value": "value", "secret": false}},
	}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", capture, credential, nil, nil)
	if w.Code != http.StatusBadRequest {
		t.Fatal("tampered permit accepted", w.Code, w.Body.String())
	}
	capture["permit"] = permit
	capture["fields"] = []map[string]any{{"path": "/token", "value": "all removed", "secret": true}}
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/captures", capture, credential, nil, nil)
	if w.Code != http.StatusBadRequest {
		t.Fatal("empty post-filter content accepted", w.Code, w.Body.String())
	}
	if w := sessionRequest(t, s, http.MethodGet, "/v1/raw-task-content/captures", nil, credential, nil, nil); w.Code != http.StatusMethodNotAllowed {
		t.Fatal("capture method accepted", w.Code)
	}
}

func TestRawTaskContentNativeCaptureResolvesRuntimeBindingAndUniqueGrant(t *testing.T) {
	s, _, credential, agent := managedIdentityFixture(t, "block")
	sessionID := "native-raw-session"
	if code, out := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{
		"schema_version": "local-runtime-session-enroll/v1", "session_id": sessionID,
	}); code != http.StatusOK {
		t.Fatal(code, out)
	}
	runtimeRecord, binding, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, sessionID)
	if err != nil {
		t.Fatal(err)
	}
	request := map[string]any{
		"schema_version": "local-raw-task-content-native-capture/v1", "platform": "hermes",
		"agent_id": agent, "session_id": sessionID, "kind": "output",
		"fields": []map[string]any{{"path": "/result", "value": "NATIVE_PRIVATE_RESULT", "secret": false}},
	}
	path := "/v1/raw-task-content/native-captures"
	if w := sessionRequest(t, s, http.MethodPost, path, request, credential, nil, nil); w.Code != http.StatusConflict {
		t.Fatal("disabled native capture", w.Code, w.Body.String())
	}
	activateRawTaskContent(t, s)
	if w := sessionRequest(t, s, http.MethodPost, path, request, credential, nil, nil); w.Code != http.StatusForbidden {
		t.Fatal("native capture guessed missing grant", w.Code, w.Body.String())
	}
	grant, err := s.rawAuthority.Issue(binding.TaskID, []string{"output"}, "operator", time.Hour, time.Hour, 4096, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	for _, unauthorized := range []string{"", token, s.bootAdmin} {
		if w := sessionRequest(t, s, http.MethodPost, path, request, unauthorized, nil, nil); w.Code != http.StatusUnauthorized {
			t.Fatal("non-runtime credential captured", w.Code, w.Body.String())
		}
	}
	w := sessionRequest(t, s, http.MethodPost, path, request, credential, nil, nil)
	result := sessionBody(t, w)
	if w.Code != http.StatusCreated || result["schema_version"] != "local-raw-task-content-capture-result/v1" || result["kind"] != "output" {
		t.Fatal("native capture", w.Code, result)
	}
	serialized, _ := json.Marshal(request)
	for _, forbidden := range []string{binding.TaskID, binding.BindingID, grant.GrantID, grant.Signature} {
		if bytes.Contains(serialized, []byte(forbidden)) {
			t.Fatal("adapter request carried server authority", forbidden)
		}
	}
	fields, _, err := s.rawStore.Read(binding.TaskID, result["record_id"].(string), time.Now())
	if err != nil || len(fields) != 1 || fields[0].Value != "NATIVE_PRIVATE_RESULT" {
		t.Fatal("native ciphertext unreadable", fields, err)
	}
	outputs, err := s.rawStore.ListRuntimeOutputs(binding.TaskID, runtimeRecord.IdentityID, sessionID, binding.BindingID, time.Now())
	if err != nil || len(outputs) != 1 || outputs[0].RecordID != result["record_id"] {
		t.Fatal("native output lost server-verified runtime provenance", outputs, err)
	}
	if outputs, err := s.rawStore.ListRuntimeOutputs(binding.TaskID, runtimeRecord.IdentityID, "other-session", binding.BindingID, time.Now()); err != nil || len(outputs) != 0 {
		t.Fatal("native output attributed to another session", outputs, err)
	}
	second, err := s.rawAuthority.Issue(binding.TaskID, []string{"output"}, "operator", time.Hour, time.Hour, 4096, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if w = sessionRequest(t, s, http.MethodPost, path, request, credential, nil, nil); w.Code != http.StatusConflict {
		t.Fatal("overlapping grants did not fail closed", w.Code, w.Body.String())
	}
	if _, err := s.rawAuthority.Revoke(second.GrantID, second.Signature, "operator", time.Now()); err != nil {
		t.Fatal(err)
	}
	if w = sessionRequest(t, s, http.MethodPost, path, request, credential, nil, nil); w.Code != http.StatusCreated {
		t.Fatal("revoked overlap still blocked unique grant", w.Code, w.Body.String())
	}
	bad := `{"schema_version":"local-raw-task-content-native-capture/v1","platform":"hermes","agent_id":"` + agent + `","session_id":"` + sessionID + `","kind":"output","fields":[{"path":"/result","value":"one","value":"two","secret":false}]}`
	if w = sessionRequest(t, s, http.MethodPost, path, bad, credential, nil, nil); w.Code != http.StatusBadRequest {
		t.Fatal("duplicate native field accepted", w.Code, w.Body.String())
	}
	if w = sessionRequest(t, s, http.MethodGet, path, nil, credential, nil, nil); w.Code != http.StatusMethodNotAllowed {
		t.Fatal("native capture accepted read method", w.Code)
	}
}

func TestRawTaskContentRecordManagementReadDeleteAndPurge(t *testing.T) {
	s, stateStore := newServer(t, "block")
	activateRawTaskContent(t, s)
	now := time.Now()
	activeGrant, err := s.rawAuthority.Issue("task-a", []string{"note"}, "operator", time.Hour, time.Hour, 4096, now)
	if err != nil {
		t.Fatal(err)
	}
	activePrepared, _ := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/text", Value: "VISIBLE_PRIVATE_VALUE"}})
	active, err := s.rawAuthority.Capture(activeGrant.GrantID, "task-a", activePrepared, now)
	if err != nil {
		t.Fatal(err)
	}
	expiredAt := now.Add(-2 * time.Hour)
	expiredGrant, err := s.rawAuthority.Issue("task-a", []string{"note"}, "operator", 3*time.Hour, time.Hour, 4096, expiredAt)
	if err != nil {
		t.Fatal(err)
	}
	expiredPrepared, _ := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/text", Value: "EXPIRED_PRIVATE_VALUE"}})
	expired, err := s.rawAuthority.Capture(expiredGrant.GrantID, "task-a", expiredPrepared, expiredAt)
	if err != nil {
		t.Fatal(err)
	}
	otherGrant, _ := s.rawAuthority.Issue("task-b", []string{"note"}, "operator", time.Hour, time.Hour, 4096, now)
	otherPrepared, _ := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/text", Value: "OTHER_TASK_VALUE"}})
	other, _ := s.rawAuthority.Capture(otherGrant.GrantID, "task-b", otherPrepared, now)

	searchPath := "/v1/raw-task-content/records/search"
	search := map[string]any{"schema_version": "local-raw-task-content-record-list/v1", "task_id": "task-a"}
	for _, credential := range []string{"", token} {
		w := sessionRequest(t, s, http.MethodPost, searchPath, search, credential, nil, nil)
		want := http.StatusUnauthorized
		if credential == token {
			want = http.StatusForbidden
		}
		if w.Code != want {
			t.Fatal("non-admin listed raw records", credential, w.Code)
		}
	}
	w := sessionRequest(t, s, http.MethodPost, searchPath, search, s.bootAdmin, nil, nil)
	list := sessionBody(t, w)
	items := list["items"].([]any)
	if w.Code != http.StatusOK || list["schema_version"] != "local-raw-task-content-records/v1" || len(items) != 2 {
		t.Fatal("record list", w.Code, list)
	}
	statuses := map[string]string{}
	for _, item := range items {
		row := item.(map[string]any)
		statuses[row["record_id"].(string)] = row["status"].(string)
		if row["task_ref"] == "task-a" || row["ciphertext_base64"] != nil {
			t.Fatal("list leaked content or task", row)
		}
	}
	if statuses[active.RecordID] != "active" || statuses[expired.RecordID] != "expired" {
		t.Fatal("record status", statuses)
	}
	readPath := "/v1/raw-task-content/records/" + active.RecordID + "/read"
	w = sessionRequest(t, s, http.MethodPost, readPath, map[string]any{
		"schema_version": "local-raw-task-content-record-read/v1", "task_id": "wrong-task",
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatal("cross-task read did not fail closed", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodPost, readPath, map[string]any{
		"schema_version": "local-raw-task-content-record-read/v1", "task_id": "task-a",
	}, s.bootAdmin, nil, nil)
	content := sessionBody(t, w)
	if w.Code != http.StatusOK || content["contains_plaintext"] != true || content["fields"].([]any)[0].(map[string]any)["value"] != "VISIBLE_PRIVATE_VALUE" {
		t.Fatal("record read", w.Code, content)
	}
	if content["ciphertext_base64"] != nil || content["record"].(map[string]any)["status"] != "active" {
		t.Fatal("read response shape", content)
	}
	deletePath := "/v1/raw-task-content/records/" + active.RecordID + "/delete"
	w = sessionRequest(t, s, http.MethodPost, deletePath, map[string]any{
		"schema_version": "local-raw-task-content-record-delete/v1", "task_id": "task-a", "confirm_record_id": expired.RecordID,
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusBadRequest {
		t.Fatal("wrong delete confirmation accepted", w.Code)
	}
	w = sessionRequest(t, s, http.MethodPost, deletePath, map[string]any{
		"schema_version": "local-raw-task-content-record-delete/v1", "task_id": "task-a", "confirm_record_id": active.RecordID,
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusOK || sessionBody(t, w)["deleted"] != true {
		t.Fatal("record delete", w.Code, w.Body.String())
	}
	w = sessionRequest(t, s, http.MethodPost, deletePath, map[string]any{
		"schema_version": "local-raw-task-content-record-delete/v1", "task_id": "task-a", "confirm_record_id": active.RecordID,
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusNotFound {
		t.Fatal("missing delete status", w.Code, w.Body.String())
	}
	chainBefore, _ := s.d.Chain.Read()
	w = sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/purge-expired", map[string]any{
		"schema_version": "local-raw-task-content-purge-expired/v1", "confirm_expired_only": true,
	}, s.bootAdmin, nil, nil)
	purged := sessionBody(t, w)
	if w.Code != http.StatusOK || purged["deleted_records"] != float64(1) || purged["released_bytes"].(float64) <= 0 {
		t.Fatal("expired purge", w.Code, purged)
	}
	chainAfter, _ := s.d.Chain.Read()
	if len(chainAfter) != len(chainBefore) {
		t.Fatal("raw deletion changed receipt chain")
	}
	if _, err := os.Stat(filepath.Join(stateStore.Dir, "raw-task-content", other.RecordID+".json")); err != nil {
		t.Fatal("purge deleted active other task", err)
	}
}

func TestRawTaskContentRecordManagementFailsWholeListOnTamper(t *testing.T) {
	s, stateStore := newServer(t, "block")
	activateRawTaskContent(t, s)
	now := time.Now()
	for _, task := range []string{"task-a", "task-b"} {
		grant, _ := s.rawAuthority.Issue(task, []string{"note"}, "operator", time.Hour, time.Hour, 4096, now)
		prepared, _ := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/text", Value: task + " value"}})
		if _, err := s.rawAuthority.Capture(grant.GrantID, task, prepared, now); err != nil {
			t.Fatal(err)
		}
	}
	entries, _ := os.ReadDir(filepath.Join(stateStore.Dir, "raw-task-content"))
	path := filepath.Join(stateStore.Dir, "raw-task-content", entries[len(entries)-1].Name())
	raw, _ := os.ReadFile(path)
	var envelope map[string]any
	_ = json.Unmarshal(raw, &envelope)
	envelope["kind"] = "input"
	tampered, _ := json.Marshal(envelope)
	if err := os.WriteFile(path, tampered, 0600); err != nil {
		t.Fatal(err)
	}
	w := sessionRequest(t, s, http.MethodPost, "/v1/raw-task-content/records/search", map[string]any{
		"schema_version": "local-raw-task-content-record-list/v1", "task_id": "task-a",
	}, s.bootAdmin, nil, nil)
	if w.Code != http.StatusServiceUnavailable || sessionBody(t, w)["error"] != "raw_task_content_unavailable" {
		t.Fatal("tampered list returned partial records", w.Code, w.Body.String())
	}
}

func TestRawTaskContentAutomaticPurgeIsOptionalAuthenticatedAndIsolated(t *testing.T) {
	s, stateStore := newServer(t, "block")
	if err := s.PurgeExpiredRawContent(time.Now()); err != nil {
		t.Fatal("disabled maintenance was not a no-op", err)
	}
	if _, err := os.Stat(filepath.Join(stateStore.Dir, "raw-task-content")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("disabled maintenance initialized optional state", err)
	}

	activateRawTaskContent(t, s)
	now := time.Now().UTC()
	activeGrant, err := s.rawAuthority.Issue("active-task", []string{"note"}, "operator", time.Hour, time.Hour, 4096, now)
	if err != nil {
		t.Fatal(err)
	}
	expiredAt := now.Add(-2 * time.Hour)
	expiredGrant, err := s.rawAuthority.Issue("expired-task", []string{"note"}, "operator", 3*time.Hour, time.Hour, 4096, expiredAt)
	if err != nil {
		t.Fatal(err)
	}
	prepared, _ := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/text", Value: "temporary private detail"}})
	active, err := s.rawAuthority.Capture(activeGrant.GrantID, "active-task", prepared, now)
	if err != nil {
		t.Fatal(err)
	}
	expired, err := s.rawAuthority.Capture(expiredGrant.GrantID, "expired-task", prepared, expiredAt)
	if err != nil {
		t.Fatal(err)
	}
	grantBefore, err := os.ReadFile(filepath.Join(stateStore.Dir, "raw-task-content-authority", expiredGrant.GrantID+".grant.json"))
	if err != nil {
		t.Fatal(err)
	}
	chainBefore, err := s.d.Chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if err := s.PurgeExpiredRawContent(now); err != nil {
		t.Fatal("automatic purge failed", err)
	}
	if _, err := os.Stat(filepath.Join(stateStore.Dir, "raw-task-content", expired.RecordID+".json")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("expired ciphertext retained", err)
	}
	activePath := filepath.Join(stateStore.Dir, "raw-task-content", active.RecordID+".json")
	if _, err := os.Stat(activePath); err != nil {
		t.Fatal("active ciphertext deleted", err)
	}
	grantAfter, err := os.ReadFile(filepath.Join(stateStore.Dir, "raw-task-content-authority", expiredGrant.GrantID+".grant.json"))
	if err != nil || !bytes.Equal(grantBefore, grantAfter) {
		t.Fatal("automatic purge changed grant authority", err)
	}
	chainAfter, err := s.d.Chain.Read()
	if err != nil || len(chainAfter) != len(chainBefore) {
		t.Fatal("automatic purge changed receipt facts", err)
	}

	raw, err := os.ReadFile(activePath)
	if err != nil {
		t.Fatal(err)
	}
	var envelope map[string]any
	if err := json.Unmarshal(raw, &envelope); err != nil {
		t.Fatal(err)
	}
	envelope["kind"] = "input"
	tampered, _ := json.Marshal(envelope)
	if err := os.WriteFile(activePath, tampered, 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.PurgeExpiredRawContent(now.Add(2 * time.Hour)); !errors.Is(err, rawcontent.ErrState) {
		t.Fatal("tampered content did not fail cleanup closed", err)
	}
	if _, err := os.Stat(activePath); err != nil {
		t.Fatal("failed cleanup removed tampered evidence", err)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, loopbackRequest(http.MethodGet, "/healthz", nil))
	if w.Code != http.StatusOK {
		t.Fatal("cleanup failure blocked default service", w.Code, w.Body.String())
	}
}

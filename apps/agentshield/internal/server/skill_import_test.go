package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/skillimport"
)

func skillImportHTTPFixture(t *testing.T) (*Server, skillimport.CreateRequest) {
	t.Helper()
	s, _ := newServer(t, "block")
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: http-import\ndescription: Read a synthetic report.\n---\nRead a report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	return s, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: "si-" + strings.Repeat("a", 32), SourceKind: "local_dir", Path: source, ActorID: "fixture-human"}
}
func TestSkillImportHTTPFixedCopyReadAndTamper(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	code, first := call(t, s, "POST", "/v1/skill-imports", token, req)
	if code != 201 || first["installed"] != false || first["reused"] != false {
		t.Fatal(code, first)
	}
	original, err := os.ReadFile(filepath.Join(req.Path, "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	record, analysis, err := s.skillImports.Load(context.Background(), req.ImportID)
	if err != nil || !admission.Verify(s.d.Key.Public(), analysis.Admission) {
		t.Fatal("unverified import audit", err)
	}
	raw, _ := json.Marshal(first)
	for _, forbidden := range []string{req.Path, string(original), s.d.Token} {
		if bytes.Contains(raw, []byte(forbidden)) {
			t.Fatal("response leaked local content")
		}
	}
	for _, name := range []string{"grants", "admissions"} {
		files, err := os.ReadDir(filepath.Join(s.d.Store.Dir, name))
		if err != nil && !os.IsNotExist(err) {
			t.Fatal(err)
		}
		if len(files) != 0 {
			t.Fatal("candidate mutated authority", name)
		}
	}
	if err = os.WriteFile(filepath.Join(req.Path, "SKILL.md"), []byte("source changed"), 0600); err != nil {
		t.Fatal(err)
	}
	code, retry := call(t, s, "POST", "/v1/skill-imports", token, req)
	if code != 200 || retry["reused"] != true || retry["import"].(map[string]any)["artifact_digest"] != record.ArtifactDigest {
		t.Fatal(code, retry)
	}
	route := "/v1/skill-imports/" + req.ImportID
	code, read := call(t, s, "GET", route, token, nil)
	if code != 200 || read["installed"] != false {
		t.Fatal(code, read)
	}
	changed := req
	changed.ActorID = "different-reviewer"
	if code, _ = call(t, s, "POST", "/v1/skill-imports", token, changed); code != 409 {
		t.Fatal("different operator reused ID", code)
	}
	if err = os.WriteFile(filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", req.ImportID, "payload", "SKILL.md"), []byte("replaced copy"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, method := range []string{"GET", "POST"} {
		path := route
		if method == "POST" {
			path = "/v1/skill-imports"
		}
		code, out := call(t, s, method, path, token, req)
		if code != 409 || out["error"] != "skill_import_changed" {
			t.Fatal("tampered candidate exposed", code, out)
		}
	}
}
func TestSkillImportHTTPStrictAuthenticationAndBody(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	raw, _ := json.Marshal(req)
	for _, route := range []string{"/v1/skill-imports", "/v1/skill-imports/" + req.ImportID} {
		method := "GET"
		if route == "/v1/skill-imports" {
			method = "POST"
		}
		for _, credential := range []string{"", token} {
			r := loopbackRequest(method, route, req)
			if credential != "" {
				r.Header.Set("Authorization", "Bearer "+credential)
			}
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			expected := 401
			if credential != "" {
				expected = 403
			}
			if w.Code != expected {
				t.Fatal("admin boundary", w.Code)
			}
		}
	}
	malformed := []string{
		string(raw) + " {}", "null", "[]",
		strings.Replace(string(raw), `"actor_id":`, `"Actor_ID":`, 1),
		strings.Replace(string(raw), `"actor_id":"fixture-human"`, `"actor_id":null`, 1),
		strings.Replace(string(raw), `"actor_id":"fixture-human"`, `"actor_id":"fixture-human","actor_id":"other"`, 1),
		strings.Replace(string(raw), `"actor_id":"fixture-human"`, `"actor_id":"`+strings.Repeat("x", 17000)+`"`, 1),
		strings.Replace(string(raw), `"actor_id":"fixture-human"`, `"actor_id":true`, 1),
		strings.Replace(string(raw), `"actor_id":"fixture-human"`, `"actor_id":"fixture-human","extra":true`, 1),
	}
	var fields map[string]any
	if json.Unmarshal(raw, &fields) != nil {
		t.Fatal("fixture")
	}
	for name := range fields {
		missing := map[string]any{}
		for k, v := range fields {
			if k != name {
				missing[k] = v
			}
		}
		b, _ := json.Marshal(missing)
		malformed = append(malformed, string(b))
	}
	for _, body := range malformed {
		r := loopbackRequest("POST", "/v1/skill-imports", nil)
		r.Body = io.NopCloser(strings.NewReader(body))
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 || !strings.Contains(w.Body.String(), "skill_import_invalid") {
			t.Fatal("invalid request accepted", w.Code, w.Body.String())
		}
	}
	for _, badPath := range []string{"relative/path", ""} {
		bad := req
		bad.Path = badPath
		if code, _ := call(t, s, "POST", "/v1/skill-imports", token, bad); code != 400 {
			t.Fatal("relative path accepted", code)
		}
	}
	records, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "skill-imports", "records"))
	if err != nil || len(records) != 0 {
		t.Fatal("invalid request published", err)
	}
	if code, _ := call(t, s, "GET", "/v1/skill-imports/"+req.ImportID, token, nil); code != 404 {
		t.Fatal(code)
	}
}
func TestSkillImportHTTPBusyCancellationAndErrorPrivacy(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	s.skillImportMu.Lock()
	for _, route := range []string{"/v1/skill-imports", "/v1/skill-imports/" + req.ImportID} {
		method := "POST"
		if route != "/v1/skill-imports" {
			method = "GET"
		}
		r := loopbackRequest(method, route, req)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 429 || w.Header().Get("Retry-After") != "1" || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatal("unbounded import queue", w.Code)
		}
	}
	s.skillImportMu.Unlock()
	r := loopbackRequest("POST", "/v1/skill-imports", req)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	ctx, cancel := context.WithCancel(r.Context())
	cancel()
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 408 {
		t.Fatal("cancel ignored", w.Code)
	}
	req.Path = filepath.Join(req.Path, "missing-sensitive-path")
	code, out := call(t, s, "POST", "/v1/skill-imports", token, req)
	if code == 201 || strings.Contains(out["error"].(string), "sensitive") {
		t.Fatal("missing path accepted/leaked", code, out)
	}
	if _, _, err := s.skillImports.Load(context.Background(), req.ImportID); err != skillimport.ErrNotFound {
		t.Fatal("failed import published", err)
	}
}

type importDeadlineWriter struct {
	*httptest.ResponseRecorder
	deadline time.Time
	failure  error
}

func (w *importDeadlineWriter) SetWriteDeadline(at time.Time) error {
	w.deadline = at
	return w.failure
}
func TestSkillImportHTTPResponseDeadline(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	for _, fail := range []bool{true, false} {
		w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder()}
		if fail {
			w.failure = errors.New("closed connection with private detail")
		}
		r := loopbackRequest("POST", "/v1/skill-imports", req)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		before := time.Now()
		s.Handler().ServeHTTP(w, r)
		if w.deadline.Sub(before) < 64*time.Second || w.deadline.Sub(before) > 66*time.Second {
			t.Fatal("import response still has default 15s budget")
		}
		if fail {
			if w.Code != 503 || strings.Contains(w.Body.String(), "private") {
				t.Fatal(w.Code, w.Body.String())
			}
			if _, _, err := s.skillImports.Load(context.Background(), req.ImportID); !errors.Is(err, skillimport.ErrNotFound) {
				t.Fatal("started after connection failure")
			}
		} else if w.Code != 201 {
			t.Fatal("deadline failure leaked import slot", w.Code)
		}
	}
}

func TestSkillImportCollectionListAdminAndMetadata(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	for _, credential := range []string{"", token} {
		r := loopbackRequest("GET", "/v1/skill-imports", nil)
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("list auth", w.Code)
		}
	}
	if code, _ := call(t, s, "POST", "/v1/skill-imports", token, req); code != 201 {
		t.Fatal(code)
	}
	code, result := call(t, s, "GET", "/v1/skill-imports", token, nil)
	if code != 200 || result["schema_version"] != "local-skill-import-list/v1" {
		t.Fatal(code, result)
	}
	item := result["items"].([]any)[0].(map[string]any)
	if item["payload_status"] != "unchecked" || item["record_status"] != "metadata_verified" {
		t.Fatal(item)
	}
	s.skillImportMu.Lock()
	code, _ = call(t, s, "GET", "/v1/skill-imports", token, nil)
	s.skillImportMu.Unlock()
	if code != 429 {
		t.Fatal("list bypassed work limit", code)
	}
}

func TestRemoteSkillImportHTTPStrictAdminAndBounds(t *testing.T) {
	s, local := skillImportHTTPFixture(t)
	req := skillimport.RemoteCreateRequest{SchemaVersion: "local-skill-import-remote-create/v1", ImportID: local.ImportID, URL: "https://127.0.0.1/private?token=secret", ActorID: local.ActorID}
	route := "/v1/skill-imports/remote"
	for _, credential := range []string{"", token} {
		r := loopbackRequest("POST", route, req)
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("remote admin boundary", w.Code)
		}
	}
	code, out := call(t, s, "POST", route, token, req)
	if code != 400 || out["error"] != "skill_import_url_blocked" {
		t.Fatal(code, out)
	}
	if code, _ := call(t, s, "GET", route, token, nil); code != 405 {
		t.Fatal("remote path dispatched as ID", code)
	}
	raw, _ := json.Marshal(req)
	var fields map[string]any
	_ = json.Unmarshal(raw, &fields)
	bodies := []string{string(raw) + " {}", "null", "[]", strings.Replace(string(raw), `"url":`, `"URL":`, 1), strings.Replace(string(raw), `"url":`, `"url":"https://ignored.example.com/","url":`, 1), strings.TrimSuffix(string(raw), "}") + `,"extra":true}`}
	for name := range fields {
		for _, mode := range []string{"missing", "null", "bool"} {
			copy := map[string]any{}
			for k, v := range fields {
				copy[k] = v
			}
			switch mode {
			case "missing":
				delete(copy, name)
			case "null":
				copy[name] = nil
			case "bool":
				copy[name] = true
			}
			data, _ := json.Marshal(copy)
			bodies = append(bodies, string(data))
		}
	}
	for _, body := range bodies {
		r := loopbackRequest("POST", route, nil)
		r.Body = io.NopCloser(strings.NewReader(body))
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 || !strings.Contains(w.Body.String(), "skill_import_invalid") || strings.Contains(w.Body.String(), "secret") {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	s.skillImportMu.Lock()
	code, _ = call(t, s, "POST", route, token, req)
	s.skillImportMu.Unlock()
	if code != 429 {
		t.Fatal("remote bypassed slot", code)
	}
	req.URL = "https://download.example.com/archive.zip"
	r := loopbackRequest("POST", route, req)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	ctx, cancel := context.WithCancel(r.Context())
	cancel()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r.WithContext(ctx))
	if w.Code != 408 {
		t.Fatal("canceled import not rejected before network", w.Code)
	}
	for _, test := range []struct {
		err    error
		status int
		code   string
	}{{skillimport.ErrURLBlocked, 400, "skill_import_url_blocked"}, {skillimport.ErrDownloadFailed, 502, "skill_import_download_failed"}, {skillimport.ErrArchiveMismatch, 409, "skill_import_archive_mismatch"}} {
		w := httptest.NewRecorder()
		skillImportError(w, test.err)
		if w.Code != test.status || !strings.Contains(w.Body.String(), test.code) {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	records, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "skill-imports", "records"))
	if err != nil || len(records) != 0 {
		t.Fatal("invalid remote request persisted", err)
	}
}

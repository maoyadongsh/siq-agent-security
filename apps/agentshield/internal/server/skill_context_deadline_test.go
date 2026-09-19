package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestSkillContextManagementRealHTTPDeadline(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, legacy := range []bool{true, false} {
		h := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			time.Sleep(100 * time.Millisecond)
			if legacy {
				w = legacyAdapterResponse{w}
			}
			s.skillContextManagement(w, r)
		}))
		h.Config.WriteTimeout = 25 * time.Millisecond
		h.Start()
		client := h.Client()
		client.Timeout = 10 * time.Second
		res, err := client.Get(h.URL + "/v1/skill-contexts/management?install_id=sin-" + strings.Repeat("a", 64))
		if legacy {
			if err == nil {
				res.Body.Close()
				t.Fatal("legacy management deadline unexpectedly returned JSON")
			}
		} else {
			if err != nil {
				t.Fatal(err)
			}
			raw, readErr := io.ReadAll(res.Body)
			res.Body.Close()
			var body map[string]any
			if readErr != nil || json.Unmarshal(raw, &body) != nil || body["error"] == nil {
				t.Fatalf("missing-install readback lost: %s %v", raw, readErr)
			}
		}
		h.Close()
	}
}

func TestSkillContextResponseFailureDoesNotAuditOrIssue(t *testing.T) {
	s, store := newServer(t, "block")
	attachSkillContextStore(t, s)
	before, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	r := loopbackRequest("POST", "/v1/skill-contexts", map[string]any{
		"schema_version": "local-skill-execution-context-issue/v1", "instance_id": contextTestInstance,
		"session_id": contextTestSession, "task_id": "", "install_id": contextTestInstall,
		"ttl_seconds": 600, "actor_id": "fixture", "confirm_issue": true,
	})
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder(), failure: errors.New("private detail")}
	s.Handler().ServeHTTP(w, r)
	if w.Code != 503 || strings.Contains(w.Body.String(), "private") {
		t.Fatalf("unexpected response: %d %s", w.Code, w.Body.String())
	}
	after, err := store.TailAudit(100)
	if err != nil || len(before) != len(after) {
		t.Fatal("failed response wrote issue audit")
	}
	items, err := s.skillContexts.ManagementRecords(r.Context(), contextTestInstall)
	if err != nil || len(items) != 0 {
		t.Fatal("failed response issued SEC")
	}
}

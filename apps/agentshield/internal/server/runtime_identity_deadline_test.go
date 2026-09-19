package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestRuntimeIdentityManagementRealHTTPDeadline(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, legacy := range []bool{true, false} {
		t.Run(map[bool]string{true: "old-deadline-disconnects", false: "response-survives-original-deadline"}[legacy], func(t *testing.T) {
			h := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				time.Sleep(100 * time.Millisecond)
				if legacy {
					w = legacyAdapterResponse{w}
				}
				s.runtimeIdentityCollection(w, r)
			}))
			h.Config.WriteTimeout = 25 * time.Millisecond
			h.Start()
			defer h.Close()
			client := h.Client()
			client.Timeout = 10 * time.Second
			res, err := client.Get(h.URL + "/v1/runtime-identities")
			if legacy {
				if err == nil {
					res.Body.Close()
					t.Fatal("old deadline unexpectedly returned identity state")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			raw, err := io.ReadAll(res.Body)
			var data struct {
				Items []json.RawMessage `json:"items"`
			}
			if err != nil || res.StatusCode != 200 || json.Unmarshal(raw, &data) != nil || data.Items == nil || len(data.Items) != 0 {
				t.Fatalf("identity readback failed: status=%d body=%s err=%v", res.StatusCode, raw, err)
			}
		})
	}
}

func TestRuntimeIdentityResponseFailureBeforeMutation(t *testing.T) {
	s, store := newServer(t, "block")
	before, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	for _, cancel := range []bool{false, true} {
		for _, revoke := range []bool{false, true} {
			route := "/v1/runtime-identities"
			body := map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": "hi-" + strings.Repeat("a", 32), "grant_id": "missing", "expected_grant_revision": 0, "actor_id": "fixture", "session_ttl_seconds": 600}
			if revoke {
				route += "/ri-" + strings.Repeat("a", 32) + "/revoke"
				body = map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "fixture"}
			}
			r := loopbackRequest("POST", route, body)
			r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
			if cancel {
				ctx, stop := context.WithCancel(r.Context())
				stop()
				r = r.WithContext(ctx)
			}
			w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder(), failure: errors.New("private socket detail")}
			s.Handler().ServeHTTP(w, r)
			want := http.StatusServiceUnavailable
			if cancel {
				want = http.StatusRequestTimeout
			}
			if w.Code != want || strings.Contains(w.Body.String(), "private") {
				t.Fatalf("response preparation: %d %s", w.Code, w.Body.String())
			}
		}
	}
	items, err := s.runtimeIdentities.List()
	if err != nil || len(items) != 0 {
		t.Fatal("response failure created an identity")
	}
	after, err := store.TailAudit(100)
	if err != nil || len(before) != len(after) {
		t.Fatal("response failure changed audit state")
	}
}

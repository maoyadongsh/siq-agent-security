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

// Hide only SetWriteDeadline to reproduce the former handler's unchanged
// connection deadline; all status/body writes still use the real socket.
type legacyAdapterResponse struct{ http.ResponseWriter }

func TestAdapterManagementRealHTTPDeadline(t *testing.T) {
	// Real sockets are essential: ResponseRecorder cannot reproduce a late
	// buffered write becoming EOF. Only the server deadline is scaled here.
	for _, extend := range []bool{false, true} {
		t.Run(map[bool]string{false: "legacy-deadline-disconnects", true: "scoped-deadline-returns-json"}[extend], func(t *testing.T) {
			s, _ := newServer(t, "block")
			h := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				time.Sleep(100 * time.Millisecond)
				if !extend {
					w = legacyAdapterResponse{w}
				}
				s.adapterPreview(w, r)
			}))
			h.Config.WriteTimeout = 25 * time.Millisecond
			h.Start()
			defer h.Close()
			client := h.Client()
			client.Timeout = 15 * time.Second
			res, err := client.Post(h.URL+"/v1/adapter/preview", "application/json", strings.NewReader(`{"platform":"hermes","action":"install"}`))
			if !extend {
				if err == nil {
					res.Body.Close()
					t.Fatal("legacy write deadline unexpectedly delivered a response")
				}
				t.Log("old 15s-shaped deadline reproduced as a real connection failure:", err)
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			raw, err := io.ReadAll(res.Body)
			var plan map[string]any
			if err != nil || res.StatusCode != 200 || json.Unmarshal(raw, &plan) != nil || plan["platform"] != "hermes" || plan["action"] != "install" || plan["plan_digest"] == "" {
				t.Fatalf("incomplete management response: %d %s %v", res.StatusCode, raw, err)
			}
		})
	}
}

func managementBody(route string) map[string]any {
	return map[string]any{"platform": "hermes", "action": "install", "plan_id": "ap-unavailable", "plan_digest": "unavailable"}
}

func TestAdapterManagementDeadlineFailurePrecedesWork(t *testing.T) {
	s, store := newServer(t, "block")
	before, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	for _, route := range []string{"preview", "install", "uninstall", "recover"} {
		r := loopbackRequest("POST", "/v1/adapter/"+route, managementBody(route))
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder(), failure: errors.New("private socket detail")}
		start := time.Now()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 503 || strings.Contains(w.Body.String(), "private") {
			t.Fatalf("%s: %d %s", route, w.Code, w.Body.String())
		}
		if w.deadline.Sub(start) < adapterManagementWriteBudget-time.Second || w.deadline.Sub(start) > adapterManagementWriteBudget+time.Second {
			t.Fatal("management deadline not selected")
		}
		if !s.adapterPlanMu.TryLock() {
			t.Fatal("failed response leaked operation lock")
		}
		s.adapterPlanMu.Unlock()
	}
	if len(s.adapterPlans) != 0 {
		t.Fatal("failed response prepared a plan")
	}
	after, err := store.TailAudit(100)
	if err != nil || len(before) != len(after) {
		t.Fatal("response failure started a transaction")
	}
}

func TestAdapterManagementBusyAndCanceledDoNotStart(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, route := range []string{"preview", "install", "uninstall", "recover"} {
		for _, busy := range []bool{true, false} {
			r := loopbackRequest("POST", "/v1/adapter/"+route, managementBody(route))
			r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
			if busy {
				s.adapterPlanMu.Lock()
			} else {
				ctx, cancel := context.WithCancel(r.Context())
				cancel()
				r = r.WithContext(ctx)
			}
			w := httptest.NewRecorder()
			done := make(chan struct{})
			go func() { s.Handler().ServeHTTP(w, r); close(done) }()
			select {
			case <-done:
			case <-time.After(10 * time.Second):
				if busy {
					s.adapterPlanMu.Unlock()
				}
				<-done
				t.Fatal("operation queued instead of returning")
			}
			want := 408
			if busy {
				s.adapterPlanMu.Unlock()
				want = 429
				if w.Header().Get("Retry-After") != "1" {
					t.Fatal("busy retry guidance missing")
				}
			}
			if w.Code != want {
				t.Fatalf("%s: got %d want %d", route, w.Code, want)
			}
		}
	}
	if len(s.adapterPlans) != 0 {
		t.Fatal("busy/canceled operation prepared a plan")
	}
}

func TestAdapterManagementDeadlineDoesNotChangeOrdinaryRoute(t *testing.T) {
	s, _ := newServer(t, "block")
	r := loopbackRequest("GET", "/v1/status", nil)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder()}
	s.Handler().ServeHTTP(w, r)
	if !w.deadline.IsZero() {
		t.Fatal("ordinary API acquired management deadline")
	}
	var body map[string]any
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &body) != nil {
		t.Fatal("ordinary API failed")
	}
}

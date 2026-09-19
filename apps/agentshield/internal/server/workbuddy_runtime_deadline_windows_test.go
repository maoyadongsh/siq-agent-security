package server

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestWorkBuddyRuntimeRealHTTPDeadline(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, route := range []string{"enroll", "decide", "observe"} {
		for _, legacy := range []bool{true, false} {
			t.Run(route+map[bool]string{true: "/old-disconnect", false: "/response"}[legacy], func(t *testing.T) {
				h := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					time.Sleep(100 * time.Millisecond)
					if legacy {
						w = legacyAdapterResponse{w}
					}
					switch route {
					case "enroll":
						s.runtimeSessionEnroll(w, r)
					case "decide":
						s.decide(w, r)
					case "observe":
						s.observe(w, r)
					}
				}))
				h.Config.WriteTimeout = 25 * time.Millisecond
				h.Start()
				defer h.Close()
				body := `{"platform":"workbuddy","session_id":"deadline-fixture","tool":"Read","tool_call_id":"deadline-fixture"}`
				if route == "enroll" {
					body = `{"schema_version":"local-runtime-session-enroll/v1","session_id":"deadline-fixture"}`
				}
				req, _ := http.NewRequest("POST", h.URL, strings.NewReader(body))
				req.Header.Set("Authorization", "Bearer invalid-fixture")
				client := h.Client()
				client.Timeout = 10 * time.Second
				res, err := client.Do(req)
				if legacy {
					if err == nil {
						res.Body.Close()
						t.Fatal("old socket deadline returned a response")
					}
					return
				}
				if err != nil {
					t.Fatal(err)
				}
				defer res.Body.Close()
				raw, err := io.ReadAll(res.Body)
				if err != nil || len(raw) == 0 {
					t.Fatalf("missing response: %s %v", raw, err)
				}
				// A longer response deadline must never authenticate the fixture or allow it.
				if route == "enroll" && res.StatusCode != 401 {
					t.Fatal(res.StatusCode)
				}
				if route == "decide" && !strings.Contains(string(raw), `"action":"deny"`) {
					t.Fatalf("authority bypass: %s", raw)
				}
			})
		}
	}
}

func TestWorkBuddyRuntimeResponseFailureDoesNotWrite(t *testing.T) {
	s, store := newServer(t, "block")
	before, _ := store.TailAudit(100)
	receiptsBefore, _ := s.d.Chain.Read()
	for _, cancel := range []bool{false, true} {
		for _, route := range []string{"enroll", "decide", "observe"} {
			body := map[string]any{"platform": "workbuddy", "session_id": "fixture", "tool": "Read"}
			if route == "enroll" {
				body = map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "fixture"}
			}
			r := loopbackRequest("POST", "/", body)
			r.Header.Set("Authorization", "Bearer fixture")
			if cancel {
				ctx, stop := context.WithCancel(r.Context())
				stop()
				r = r.WithContext(ctx)
			}
			w := &importDeadlineWriter{ResponseRecorder: httptest.NewRecorder(), failure: errors.New("private socket")}
			switch route {
			case "enroll":
				s.runtimeSessionEnroll(w, r)
			case "decide":
				s.decide(w, r)
			case "observe":
				s.observe(w, r)
			}
			want := 503
			if cancel {
				want = 408
			}
			if w.Code != want || strings.Contains(w.Body.String(), "private") {
				t.Fatalf("%s: %d %s", route, w.Code, w.Body.String())
			}
		}
	}
	after, _ := store.TailAudit(100)
	receiptsAfter, _ := s.d.Chain.Read()
	if len(after) != len(before) || len(receiptsAfter) != len(receiptsBefore) {
		t.Fatal("failed response preparation changed audit or receipts")
	}
}

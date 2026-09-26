//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

type scheduleReadTransport func(*http.Request) (*http.Response, error)

func (f scheduleReadTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestScheduleRetirementRequiresMatchingOnlineRevocation(t *testing.T) {
	for _, mode := range []string{"revoked", "active", "pending", "zero-revision", "unknown", "changed-intent", "wrong-origin", "canceled"} {
		t.Run(mode, func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			journal, err := prepareScheduleJournal(state, raw, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			path, _ := scheduleJournalPath()
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			body := discoveryScheduleSnapshot{Schema: "edge-discovery-schedule-intent/v1", Intent: raw,
				Digest: journal.Request.IntentDigest, Status: "revoked", Revision: 2}
			switch mode {
			case "active":
				body.Status = "active"
			case "pending":
				body.Status, body.Revision = "pending_confirmation", 0
			case "zero-revision":
				body.Revision = 0
			case "unknown":
				body.Status = "expired"
			case "changed-intent":
				intent, _ := parseDiscoverySchedule(raw)
				intent.MaxRuns++
				body.Intent, _ = json.Marshal(intent)
				body.Digest, _ = intent.digest()
			}
			response, _ := json.Marshal(body)
			client := newAuthedClient(state)
			calls := 0
			client.http.Transport = scheduleReadTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.Method != http.MethodGet || r.URL.String() != state.ControlPlaneURL+"/edge/v1/discovery-schedules/"+journal.Request.ScheduleID {
					t.Fatal("retirement verification attempted a write or changed target")
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(response)), Header: make(http.Header)}, nil
			})
			if mode == "wrong-origin" {
				client.base = "https://different.invalid"
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "canceled" {
				cancel()
			}
			result, err := client.verifyRevokedSchedule(ctx, state, journal)
			if (err == nil) != (mode == "revoked") {
				t.Fatalf("unexpected revocation verification for %s: %v", mode, err)
			}
			if mode == "revoked" && (result.Status != "revoked" || result.Revision != 2 || result.IntentDigest != journal.Request.IntentDigest) {
				t.Fatal("verified result changed")
			}
			wantCalls := 1
			if mode == "wrong-origin" || mode == "canceled" {
				wantCalls = 0
			}
			if calls != wantCalls {
				t.Fatalf("requests=%d, want %d", calls, wantCalls)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("verification changed local confirmation")
			}
		})
	}
}

func TestScheduleFetchStrictReadOnly(t *testing.T) {
	state, intent, _ := scheduleFixture(t)
	digest, _ := intent.digest()
	for _, mode := range []string{"valid", "digest", "active", "revision", "duplicate", "extra", "redirect", "denied"} {
		t.Run(mode, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "GET" || r.URL.Path != "/edge/v1/discovery-schedules/"+intent.ID || r.Header.Get("X-Edge-Identity") != state.DeviceIdentity || r.Header.Get("Authorization") != "Bearer synthetic-secret" {
					t.Error("wrong read request")
				}
				if mode == "redirect" {
					w.Header().Set("Location", "/must-not-follow")
					w.WriteHeader(302)
					return
				}
				if mode == "denied" {
					w.WriteHeader(404)
					return
				}
				body := map[string]any{"schema_version": "edge-discovery-schedule-intent/v1", "intent": intent, "intent_digest": digest, "status": "pending_confirmation", "revision": 0}
				switch mode {
				case "digest":
					body["intent_digest"] = strings.Repeat("f", 64)
				case "active":
					body["status"] = "active"
				case "revision":
					body["revision"] = 1
				case "extra":
					body["extra"] = true
				}
				raw, _ := json.Marshal(body)
				if mode == "duplicate" {
					raw = append([]byte(`{"revision":0,`), raw[1:]...)
				}
				w.Write(raw)
			}))
			defer server.Close()
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: state.DeviceIdentity, Secret: "synthetic-secret"})
			raw, err := client.fetchDiscoverySchedule(context.Background(), intent.ID)
			if (err == nil) != (mode == "valid") || calls != 1 {
				t.Fatalf("mode=%s err=%v calls=%d", mode, err, calls)
			}
			if mode == "valid" {
				parsed, err := parseDiscoverySchedule(raw)
				if err != nil || *parsed != intent {
					t.Fatal("intent changed")
				}
			}
			if _, err := client.fetchDiscoverySchedule(context.Background(), "../other"); err == nil || calls != 1 {
				t.Fatal("invalid ID requested")
			}
		})
	}
}

package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestScheduleConfirmationTransportStrictResponses(t *testing.T) {
	for _, mode := range []string{"valid", "id", "digest", "status", "revision", "missing", "extra", "duplicate", "case", "null", "oversized", "trailing", "unauthorized", "conflict", "failure"} {
		t.Run(mode, func(t *testing.T) {
			state, schedule, now := scheduleFixture(t)
			body, err := prepareDiscoveryScheduleConfirmation(state, schedule, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "POST" || r.URL.Path != "/edge/v1/discovery-schedules/confirm" ||
					r.Header.Get("X-Edge-Identity") != body.Identity || r.Header.Get("Authorization") != "Bearer synthetic-secret" {
					t.Error("wrong request")
				}
				var received DiscoveryScheduleConfirmation
				if json.NewDecoder(r.Body).Decode(&received) != nil || received != body {
					t.Error("request changed")
				}
				result := map[string]any{"schema_version": "enterprise-discovery-schedule-state/v1", "schedule_id": body.ScheduleID,
					"status": "active", "revision": 1, "intent_digest": body.IntentDigest}
				switch mode {
				case "id":
					result["schedule_id"] = "eds-" + strings.Repeat("b", 32)
				case "digest":
					result["intent_digest"] = strings.Repeat("f", 64)
				case "status":
					result["status"] = "pending_confirmation"
				case "revision":
					result["revision"] = 0
				case "missing":
					delete(result, "revision")
				case "extra":
					result["secret"] = "synthetic-upstream-secret"
				case "case":
					delete(result, "status")
					result["STATUS"] = "active"
				case "null":
					result["revision"] = nil
				case "unauthorized":
					w.WriteHeader(401)
					return
				case "conflict":
					w.WriteHeader(409)
					return
				case "failure":
					w.WriteHeader(503)
					io.WriteString(w, "synthetic-upstream-secret")
					return
				case "oversized":
					io.WriteString(w, strings.Repeat(" ", 4097))
					return
				}
				raw, _ := json.Marshal(result)
				if mode == "duplicate" {
					raw = []byte(strings.TrimSuffix(string(raw), "}") + `,"revision":1}`)
				}
				if mode == "trailing" {
					raw = append(raw, []byte(` {}`)...)
				}
				w.Write(raw)
			}))
			defer server.Close()
			body.Origin = server.URL
			signer, _ := NewSignerFromSeed(state.SignerSeed)
			payload, _ := body.signedBytes()
			body.Signature, _ = signer.Sign(payload)
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: body.Identity, Secret: "synthetic-secret"})
			result, err := client.ConfirmDiscoverySchedule(context.Background(), body)
			if mode == "valid" {
				if err != nil || result == nil {
					t.Fatal("valid result denied", err)
				}
			} else {
				if err != errDiscoverySchedule || result != nil {
					t.Fatal("unsafe response accepted or error leaked")
				}
			}
			if calls != 1 {
				t.Fatal("implicit retry")
			}
		})
	}
}

func TestScheduleTransportNoRedirectOrForeignOrigin(t *testing.T) {
	state, schedule, now := scheduleFixture(t)
	body, _ := prepareDiscoveryScheduleConfirmation(state, schedule, 0, true, now)
	targetCalls, calls := 0, 0
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { targetCalls++ }))
	defer target.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; http.Redirect(w, r, target.URL, 307) }))
	defer server.Close()
	client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: body.Identity, Secret: "synthetic-secret"})
	if _, err := client.ConfirmDiscoverySchedule(context.Background(), body); err == nil || calls != 0 {
		t.Fatal("foreign origin sent")
	}
	body.Origin = server.URL
	if _, err := client.ConfirmDiscoverySchedule(context.Background(), body); err == nil || calls != 1 || targetCalls != 0 {
		t.Fatal("redirect followed")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := client.ConfirmDiscoverySchedule(ctx, body); err == nil || calls != 1 {
		t.Fatal("cancelled request sent")
	}
}

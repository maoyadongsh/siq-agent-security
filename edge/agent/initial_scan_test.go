package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"
)

func TestInitialScanHeartbeatSequence(t *testing.T) {
	for _, scenario := range []string{"success", "legacy", "measurement_failure", "heartbeat_failure", "initial_retry", "cancel"} {
		t.Run(scenario, func(t *testing.T) {
			s, _ := consentFixture(t)
			if scenario == "legacy" {
				s = &State{}
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			var order []string
			attempts := 0
			now := time.Unix(0, 0)
			beat := initialScanHeartbeatWithClock(s, func(context.Context, *State) (map[string]any, error) {
				order = append(order, "measure")
				if scenario == "measurement_failure" {
					return nil, errors.New("invalid")
				}
				return map[string]any{"connectors": []string{"hermes"}}, nil
			}, func(context.Context, map[string]any) error {
				order = append(order, "heartbeat")
				if scenario == "heartbeat_failure" {
					return errors.New("offline")
				}
				if scenario == "cancel" {
					cancel()
				}
				return nil
			}, func(context.Context, *State) error {
				order = append(order, "initial")
				attempts++
				if scenario == "initial_retry" && attempts == 1 {
					return errors.New("lost response")
				}
				return nil
			}, func() time.Time { return now })
			for i := 0; i < 3; i++ {
				_ = beat(ctx)
				now = now.Add(30 * time.Second)
			}
			want := 0
			if scenario == "success" {
				want = 1
			}
			if scenario == "initial_retry" {
				want = 2
			}
			if attempts != want {
				t.Fatalf("initial calls %d want %d", attempts, want)
			}
			if scenario == "success" && !reflect.DeepEqual(order, []string{"measure", "heartbeat", "initial", "measure", "heartbeat", "measure", "heartbeat"}) {
				t.Fatal(order)
			}
		})
	}
}

func TestInitialScanFailureBackoffDoesNotDelayHealthyHeartbeats(t *testing.T) {
	state, _ := consentFixture(t)
	now := time.Unix(0, 0)
	start := now
	beats := 0
	var attempts []int
	succeed := false
	beat := initialScanHeartbeatWithClock(state, func(context.Context, *State) (map[string]any, error) {
		return map[string]any{"connectors": []string{"hermes"}}, nil
	}, func(context.Context, map[string]any) error {
		beats++
		return nil
	}, func(_ context.Context, got *State) error {
		if got != state {
			t.Fatal("retry replaced confirmed state")
		}
		attempts = append(attempts, int(now.Sub(start)/(30*time.Second)))
		if succeed {
			return nil
		}
		return errors.New("upstream scheduling unavailable")
	}, func() time.Time { return now })
	for tick := 0; tick < 122; tick++ {
		if tick == 91 {
			succeed = true
		}
		if err := beat(context.Background()); err != nil {
			t.Fatalf("healthy heartbeat incorrectly backs off: %v", err)
		}
		now = now.Add(30 * time.Second)
	}
	if beats != 122 || !reflect.DeepEqual(attempts, []int{0, 1, 3, 7, 15, 31, 61, 91}) {
		t.Fatalf("heartbeats=%d scan ticks=%v", beats, attempts)
	}
}

func TestInitialScanHTTPContract(t *testing.T) {
	for _, scenario := range []string{"created", "replay", "bad_schema", "missing_replay", "missing_tasks", "bad_id", "unavailable"} {
		t.Run(scenario, func(t *testing.T) {
			s, _ := consentFixture(t)
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.URL.Path != "/edge/v1/initial-scan" || r.Method != "POST" {
					t.Error("wrong request")
				}
				var body struct {
					Schema string          `json:"schema_version"`
					Plan   json.RawMessage `json:"plan"`
				}
				if json.NewDecoder(r.Body).Decode(&body) != nil || body.Schema != "edge-initial-scan/v1" {
					t.Error("invalid body")
				}
				digest, _ := compactPlanDigest(body.Plan)
				if digest != s.DiscoveryPlanSHA256 {
					t.Error("plan changed")
				}
				if scenario == "unavailable" {
					w.WriteHeader(503)
					return
				}
				out := map[string]any{"schema_version": "edge-initial-scan-result/v1", "task_ids": []string{"tsk_fixture"}, "replay": scenario == "replay"}
				switch scenario {
				case "bad_schema":
					out["schema_version"] = "other"
				case "missing_replay":
					delete(out, "replay")
				case "missing_tasks":
					delete(out, "task_ids")
				case "bad_id":
					out["task_ids"] = []string{"bad"}
				}
				_ = json.NewEncoder(w).Encode(out)
			}))
			defer server.Close()
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL})
			err := client.RequestInitialScan(context.Background(), s)
			if calls != 1 {
				t.Fatal("unexpected retry")
			}
			if (err == nil) != (scenario == "created" || scenario == "replay") {
				t.Fatalf("result: %v", err)
			}
		})
	}
}

func TestInitialSkillScanHTTPContract(t *testing.T) {
	for _, scenario := range []string{"created", "skills_only", "missing_skill_task", "legacy_response", "glob_scope"} {
		t.Run(scenario, func(t *testing.T) {
			state, _ := consentFixture(t)
			var plan map[string]any
			if err := json.Unmarshal(state.DiscoveryPlan, &plan); err != nil {
				t.Fatal(err)
			}
			connector := plan["connectors"].([]any)[0].(map[string]any)
			connector["id"] = "directory"
			root := "/fixture/skills"
			if scenario == "glob_scope" {
				root += "/*"
			}
			connector["scope"] = map[string]any{"roots": []string{root}, "include": []string{"AGENTS.md", "SKILL.md"}}
			if scenario == "skills_only" {
				connector["scope"] = map[string]any{"roots": []string{root}, "include": []string{"SKILL.md"}}
			}
			state.DiscoveryPlan, _ = json.Marshal(plan)
			state.DiscoveryPlanSHA256, _ = compactPlanDigest(state.DiscoveryPlan)
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				calls++
				var body struct {
					Schema string          `json:"schema_version"`
					Plan   json.RawMessage `json:"plan"`
				}
				if json.NewDecoder(req.Body).Decode(&body) != nil || body.Schema != "edge-initial-scan/v2" {
					t.Error("skill initial version missing")
				}
				digest, _ := compactPlanDigest(body.Plan)
				if digest != state.DiscoveryPlanSHA256 {
					t.Error("confirmed plan changed")
				}
				schema := "edge-initial-scan-result/v2"
				ids := []string{"tsk_agents", "tsk_skills"}
				if scenario == "missing_skill_task" || scenario == "skills_only" {
					ids = ids[:1]
				}
				if scenario == "legacy_response" {
					schema = "edge-initial-scan-result/v1"
				}
				json.NewEncoder(w).Encode(map[string]any{"schema_version": schema, "task_ids": ids, "replay": false})
			}))
			defer server.Close()
			err := NewClient(ClientConfig{ControlPlaneURL: server.URL}).RequestInitialScan(context.Background(), state)
			if (err == nil) != (scenario == "created" || scenario == "skills_only") {
				t.Fatal("unexpected confirmation", err)
			}
			if scenario == "glob_scope" && calls != 0 {
				t.Fatal("unsupported scope sent")
			}
		})
	}
}

package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"regexp"
	"slices"
	"strings"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

var errInitialScan = errors.New("initial_scan_unconfirmed; retry the original confirmed plan")
var initialTaskID = regexp.MustCompile(`^tsk_[A-Za-z0-9_-]{1,60}$`)

func (c *Client) RequestInitialScan(ctx context.Context, state *State) error {
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return errInitialScan
	}
	p, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil || p.EnvironmentID != state.EnvironmentID || p.ControlPlaneOrigin != state.ControlPlaneURL {
		return errInitialScan
	}
	schema, resultSchema, taskCount := "edge-initial-scan/v1", "edge-initial-scan-result/v1", len(p.Connectors)
	for _, connector := range p.Connectors {
		if connector.ID == "directory" && slices.Contains(connector.Scope.Include, "SKILL.md") {
			if len(connector.Scope.Roots) > 16 {
				return errInitialScan
			}
			for _, root := range connector.Scope.Roots {
				if strings.Contains(root, "*") {
					return errInitialScan
				}
			}
			schema, resultSchema = "edge-initial-scan/v2", "edge-initial-scan-result/v2"
			if len(connector.Scope.Include) > 1 {
				taskCount++
			}
		}
	}
	var out struct {
		Schema  string   `json:"schema_version"`
		TaskIDs []string `json:"task_ids"`
		Replay  *bool    `json:"replay"`
	}
	body := struct {
		Schema string          `json:"schema_version"`
		Plan   json.RawMessage `json:"plan"`
	}{schema, state.DiscoveryPlan}
	// The server has a durable per-device key; do not invent a new plan on error.
	if c.do(ctx, http.MethodPost, "/edge/v1/initial-scan", body, &out, 0) != nil {
		return errInitialScan
	}
	if out.Schema != resultSchema || out.Replay == nil || len(out.TaskIDs) != taskCount {
		return errInitialScan
	}
	seen := map[string]bool{}
	for _, id := range out.TaskIDs {
		if !initialTaskID.MatchString(id) || seen[id] {
			return errInitialScan
		}
		seen[id] = true
	}
	return nil
}

// Called only from the single heartbeat goroutine. The local flag is an
// optimization; durable replay protection lives on the authenticated server.
func initialScanHeartbeat(state *State, measure func(context.Context, *State) (map[string]any, error), send func(context.Context, map[string]any) error, initial func(context.Context, *State) error) func(context.Context) error {
	return initialScanHeartbeatWithClock(state, measure, send, initial, time.Now)
}

func initialScanHeartbeatWithClock(state *State, measure func(context.Context, *State) (map[string]any, error), send func(context.Context, map[string]any) error, initial func(context.Context, *State) error, now func() time.Time) func(context.Context) error {
	requested := false
	var retryAt time.Time
	retryDelay := 30 * time.Second
	return func(ctx context.Context) error {
		return heartbeatWithMeasurement(ctx, state, measure, func(ctx context.Context, caps map[string]any) error {
			if err := send(ctx, caps); err != nil {
				return err
			}
			if ctx.Err() != nil {
				return ctx.Err()
			}
			connectors, ok := caps["connectors"].([]string)
			if requested || !ok || len(connectors) == 0 || now().Before(retryAt) {
				return nil
			}
			if err := initial(ctx, state); err != nil {
				if ctx.Err() != nil {
					return ctx.Err()
				}
				// Discovery scheduling failure must not back off a healthy heartbeat.
				// Keep the original plan and retry separately; never log upstream details.
				retryAt = now().Add(retryDelay)
				retryDelay = min(retryDelay*2, 15*time.Minute)
				log.Print("edge initial scan unconfirmed; bounded retry scheduled")
				return nil
			}
			requested = true
			return nil
		})
	}
}

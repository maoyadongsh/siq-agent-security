//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func skillExecutionFixture(t *testing.T) (*State, *Task) {
	t.Helper()
	state, task, _, _ := skillJournalFixture(t)
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	var plan map[string]any
	if json.Unmarshal(raw, &plan) != nil {
		t.Fatal("plan fixture")
	}
	plan["control_plane_origin"] = state.ControlPlaneURL
	connector := plan["connectors"].([]any)[0].(map[string]any)
	connector["id"] = "directory"
	connector["scope"] = map[string]any{"roots": []string{"/fixture/skills"}, "include": []string{"SKILL.md"}}
	state.DiscoveryPlan, err = json.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	state.DiscoveryPlanSHA256, err = compactPlanDigest(state.DiscoveryPlan)
	if err != nil {
		t.Fatal(err)
	}
	return state, task
}

func TestSkillExecutionRetriesOriginalJournalWithoutRescan(t *testing.T) {
	state, task := skillExecutionFixture(t)
	collected, uploaded := 0, 0
	var originalBody, originalDigest string
	collect := func(context.Context, json.RawMessage) (protocol.SkillCollection, error) {
		collected++
		return skillUploadFixture(), nil
	}
	upload := func(_ context.Context, body json.RawMessage, digest string) error {
		uploaded++
		stored, err := loadSkillUpload(state, task)
		if err != nil || stored == nil || string(stored.Body) != string(body) {
			t.Fatal("network preceded durable journal")
		}
		if uploaded == 1 {
			originalBody, originalDigest = string(body), digest
			return errors.New("lost acknowledgement")
		}
		if string(body) != originalBody || digest != originalDigest {
			t.Fatal("retry changed signed batch")
		}
		return nil
	}
	if result, err := executeSkillUpload(context.Background(), state, task, collect, upload); err == nil || result != nil {
		t.Fatal("unconfirmed upload counted as complete")
	}
	// A new invocation must not need a collector, even after process-local state is gone.
	result, err := executeSkillUpload(context.Background(), state, task, nil, upload)
	if err != nil || result.Observations != 1 || result.Digest != originalDigest || collected != 1 || uploaded != 2 {
		t.Fatal("journal replay failed", err)
	}
	// A previous upload cannot override a subsequently changed confirmation.
	state.DiscoveryPlan = nil
	if _, err := executeSkillUpload(context.Background(), state, task, nil, upload); err == nil || uploaded != 2 {
		t.Fatal("missing consent bypassed on replay")
	}
}

func TestSkillExecutionDenialNeverCallsCollectorOrUpload(t *testing.T) {
	for _, scenario := range []string{"legacy", "digest", "root", "signature", "journal_corrupt", "cancelled"} {
		t.Run(scenario, func(t *testing.T) {
			state, task := skillExecutionFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			switch scenario {
			case "legacy":
				state.DiscoveryPlan = nil
				state.DiscoveryPlanSHA256 = ""
			case "digest":
				state.DiscoveryPlanSHA256 = "invalid"
			case "root":
				state.DiscoveryPlan = json.RawMessage(strings.Replace(string(state.DiscoveryPlan), "/fixture/skills", "/fixture/other", 1))
				state.DiscoveryPlanSHA256, _ = compactPlanDigest(state.DiscoveryPlan)
			case "signature":
				task.Signature = "invalid"
			case "journal_corrupt":
				dir, _ := StateDir()
				dir = filepath.Join(dir, "skill_uploads")
				if err := os.Mkdir(dir, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(dir, task.TaskID+".json"), []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "cancelled":
				cancel()
			}
			collect := func(context.Context, json.RawMessage) (protocol.SkillCollection, error) {
				t.Fatal("denial called collector")
				return protocol.SkillCollection{}, nil
			}
			upload := func(context.Context, json.RawMessage, string) error { t.Fatal("denial called network"); return nil }
			if _, err := executeSkillUpload(ctx, state, task, collect, upload); err == nil {
				t.Fatal("denial accepted")
			}
		})
	}
}

func TestSkillExecutionIncompleteCollectionNeverUploads(t *testing.T) {
	for _, scenario := range []string{"truncated", "read_error", "cancelled", "consent_removed"} {
		t.Run(scenario, func(t *testing.T) {
			state, task := skillExecutionFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			collect := func(context.Context, json.RawMessage) (protocol.SkillCollection, error) {
				collection := skillUploadFixture()
				switch scenario {
				case "truncated":
					collection.Truncated = true
				case "read_error":
					return collection, errors.New("private fixture diagnostic")
				case "cancelled":
					cancel()
				case "consent_removed":
					state.DiscoveryPlan = nil
				}
				return collection, nil
			}
			upload := func(context.Context, json.RawMessage, string) error {
				t.Fatal("incomplete or revoked collection uploaded")
				return nil
			}
			if outcome, err := executeSkillUpload(ctx, state, task, collect, upload); err == nil || outcome != nil {
				t.Fatal("incomplete collection accepted")
			}
			dir, _ := StateDir()
			if _, err := os.Stat(filepath.Join(dir, "skill_uploads", task.TaskID+".json")); !os.IsNotExist(err) {
				t.Fatal("failed collection journaled as uploadable")
			}
		})
	}
}

package runtimecheck

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

func TestRuntimeCheckContractFixtures(t *testing.T) {
	fx := newManagerFixture(t)
	var attachment Attached
	fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
		var err error
		attachment, err = fx.m.Attach(Attach{SchemaVersion: "local-runtime-check-attach/v1", ID: r.id, InstanceID: testInstance, AgentID: agentID(r.id), SessionID: "synthetic-native-session"}, nonce)
		if err != nil {
			return err
		}
		return fx.runProbes(r, nonce, p, true)
	}
	plan, started := startFixture(t, fx)
	result := awaitResult(t, fx.m, plan.ID)
	// Close joins the worker before reading its attachment output.
	if err := fx.m.Close(context.Background()); err != nil {
		t.Fatal(err)
	}
	if result.Status != "passed" || result.ID != plan.ID || attachment.ID != plan.ID || result.Snapshot != plan.Snapshot {
		t.Fatal("incoherent runtime outputs")
	}
	// Normalize only nondeterministic identities/times; all fields and statuses
	// originate from the real controller and signed receipt engine in this unit fixture.
	id := "rc-" + strings.Repeat("0", 32)
	plan.ID, plan.Digest, plan.Snapshot, plan.ExpiresAt = id, strings.Repeat("0", 64), strings.Repeat("1", 64), "2026-09-10T09:05:00Z"
	attachment.ID = id
	normalize := func(r Result) Result {
		r.ID, r.Snapshot, r.StartedAt, r.ExpiresAt = id, plan.Snapshot, "2026-09-10T09:00:00Z", "2026-09-10T09:02:00Z"
		if r.FinishedAt != nil {
			v := "2026-09-10T09:00:10Z"
			r.FinishedAt = &v
		}
		for i := range r.ReceiptIDs {
			r.ReceiptIDs[i] = fmt.Sprintf("receipt-%d", i+1)
		}
		return r
	}
	result, started = normalize(result), normalize(started)
	values := map[string]any{
		"runtime-check-plan.json": plan, "runtime-check-started.json": started, "runtime-check-passed.json": result,
		"runtime-check-attached.json": attachment,
		"runtime-check-list.json":     map[string]any{"schema_version": "local-runtime-check-list/v1", "items": []Result{result}},
	}
	for name, value := range values {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		file := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(file, raw, 0644); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(file)
		if err != nil || string(expected) != string(raw) {
			t.Fatalf("contract drift: %s", name)
		}
	}
}

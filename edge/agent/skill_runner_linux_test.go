//go:build linux

package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestSkillRunnerJournalRecovery(t *testing.T) {
	for _, empty := range []bool{false, true} {
		t.Run(map[bool]string{false: "one", true: "zero"}[empty], func(t *testing.T) {
			state, task := skillExecutionFixture(t)
			var body json.RawMessage
			var digest string
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				calls++
				got, _ := io.ReadAll(req.Body)
				if req.URL.Path != "/edge/v1/skill-batches" || string(got) != string(body) {
					t.Error("wrong route or changed original signed batch")
				}
				if calls == 1 {
					w.WriteHeader(503)
					return
				}
				json.NewEncoder(w).Encode(map[string]any{"schema_version": "enterprise-skill-upload-result/v1", "task_id": task.TaskID, "batch_digest": digest, "observations": 0, "idempotent": true})
			}))
			defer server.Close()
			state.DiscoveryPlan = json.RawMessage(strings.Replace(string(state.DiscoveryPlan), state.ControlPlaneURL, server.URL, 1))
			state.ControlPlaneURL = server.URL
			state.DiscoveryPlanSHA256, _ = compactPlanDigest(state.DiscoveryPlan)
			signer, _ := NewSignerFromSeed(state.SignerSeed)
			collection := skillUploadFixture()
			if empty {
				collection.Observations = []protocol.SkillObservation{}
			}
			request, err := confirmedSkillRequest(state, task)
			if err != nil {
				t.Fatal(err)
			}
			body, digest, err = prepareSkillUpload(task.TaskID, request.Scope, collection, signer)
			if err != nil {
				t.Fatal(err)
			}
			if err := saveSkillUpload(state, task, body, digest); err != nil {
				t.Fatal(err)
			}
			// No stage exists: successful retry must use the journal, never rescan.
			t.Setenv("SIQ_CONNECTOR_BIN_DIR", "")
			runner := &Runner{State: state, Client: NewClient(ClientConfig{ControlPlaneURL: server.URL})}
			if receipt, err := runner.Execute(context.Background(), task); err == nil || receipt != nil {
				t.Fatal("uncertain upload produced terminal receipt")
			}
			receipt, err := runner.Execute(context.Background(), task)
			if err != nil || receipt.Status != "success" || receipt.SkillBatchDigest != digest || receipt.SkillObservationCount == nil || *receipt.SkillObservationCount != len(collection.Observations) || calls != 2 {
				t.Fatal("recovery failed", receipt, err, calls)
			}
			if reused, err := LookupExecReuse(task); err != nil || reused != nil {
				t.Fatal("skill entered legacy completion ledger", err)
			}
			if ids, err := ListPendingReceiptTaskIDs(); err != nil || len(ids) != 0 {
				t.Fatal("skill entered unconfirmed receipt drain", err)
			}
			state.DiscoveryPlan = nil
			if receipt, err := runner.Execute(context.Background(), task); err == nil || receipt != nil || calls != 2 {
				t.Fatal("replay bypassed current consent")
			}
		})
	}
}

func TestSkillRunnerRequiresVerifiedStageBeforeCollection(t *testing.T) {
	state, task := skillExecutionFixture(t)
	t.Setenv("SIQ_CONNECTOR_BIN_DIR", "")
	runner := &Runner{State: state, Client: NewClient(ClientConfig{ControlPlaneURL: "https://fixture.invalid"})}
	if receipt, err := runner.Execute(context.Background(), task); err == nil || receipt != nil {
		t.Fatal("unverified installation executed")
	}
	if record, err := loadSkillUpload(state, task); err != nil || record != nil {
		t.Fatal("unverified collector generated upload", err)
	}
}

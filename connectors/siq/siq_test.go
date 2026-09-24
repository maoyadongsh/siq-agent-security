package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

func hashRef(character string) string { return "sha256:" + strings.Repeat(character, 64) }
func digest(character string) string  { return strings.Repeat(character, 64) }

func eventFixture(eventID, eventType, status string) businessSecurityEvent {
	terminal := eventType == "agent_run.terminal"
	return businessSecurityEvent{
		SchemaVersion: eventSchema,
		EventID:       eventID,
		EventType:     eventType,
		OccurredAt:    "2026-09-21T12:00:00Z",
		Producer:      eventProducer,
		Identity: hashIdentity{
			TenantRef:  hashRef("a"),
			SubjectRef: hashRef("b"),
		},
		Authorization: authorizationProjection{
			ScopeTenantRef:              hashRef("a"),
			DataScopeRefSHA256:          digest("c"),
			AuthorizationSnapshotSHA256: digest("d"),
			DataClassification:          "confidential_local",
		},
		Execution: executionProjection{
			RunRef:           hashRef("e"),
			SessionRef:       hashRef("f"),
			Profile:          "siq_analysis",
			RuntimeTarget:    "openshell",
			SandboxRef:       hashRef("1"),
			ModelRouteSHA256: digest("2"),
		},
		Audit: auditProjection{
			CorrelationRef: hashRef("e"),
		},
		Lifecycle: lifecycleProjection{
			Status:                    status,
			RuntimeTerminalConfirmed:  terminal,
			ChildrenTerminalConfirmed: terminal,
			WriteQuiesced:             terminal,
		},
	}
}

func privateDir(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "security-export")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	return dir
}

func writeEvent(t *testing.T, dir string, event businessSecurityEvent) string {
	t.Helper()
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, event.EventID+".json")
	if err := os.WriteFile(path, append(data, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestCollectProducesCorrelatedCandidateAndNoPermissionFacts(t *testing.T) {
	dir := privateDir(t)
	writeEvent(t, dir, eventFixture("sev_"+strings.Repeat("3", 64), "agent_run.admitted", "admitted"))
	terminal := eventFixture("sev_"+strings.Repeat("4", 64), "agent_run.terminal", "succeeded")
	auditRef := hashRef("5")
	terminal.Audit.AuditTraceRef = &auditRef
	writeEvent(t, dir, terminal)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if batch.Truncated || len(batch.Candidates) != 1 || len(batch.Evidence) != 2 {
		t.Fatalf("unexpected batch: candidates=%d evidence=%d truncated=%v", len(batch.Candidates), len(batch.Evidence), batch.Truncated)
	}
	if len(batch.PermissionFacts) != 0 {
		t.Fatal("connector must not assert effective or inferred permissions")
	}
	candidate := batch.Candidates[0]
	if candidate.SourceType != "siq_hub" || candidate.Framework != "siq-hermes-openshell" {
		t.Fatalf("unexpected candidate identity: %+v", candidate)
	}
	if candidate.Attributes["event_types"] != "agent_run.admitted,agent_run.terminal" {
		t.Fatalf("unexpected event types: %q", candidate.Attributes["event_types"])
	}
	if candidate.Attributes["lifecycle_statuses"] != "admitted,succeeded" {
		t.Fatalf("unexpected statuses: %q", candidate.Attributes["lifecycle_statuses"])
	}
	if candidate.Attributes["event_count"] != "2" || len(candidate.EvidenceIDs) != 2 {
		t.Fatal("candidate must reference every event evidence")
	}
	for _, evidence := range batch.Evidence {
		if evidence.SubjectRef == nil || *evidence.SubjectRef != candidate.CandidateID {
			t.Fatalf("orphan evidence: %+v", evidence)
		}
		if evidence.Classification != "confidential" || evidence.Signature != "" {
			t.Fatalf("unexpected evidence projection: %+v", evidence)
		}
	}
	if !strings.HasPrefix(batch.Cursor, "siq-cursor:") || batch.Cursor != lastCursor {
		t.Fatalf("unexpected cursor: %q", batch.Cursor)
	}
	encoded, _ := json.Marshal(batch)
	for _, forbidden := range []string{"Bearer ", "prompt", "response", "tenant_id", "user_id"} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatalf("connector output contains forbidden field/value %q", forbidden)
		}
	}
}

func TestParseRejectsCrossTenantAndCorrelationMismatch(t *testing.T) {
	for name, mutate := range map[string]func(*businessSecurityEvent){
		"cross tenant": func(event *businessSecurityEvent) {
			event.Authorization.ScopeTenantRef = hashRef("9")
		},
		"wrong correlation": func(event *businessSecurityEvent) {
			event.Audit.CorrelationRef = hashRef("8")
		},
	} {
		t.Run(name, func(t *testing.T) {
			event := eventFixture("sev_"+strings.Repeat("6", 64), "agent_run.admitted", "admitted")
			mutate(&event)
			data, _ := json.Marshal(event)
			if _, err := parseEvent(data); !errors.Is(err, errInvalidEvent) {
				t.Fatalf("expected invalid event, got %v", err)
			}
		})
	}
}

func TestParseRejectsRawFieldsDuplicateKeysAndTrailingJSON(t *testing.T) {
	event := eventFixture("sev_"+strings.Repeat("7", 64), "agent_run.admitted", "admitted")
	data, _ := json.Marshal(event)
	withRawField := append(data[:len(data)-1], []byte(`,"tenant_id":"raw-tenant","prompt":"raw prompt"}`)...)
	if _, err := parseEvent(withRawField); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("raw identity/content fields accepted: %v", err)
	}
	duplicate := []byte(strings.Replace(string(data), `"producer":"siq-research-api"`, `"producer":"siq-research-api","producer":"evil"`, 1))
	if _, err := parseEvent(duplicate); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("duplicate key accepted: %v", err)
	}
	if _, err := parseEvent(append(data, []byte(` {}`)...)); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("trailing JSON accepted: %v", err)
	}
}

func TestSuccessfulTerminalMustBeWriteQuiesced(t *testing.T) {
	event := eventFixture("sev_"+strings.Repeat("8", 64), "agent_run.terminal", "succeeded")
	event.Lifecycle.ChildrenTerminalConfirmed = false
	event.Lifecycle.WriteQuiesced = false
	data, _ := json.Marshal(event)
	if _, err := parseEvent(data); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("non-quiesced successful event accepted: %v", err)
	}
}

func TestAdmissionCannotClaimAnyTerminalConfirmation(t *testing.T) {
	event := eventFixture("sev_"+strings.Repeat("9", 64), "agent_run.admitted", "admitted")
	event.Lifecycle.ChildrenTerminalConfirmed = true
	data, _ := json.Marshal(event)
	if _, err := parseEvent(data); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("admission with terminal child confirmation accepted: %v", err)
	}
}

func TestScopeAndFilesystemBoundaries(t *testing.T) {
	if errs := validateScope(nil); len(errs) == 0 {
		t.Fatal("empty scope accepted")
	}
	if errs := validateScope(&protocol.Scope{Roots: []string{"/"}}); len(errs) == 0 {
		t.Fatal("filesystem root accepted")
	}
	dir := privateDir(t)
	if errs := validateScope(&protocol.Scope{Roots: []string{dir}}); len(errs) != 0 {
		t.Fatalf("private root rejected: %v", errs)
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if errs := validateScope(&protocol.Scope{Roots: []string{dir}}); len(errs) == 0 {
		t.Fatal("non-private export root accepted")
	}
}

func TestCollectRejectsSymlinkAndHardlinkEvents(t *testing.T) {
	realDir := privateDir(t)
	event := eventFixture("sev_"+strings.Repeat("a", 64), "agent_run.admitted", "admitted")
	real := writeEvent(t, realDir, event)

	symlinkDir := privateDir(t)
	if err := os.Symlink(real, filepath.Join(symlinkDir, event.EventID+".json")); err != nil {
		t.Fatal(err)
	}
	if _, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{symlinkDir}}, Limits: defaultLimits()}); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("symlink event accepted: %v", err)
	}

	hardlinkDir := privateDir(t)
	hardlink := filepath.Join(hardlinkDir, event.EventID+".json")
	if err := os.Link(real, hardlink); err != nil {
		t.Fatal(err)
	}
	if _, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{hardlinkDir}}, Limits: defaultLimits()}); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("hard-linked event accepted: %v", err)
	}
}

func TestByteLimitTruncatesWithoutPartialEvidence(t *testing.T) {
	dir := privateDir(t)
	writeEvent(t, dir, eventFixture("sev_"+strings.Repeat("b", 64), "agent_run.admitted", "admitted"))
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 10, MaxBytes: 32},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Fatalf("partial event escaped byte limit: %+v", batch)
	}
}

func TestMaliciousStringsAreRejectedAndNeverExecuted(t *testing.T) {
	dir := privateDir(t)
	marker := filepath.Join(t.TempDir(), "executed")
	event := eventFixture("sev_"+strings.Repeat("c", 64), "agent_run.admitted", "admitted")
	event.Execution.Profile = "$(touch " + marker + ")"
	writeEvent(t, dir, event)
	if _, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{dir}}, Limits: defaultLimits()}); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("malicious profile accepted: %v", err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("event content was executed")
	}
}

func TestDispatchCapabilitiesAndErrors(t *testing.T) {
	caps := capabilities()
	if caps.NetworkAccess || caps.Version != connectorVersion || len(caps.Objects) != 1 {
		t.Fatalf("unexpected capabilities: %+v", caps)
	}
	response := dispatch(&protocol.Request{ID: "x", Op: "unknown", Params: json.RawMessage(`{}`)})
	if response.OK || response.Error == nil || response.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("unsupported operation response invalid: %+v", response)
	}
	response = dispatch(&protocol.Request{ID: "x", Op: protocol.OpHealth, Params: json.RawMessage(`{}`)})
	if !response.OK {
		t.Fatalf("health failed: %+v", response)
	}
}

func TestEventTimestampMustBeRFC3339(t *testing.T) {
	event := eventFixture("sev_"+strings.Repeat("d", 64), "agent_run.admitted", "admitted")
	event.OccurredAt = time.Now().Format("2006/01/02")
	data, _ := json.Marshal(event)
	if _, err := parseEvent(data); !errors.Is(err, errInvalidEvent) {
		t.Fatalf("invalid timestamp accepted: %v", err)
	}
}

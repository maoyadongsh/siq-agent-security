package server

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// Real Windows state and production HTTP stores, with controlled fixture
// writes. No desktop/model runs here and no tool success is an effect proof.
func TestWorkBuddyWindowsFileEvidence(t *testing.T) {
	for _, mode := range []string{"block", "warn"} {
		for _, written := range []bool{true, false} {
			name := "missing-output"
			if written {
				name = "written-output"
			}
			t.Run(mode+"/"+name, func(t *testing.T) {
				f := newWindowsAuthorityHTTPFixtureForPlatform(t, mode, false, "workbuddy")
				contract, err := f.s.intents.Get(f.intentID)
				if err != nil || contract.Validate() != nil {
					t.Fatal("valid v4 precondition", err)
				}
				rawContract, err := json.Marshal(contract)
				if err != nil {
					t.Fatal(err)
				}
				var legacyFields map[string]any
				if err := json.Unmarshal(rawContract, &legacyFields); err != nil {
					t.Fatal(err)
				}
				legacyFields["effect_requirements"] = []any{}
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/intents", f.s.bootAdmin, legacyFields, 400)
				grantBefore, _, err := f.st.GetGrantWithSeq(f.grantID)
				if err != nil {
					t.Fatal(err)
				}
				grantRaw, err := json.Marshal(grantBefore)
				if err != nil {
					t.Fatal(err)
				}
				call, err := runtimeidentity.WorkBuddyCallID("windows-authority-http", "output-fixture")
				if err != nil {
					t.Fatal(err)
				}
				decisionBody := f.decision("write_file", call, f.output)
				d := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, decisionBody, 200)
				if d["action"] != "allow" || d["authority_status"] != "valid" {
					t.Fatal(d)
				}
				scope := provenance.Scope{Platform: f.platform, SessionID: f.session, AgentID: f.agent, TaskID: f.taskID}
				source := effectevidence.Source{Type: "host_observer", SourceID: "controlled-host", Independence: "host_independent"}
				issueObserver := func() map[string]any {
					return windowsAuthorityHTTP(t, f.s, "POST", "/v1/effect-observers", f.s.bootAdmin,
						map[string]any{"source": source, "scope": scope, "expires_in": 600}, 201)
				}
				firstObserver := issueObserver()
				observer := firstObserver["token"].(string)
				content := []byte("controlled WorkBuddy Windows output")
				sum := sha256.Sum256(content)
				expected := hex.EncodeToString(sum[:])
				body := map[string]any{"observation_id": "workbuddy-file", "action_id": d["action_id"], "decision_receipt_id": d["receipt_id"], "path": f.output, "expected_digest": expected, "max_bytes": 1024}
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations", f.credential, body, 403)
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations", observer, body, 201)
				pending, err := f.s.effects.GetPendingFile("workbuddy-file")
				if err != nil || pending.SchemaVersion != "file-observation-pending/v2" || pending.IntentID != f.intentID || pending.Before.Exists || pending.Before.FilesystemProfile != "windows-local-drive/v1" {
					t.Fatal("begin did not preserve verified Windows authority", pending, err)
				}
				if written {
					if err := os.WriteFile(f.output, content, 0600); err != nil {
						t.Fatal(err)
					}
				}
				// Both cases claim success through the actual WorkBuddy Post endpoint.
				// The missing-output case deliberately has no filesystem write.
				decisionBody["result"] = "synthetic tool reports successful output"
				observed := windowsAuthorityHTTP(t, f.s, "POST", "/v1/observe", f.credential, decisionBody, 200)
				if observed["action_id"] != d["action_id"] {
					t.Fatal("Post changed call correlation")
				}
				f.s.observerMu.Lock()
				delete(f.s.fileObservations, "workbuddy-file")
				f.s.observerMu.Unlock()
				other := issueObserver()
				newObserver := other["token"].(string)
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations", newObserver, body, 409)
				recovery := map[string]any{"schema_version": "file-observation-recovery-request/v2", "path": filepath.Join(f.root, "Wrong.txt"), "observation_id": "workbuddy-file", "observer_id": other["observer_id"], "expected_owner": tokenDigest(observer)}
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 400)
				owner, err := f.s.effects.PendingFileOwner(pending.ID, time.Now())
				if err != nil || owner != pending.OwnerDigest {
					t.Fatal("wrong path changed recovery owner", err)
				}
				recovery["path"] = f.output
				takeover := windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 200)
				repeated := windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 200)
				if takeover["recovery"].(map[string]any)["signature"] != repeated["recovery"].(map[string]any)["signature"] || takeover["expires_at"] != pending.ExpiresAt {
					t.Fatal("recovery rewrote history or extended observation deadline")
				}
				restarted := windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations", newObserver, body, 200)
				if restarted["before"].(map[string]any)["exists"] != false {
					t.Fatal("recovery resampled before")
				}
				finish := map[string]any{"path": f.output}
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations/workbuddy-file/finish", observer, finish, 403)
				response := windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations/workbuddy-file/finish", newObserver, finish, 201)
				record, err := f.s.effects.Get("workbuddy-file", time.Now())
				if err != nil || record.Verify(f.s.d.Key.Public(), time.Now()) != nil || record.SchemaVersion != "effect-evidence-record/v2" || record.FileObservation == nil || record.FileObservation.Before != pending.Before || record.Evidence.ActionID != d["action_id"] {
					t.Fatal("result not bound to original signed snapshot and call", record, err)
				}
				wantResult, wantState := "unexpected", "failed"
				if written {
					wantResult, wantState = "expected", "completed"
				}
				if record.Evidence.Result != wantResult || record.Evidence.ExecutionState != wantState || record.Evidence.Coverage != "partial" || record.Evidence.Source != source {
					t.Fatal("tool success replaced independent file facts", record)
				}
				complete := windowsAuthorityHTTP(t, f.s, "GET", "/v1/tasks/"+f.taskID+"/completion", f.s.bootAdmin, nil, 200)
				if complete["status"] != "unknown" {
					t.Fatal("instance permission acquired task effect requirements", complete)
				}
				if written {
					if err := os.Remove(f.output); err != nil {
						t.Fatal(err)
					}
				} else if _, err := os.Stat(f.output); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("missing-output fixture unexpectedly created output", err)
				}
				// Simulate a crash after publication but before updating the cache.
				f.s.observerMu.Lock()
				cached := f.s.fileObservations["workbuddy-file"]
				cached.Completed = false
				f.s.fileObservations["workbuddy-file"] = cached
				f.s.observerMu.Unlock()
				retry := windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations/workbuddy-file/finish", newObserver, finish, 200)
				if retry["signature"] != response["signature"] {
					t.Fatal("completed retry resampled or rewrote evidence")
				}
				body["observation_id"] = "revoked-file"
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations", newObserver, body, 201)
				if _, err := f.s.runtimeIdentities.Revoke(f.identityID, "component-operator"); err != nil {
					t.Fatal(err)
				}
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observations/revoked-file/finish", newObserver, finish, 400)
				recovery["observation_id"], recovery["expected_owner"] = "revoked-file", tokenDigest(newObserver)
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 400)
				historical, err := f.s.effects.Get("workbuddy-file", time.Now())
				if err != nil || historical.Signature != record.Signature {
					t.Fatal("revocation changed completed history", err)
				}
				grantAfter, _, err := f.st.GetGrantWithSeq(f.grantID)
				if err != nil {
					t.Fatal(err)
				}
				afterRaw, err := json.Marshal(grantAfter)
				if err != nil || !bytes.Equal(grantRaw, afterRaw) {
					t.Fatal("observation workflow changed Grant", err)
				}
			})
		}
	}
}

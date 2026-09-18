package server

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type windowsObservationFixture struct {
	s                              *Server
	g                              *grant.Grant
	identity                       runtimeidentity.Record
	binding                        intent.Binding
	path, root, observer, expected string
	body                           map[string]any
	scope                          provenance.Scope
	source                         effectevidence.Source
}

// This fixture exercises signed component stores and HTTP handlers. It does
// not start Hermes, OpenClaw or WorkBuddy and is not native-desktop evidence.
func newWindowsObservationFixture(t *testing.T) windowsObservationFixture {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.Initialize(w, 47611); err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ActivateWindowsProfile(true, "file-observation-component-test"); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{3}, 32))
	root := filepath.Join(t.TempDir(), "Approved")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", root)
	if err != nil {
		t.Fatal(err)
	}
	instance := "hi-" + strings.Repeat("1", 32)
	agent, err := runtimeidentity.AgentID(instance)
	if err != nil {
		t.Fatal(err)
	}
	adm := admission.Admission{AdmissionID: "adm-observation", ContentHash: strings.Repeat("a", 64), Verdict: "admit", DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "write_file"}, Effect: "allow", State: "declared", Authority: "skill_manifest"}}}
	result, err := grant.Build(adm, grant.Options{Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}, Now: time.Now(), Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, _, err := grant.PrepareWindowsResources(result.Grant, grant.ResourceEdit{Tools: []string{"write_file"}, Network: []grant.NetworkPatch{}, Models: []string{}, Filesystem: grant.FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{canonical}}}, true, key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.Approve(g, grant.Approval{ActorType: "human", ActorID: "component-operator", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano), Channel: "console"}, key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, key)
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(st.Dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	lookup := func(platform, agentID string) *grant.Grant {
		if platform == "hermes" && agentID == agent {
			return &g
		}
		return nil
	}
	engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: lookup, EnforcementMode: "block"})
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(Deps{Store: st, Engine: engine, Chain: chain, Pack: pack, Key: key, Token: token, Version: "test", Mode: "block", Home: t.TempDir(), Binary: "agentshield-test", ListenHost: "127.0.0.1", ListenPort: 47611, PairingCode: testPairingCode})
	if err != nil {
		t.Fatal(err)
	}
	s.bootAdmin, err = s.RedeemPairing(testPairingCode)
	if err != nil {
		t.Fatal(err)
	}
	s.intents, err = intent.Open(st.Dir, key, func(id string) (*grant.Grant, int, error) {
		if id != g.GrantID {
			return nil, 0, os.ErrNotExist
		}
		return &g, 3, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	s.runtimeIdentities, err = runtimeidentity.OpenWithInstances(st.Dir, key, s.intents, func(id string) (runtimeidentity.InstanceInfo, error) {
		if id != instance {
			return runtimeidentity.InstanceInfo{}, runtimeidentity.ErrUnavailable
		}
		return runtimeidentity.InstanceInfo{Platform: "hermes", Root: root}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	identity, err := s.runtimeIdentities.Create(runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v2", ConfirmFilesystemProfile: true, InstanceID: instance, GrantID: g.GrantID, ExpectedGrantRevision: 3, ActorID: "component-operator", SessionTTLSeconds: 600})
	if err != nil {
		t.Fatal(err)
	}
	credentialPath, err := s.runtimeIdentities.CredentialPath(identity.IdentityID)
	if err != nil {
		t.Fatal(err)
	}
	credential, err := os.ReadFile(credentialPath)
	if err != nil {
		t.Fatal(err)
	}
	binding, err := s.runtimeIdentities.Enroll(string(credential), "file-profile-session")
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine, err = receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: lookup, EnforcementMode: "block", IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(s.intents), ProvenanceCheck: s.provenance.MatchParameters})
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "Output.txt")
	d, err := s.d.Engine.Decide(receipt.Request{Platform: "hermes", SessionID: binding.SessionID, AgentID: agent, Tool: "write_file", ToolCallID: "component-write", Params: map[string]any{"path": path}})
	if err != nil || d.Action != "allow" {
		t.Fatal("controlled approved write rejected", d, err)
	}
	scope := provenance.Scope{Platform: "hermes", SessionID: binding.SessionID, AgentID: agent, TaskID: binding.TaskID}
	source := effectevidence.Source{Type: "host_observer", SourceID: "component-fixture", Independence: "host_independent"}
	observer := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": source, "scope": scope, "expires_in": 600}, 201)["token"].(string)
	sum := sha256.Sum256([]byte("expected Windows file"))
	expected := hex.EncodeToString(sum[:])
	body := map[string]any{"observation_id": "windows-observation", "action_id": d.Receipt.ActionID, "decision_receipt_id": d.Receipt.ReceiptID, "path": path, "expected_digest": expected, "max_bytes": 1024}
	return windowsObservationFixture{s: s, g: &g, identity: identity, binding: binding, path: path, root: root, observer: observer, expected: expected, body: body, scope: scope, source: source}
}

func (f windowsObservationFixture) replacementObserver(t *testing.T) (string, map[string]any) {
	t.Helper()
	other := effectCall(t, f.s, "POST", "/v1/effect-observers", f.s.bootAdmin, map[string]any{"source": f.source, "scope": f.scope, "expires_in": 600}, 201)
	return other["token"].(string), map[string]any{"schema_version": "file-observation-recovery-request/v2", "path": f.path, "observation_id": "windows-observation", "observer_id": other["observer_id"], "expected_owner": tokenDigest(f.observer)}
}

func TestWindowsFileObservationHTTPRecoveryKeepsOriginalSnapshot(t *testing.T) {
	f := newWindowsObservationFixture(t)
	f.body["filesystem_profile"] = "posix/v1"
	effectCall(t, f.s, "POST", "/v1/file-observations", f.observer, f.body, 400)
	delete(f.body, "filesystem_profile")
	before := effectCall(t, f.s, "POST", "/v1/file-observations", f.observer, f.body, 201)["before"].(map[string]any)
	if before["exists"] != false || before["schema_version"] != "file-snapshot/v2" {
		t.Fatal("wrong Windows begin snapshot", before)
	}
	if err := os.WriteFile(f.path, []byte("expected Windows file"), 0600); err != nil {
		t.Fatal(err)
	}
	other, recovery := f.replacementObserver(t)
	recovery["path"] = filepath.Join(f.root, "Wrong.txt")
	effectCall(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 400)
	owner, err := f.s.effects.PendingFileOwner("windows-observation", time.Now())
	if err != nil || owner != tokenDigest(f.observer) {
		t.Fatal("wrong-path recovery changed owner", err)
	}
	recovery["path"] = f.path
	delete(recovery, "schema_version")
	delete(recovery, "path")
	effectCall(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 400)
	recovery["schema_version"], recovery["path"] = "file-observation-recovery-request/v2", f.path
	effectCall(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 200)
	restarted := effectCall(t, f.s, "POST", "/v1/file-observations", other, f.body, 200)
	if restarted["before"].(map[string]any)["exists"] != false {
		t.Fatal("recovery replaced original before snapshot")
	}
	record := effectCall(t, f.s, "POST", "/v1/file-observations/windows-observation/finish", other, map[string]any{"path": f.path}, 201)
	if record["schema_version"] != "effect-evidence-record/v2" || record["file_observation"].(map[string]any)["result"] != "expected" {
		t.Fatal("Windows result not persisted", record)
	}
	if _, err := f.s.runtimeIdentities.Revoke(f.identity.IdentityID, "component-operator"); err != nil {
		t.Fatal(err)
	}
	if _, err := f.s.effects.Get("windows-observation", time.Now()); err != nil {
		t.Fatal("revocation erased historical evidence", err)
	}
}

func TestWindowsFileObservationExpiredSignedIntentRejected(t *testing.T) {
	f := newWindowsObservationFixture(t)
	c, err := f.s.intents.Get(f.binding.IntentID)
	if err != nil {
		t.Fatal(err)
	}
	// Issue a structurally valid, already expired signed contract without any
	// sleeps or system-clock changes. The profile helper must reject it before
	// an otherwise unrelated live binding could be consulted.
	c.IntentID, c.TaskID = "int-expired-observation", "task-expired-observation"
	c.Digest, c.Signature, c.SigningSchema = "", "", ""
	c.IssuedAt = time.Now().Add(-2 * time.Hour).UTC().Format(time.RFC3339Nano)
	c.ValidFrom = c.IssuedAt
	c.ExpiresAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	issued, err := f.s.intents.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	a := effectevidence.Action{IntentID: issued.IntentID, IntentDigest: issued.Digest, TaskID: issued.TaskID, Platform: issued.Agent.Platform, AgentID: issued.Agent.ID, SessionID: f.binding.SessionID}
	if _, err := f.s.fileActionProfile(a); err == nil {
		t.Fatal("expired signed Windows authority accepted")
	}
}

func TestWindowsFileObservationRejectsRevokedAuthorityAndParent(t *testing.T) {
	for _, kind := range []string{"identity", "intent", "binding", "grant", "parent"} {
		t.Run(kind, func(t *testing.T) {
			f := newWindowsObservationFixture(t)
			effectCall(t, f.s, "POST", "/v1/file-observations", f.observer, f.body, 201)
			_, recovery := f.replacementObserver(t)
			var err error
			switch kind {
			case "identity":
				_, err = f.s.runtimeIdentities.Revoke(f.identity.IdentityID, "component-operator")
			case "intent":
				_, err = f.s.intents.RevokeIntent(f.binding.IntentID, f.binding.IntentDigest)
			case "binding":
				_, err = f.s.intents.RevokeBinding(f.binding.BindingID, f.binding.IntentDigest)
			case "grant":
				var revoked grant.Grant
				revoked, err = grant.Revoke(*f.g, f.s.d.Key)
				if err == nil {
					*f.g = revoked
				}
			case "parent":
				err = os.Rename(f.root, f.root+"-old")
				if err == nil {
					err = os.Mkdir(f.root, 0700)
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(f.path, []byte("expected Windows file"), 0600); err != nil {
				t.Fatal(err)
			}
			effectCall(t, f.s, "POST", "/v1/file-observations/windows-observation/finish", f.observer, map[string]any{"path": f.path}, 400)
			effectCall(t, f.s, "POST", "/v1/file-observation-recoveries", f.s.bootAdmin, recovery, 400)
			if _, err := f.s.effects.Get("windows-observation", time.Now()); !errors.Is(err, effectevidence.ErrNotFound) {
				t.Fatal("rejected effect published a record", err)
			}
			owner, err := f.s.effects.PendingFileOwner("windows-observation", time.Now())
			if err != nil || owner != tokenDigest(f.observer) {
				t.Fatal("rejected recovery changed owner", err)
			}
		})
	}
}

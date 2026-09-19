package runtimeidentity

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Signed stores and real NTFS facts, with an explicit committed-Grant resolver
// fixture. This is component evidence, not execution by a desktop host.
func TestWindowsIdentityGrantIntentDecisionChain(t *testing.T) {
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 49124)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "Approved")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(root, "Input.txt")
	if err := os.WriteFile(file, []byte("controlled input"), 0600); err != nil {
		t.Fatal(err)
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", root)
	if err != nil {
		t.Fatal(err)
	}
	instance := "hi-" + strings.Repeat("4", 32)
	agent, _ := AgentID(instance)
	adm := admission.Admission{AdmissionID: "adm-windows-chain", ContentHash: strings.Repeat("a", 64), Verdict: "admit", DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "read_file"}, Effect: "allow", State: "declared", Authority: "skill_manifest"}}}
	built, err := grant.Build(adm, grant.Options{Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}, Now: time.Now(), Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, _, err := grant.PrepareWindowsResources(built.Grant, grant.ResourceEdit{Tools: []string{"read_file", "write_file"}, Network: []grant.NetworkPatch{}, Models: []string{}, Filesystem: grant.FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{canonical}}}, true, key)
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
	intents, err := intent.Open(st.Dir, key, func(id string) (*grant.Grant, int, error) {
		if id != g.GrantID {
			return nil, 0, os.ErrNotExist
		}
		return &g, 3, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	currentRoot := root
	s, err := OpenWithInstances(st.Dir, key, intents, func(id string) (InstanceInfo, error) {
		if id != instance {
			return InstanceInfo{}, ErrUnavailable
		}
		return InstanceInfo{Platform: "hermes", Root: currentRoot}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	req := CreateRequest{SchemaVersion: "local-runtime-identity-create/v2", ConfirmFilesystemProfile: true, InstanceID: instance, GrantID: g.GrantID, ExpectedGrantRevision: 3, ActorID: "component-operator", SessionTTLSeconds: 600}
	if _, err := s.Create(req); !errors.Is(err, ErrProfileState) {
		t.Fatal("identity bypassed activation", err)
	}
	if _, err := st.ActivateWindowsProfile(true, "identity-chain-test"); err != nil {
		t.Fatal(err)
	}
	bad := req
	bad.ConfirmFilesystemProfile = false
	if _, err := s.Create(bad); err == nil {
		t.Fatal("identity issued without confirmation")
	}
	bad = req
	bad.SchemaVersion = "local-runtime-identity-create/v1"
	bad.ConfirmFilesystemProfile = false
	if _, err := s.Create(bad); err == nil {
		t.Fatal("legacy identity bound a Windows Grant")
	}
	bad = req
	bad.ExpectedGrantRevision = 2
	if _, err := s.Create(bad); err == nil {
		t.Fatal("identity ignored preview revision")
	}
	currentRoot = filepath.Join(root, "MissingProfile")
	if _, err := s.Create(req); err == nil {
		t.Fatal("unverified instance directory accepted")
	}
	currentRoot = root
	for _, dir := range []string{"runtime-identities", "runtime-identity-secrets"} {
		entries, e := os.ReadDir(filepath.Join(st.Dir, dir))
		if e != nil || len(entries) != 0 {
			t.Fatal("refused identity published files", dir, e)
		}
	}
	r, credential := create(t, s, req)
	binding, err := s.Enroll(credential, "windows-chain-session")
	if err != nil {
		t.Fatal(err)
	}
	c, readBinding, err := intents.ResolveBinding("hermes", binding.SessionID, agent)
	if err != nil || c == nil || readBinding == nil || c.SchemaVersion != "intent/v4" || binding.SchemaVersion != "intent-grant-binding/v2" || binding.GrantRef.PermissionDigestSchema != "grant-permissions/v2" || r.FilesystemProfile != c.FilesystemProfile {
		t.Fatal("profile chain broke", err)
	}
	if _, err := s.AuthorizeSession(credential, "hermes", agent, binding.SessionID); err != nil {
		t.Fatal(err)
	}
	if err := s.VerifySessionAuthority(*c, binding.SessionID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AuthorizeSession(credential, "hermes", agent, "other-session"); err == nil {
		t.Fatal("cross-session authority borrowed")
	}
	// A signed old Intent cannot select a newer permission interpretation.
	legacy := *c
	legacy.SchemaVersion = "intent/v2"
	legacy.AuthorityKind = ""
	legacy.FilesystemProfile = ""
	legacy.IntentID = "int-legacy-cross-profile"
	legacy.SigningSchema = ""
	legacy.Digest = ""
	legacy.Signature = ""
	issued, err := intents.Issue(legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := intents.BindWithReference(intent.Binding{Platform: "hermes", AgentID: agent, SessionID: "cross-profile", IntentID: issued.IntentID}, r.GrantRef); err == nil {
		t.Fatal("old Intent borrowed new Grant")
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(st.Dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"block", "warn", "audit_only"} {
		engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, EnforcementMode: mode, IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(intents), Grants: func(platform, id string) *grant.Grant { return &g }})
		if err != nil {
			t.Fatal(err)
		}
		allowed, err := engine.Decide(receipt.Request{Platform: "hermes", SessionID: binding.SessionID, AgentID: agent, Tool: "read_file", ToolCallID: "read-" + mode, Params: map[string]any{"path": file}})
		if err != nil || allowed.Action != "allow" {
			t.Fatal("approved Windows read rejected", mode, allowed, err)
		}
		alias, err := engine.Decide(receipt.Request{Platform: "hermes", SessionID: binding.SessionID, AgentID: agent, Tool: "read_file", ToolCallID: "alias-" + mode, Params: map[string]any{"path": file + " "}})
		if err != nil || alias.Action != "deny" || alias.Receipt.AuthorityStatus != "invalid" {
			t.Fatal("invalid path became advisory", mode, alias, err)
		}
	}
	if _, err := s.Revoke(r.IdentityID, "component-operator"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AuthorizeSession(credential, "hermes", agent, binding.SessionID); err == nil {
		t.Fatal("revoked identity still authorized")
	}
	if err := s.VerifySessionAuthority(*c, binding.SessionID); err == nil {
		t.Fatal("observer borrowed revoked identity")
	}
	if _, err := intents.Get(c.IntentID); err != nil {
		t.Fatal("revocation erased historical Intent", err)
	}
}

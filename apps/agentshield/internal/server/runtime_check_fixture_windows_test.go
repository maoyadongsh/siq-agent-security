package server

import (
	"bytes"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func newRuntimeCheckHTTPServer(t *testing.T) *Server {
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
	if _, err := st.ActivateWindowsProfile(true, "runtime-check-component-test"); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{3}, 32))
	pack, _ := rulepack.Builtin()
	chain, err := receipt.OpenChain(st.Dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: st.ActiveGrant, EnforcementMode: "block", Version: "test"})
	if err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	bin := filepath.Join(home, "agentshield-test")
	if err := os.WriteFile(bin, []byte("test program fixture"), 0700); err != nil {
		t.Fatal(err)
	}
	s, err := New(Deps{Store: st, Engine: engine, Chain: chain, Pack: pack, Key: key, Token: token, Version: "test", Mode: "block", Home: home, Binary: bin, ListenHost: "127.0.0.1", ListenPort: 47611, PairingCode: testPairingCode})
	if err != nil {
		t.Fatal(err)
	}
	s.bootAdmin, err = s.RedeemPairing(testPairingCode)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func runtimeCheckHTTPFixtureTarget(t *testing.T, target adapterinstall.RuntimeTarget) adapterinstall.RuntimeTarget {
	t.Helper()
	facts, err := runtimepath.InspectWindows(target.ProfilePath, false)
	if err != nil {
		t.Fatal(err)
	}
	target.FilesystemProfile = runtimeaction.FilesystemWindowsLocalDriveV1
	target.RootIdentityDigest, err = facts.IdentityDigest()
	if err != nil {
		t.Fatal(err)
	}
	return target
}

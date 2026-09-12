package state

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"strings"
	"testing"
)

func launchAgentFixture(t *testing.T) (*Store, *Writer, *signing.Key, []byte) {
	t.Helper()
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = w.Release() })
	if _, err := st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	plist, err := os.ReadFile("../../testdata/contracts/launch-agent.sample.plist")
	if err != nil {
		t.Fatal(err)
	}
	return st, w, key, plist
}
func TestLaunchAgentOwnershipAndRecovery(t *testing.T) {
	st, w, key, plist := launchAgentFixture(t)
	if _, err := st.PrepareLaunchAgent(nil, key, plist); err == nil {
		t.Fatal("missing writer accepted")
	}
	record, err := st.PrepareLaunchAgent(w, key, plist)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(st.Dir, record.Label+".plist")
	if _, err := st.PrepareLaunchAgent(w, key, plist); err != nil {
		t.Fatal("repeat preparation", err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err := st.VerifyLaunchAgent(key, plist); err == nil {
		t.Fatal("missing configuration verified")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("read verification repaired file")
	}
	if _, err := st.PrepareLaunchAgent(w, key, plist); err != nil {
		t.Fatal("recover missing configuration", err)
	}
	if err := os.WriteFile(path, []byte("user changes"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := st.PrepareLaunchAgent(w, key, plist); err == nil {
		t.Fatal("drift overwritten")
	}
	if raw, _ := os.ReadFile(path); string(raw) != "user changes" {
		t.Fatal("user data changed")
	}
	if _, err := st.VerifyLaunchAgent(key, plist); err == nil {
		t.Fatal("drift verified")
	}
	if _, err := st.VerifyUserService(key, plist); err == nil {
		t.Fatal("macOS record accepted as Linux ownership")
	}
}
func TestLaunchAgentRejectsUnownedAndClonedRecords(t *testing.T) {
	st, w, key, plist := launchAgentFixture(t)
	expected, err := st.expectedLaunchAgent(key, plist)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(st.Dir, expected.Label+".plist")
	if err := os.WriteFile(path, plist, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := st.PrepareLaunchAgent(w, key, plist); err == nil {
		t.Fatal("unowned configuration adopted")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	record, err := st.PrepareLaunchAgent(w, key, plist)
	if err != nil {
		t.Fatal(err)
	}
	clone, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"local-instance.json", "launch-agent.json", record.Label + ".plist"} {
		raw, err := os.ReadFile(filepath.Join(st.Dir, name))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(clone.Dir, name), raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := clone.VerifyLaunchAgent(key, plist); err == nil {
		t.Fatal("cloned directory accepted")
	}
	record.PlistSHA256 = strings.Repeat("0", 64)
	raw, _ := json.Marshal(record)
	if err := os.WriteFile(filepath.Join(st.Dir, "launch-agent.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := st.VerifyLaunchAgent(key, plist); err == nil {
		t.Fatal("tampered signature accepted")
	}
}
func TestLaunchAgentRecordContract(t *testing.T) {
	st, w, key, plist := launchAgentFixture(t)
	r, err := st.PrepareLaunchAgent(w, key, plist)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
		t.Fatal(err)
	}
	r.InstanceID = strings.Repeat("a", 64)
	r.DirectoryID = strings.Repeat("b", 64)
	r.Label = "dev.siq.agent-security." + r.InstanceID
	r.Signature, err = key.SignCanonical(r.unsigned())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-launch-agent-record.json"
	if os.Getenv("SIQ_UPDATE_LAUNCH_AGENT_RECORD_FIXTURE") == "1" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(raw, expected) {
		t.Fatal("contract fixture drift")
	}
}

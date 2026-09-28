package decisionrelay

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWindowsRelayRejectsPOSIXPrivateConfig(t *testing.T) {
	raw, err := jsonMarshal(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	// Parsing remains platform independent; only the POSIX descriptor transport
	// is unavailable. A successful Windows chmod cannot prove private permissions.
	if _, err := ParseConfig(raw); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "relay.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	for _, mode := range []os.FileMode{0600, 0400, 0640} {
		if err := os.Chmod(path, mode); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadConfig(path); err == nil {
			t.Fatal("Windows path claimed POSIX private transport")
		}
		if _, err := LoadConfigFile(file); err == nil {
			t.Fatal("Windows descriptor claimed POSIX private transport")
		}
	}
	if _, err := LoadConfigFile(nil); err == nil {
		t.Fatal("nil descriptor accepted")
	}
}

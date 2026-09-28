//go:build !windows

package decisionrelay

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigFileSupportsPrivilegeDroppedDescriptor(t *testing.T) {
	cfg := testConfig()
	raw, _ := jsonMarshal(cfg)
	dir := t.TempDir()
	path := filepath.Join(dir, "relay.json")
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	loaded, err := LoadConfigFile(file)
	if err != nil || loaded.Binding.RuntimeIdentityID != cfg.Binding.RuntimeIdentityID {
		t.Fatal("descriptor config failed", err)
	}
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfigFile(file); err == nil {
		t.Fatal("non-private descriptor config accepted")
	}
}

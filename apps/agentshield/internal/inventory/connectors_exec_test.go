package inventory

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestConnectorsStartFailureKeepsNative(t *testing.T) {
	home, dir := fakeHome(t), t.TempDir()
	path := filepath.Join(dir, "hermes", "hermes")
	if runtime.GOOS == "windows" {
		path += ".exe"
	}
	write(t, path, "fixed invalid executable fixture\n")
	if err := os.Chmod(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if bin, err := findConnectorBin(dir, "hermes"); err != nil || bin != path {
		t.Fatalf("invalid binary must be found before its loader failure: %q, %v", bin, err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	if err != nil {
		t.Fatal(err)
	}
	rep, err := Run(Options{Home: home, Key: key, ConnectorsDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := byID(rep)["platform:hermes"]; !ok {
		t.Fatal("native inventory dropped on connector start failure")
	}
	if _, ok := byID(rep)["connector:extra"]; ok {
		t.Fatal("failed connector merged a candidate")
	}
	if skipped := strings.Join(rep.Skipped, ","); !strings.Contains(skipped, "connector_failed:hermes") || strings.Contains(skipped, "connector_missing:hermes") {
		t.Fatalf("start failure misclassified: %v", rep.Skipped)
	}
}

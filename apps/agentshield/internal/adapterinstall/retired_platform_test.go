package adapterinstall

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestRetiredPlatformDoesNotReadOrMutateHost(t *testing.T) {
	opts := testOpts(t, "codebuddy")
	path := filepath.Join(opts.Home, ".codebuddy", "settings.json")
	before := []byte(`{"hooks":{"PreToolUse":[]},"user":"keep"}`)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, before, 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CODEBUDDY_CONFIG_DIR", filepath.Dir(path))
	if slices.Contains(Detect(opts.Home), opts.Platform) {
		t.Fatal("retired host discovered")
	}
	for _, action := range []string{"install", "uninstall"} {
		if _, err := Prepare(opts, action); err == nil {
			t.Fatalf("retired %s prepared", action)
		}
	}
	if _, err := Status(opts); err == nil {
		t.Fatal("retired status accepted")
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) {
		t.Fatal("retired host config changed", err)
	}
}

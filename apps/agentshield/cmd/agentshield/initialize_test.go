package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestInitializeCommandAndBareServe(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "new-state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	if err := cmdServe(nil); err == nil || !strings.Contains(err.Error(), "init") {
		t.Fatal("bare serve did not explain initialization")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("bare serve mutated state")
	}
	for _, args := range [][]string{{"--port", "0"}, {"--port", "-1"}, {"--port", "65536"}, {"unexpected"}} {
		if err := cmdInitialize(args, &bytes.Buffer{}); err == nil {
			t.Fatal("invalid initialization accepted")
		}
		if _, err := os.Stat(dir); !os.IsNotExist(err) {
			t.Fatal("invalid initialization mutated state")
		}
	}
	var first, second bytes.Buffer
	if err := cmdInitialize([]string{"--port", "49123"}, &first); err != nil {
		t.Fatal(err)
	}
	if err := cmdInitialize(nil, &second); err != nil {
		t.Fatal(err)
	}
	if first.String() != second.String() {
		t.Fatal("repeated initialization changed result")
	}
	if err := cmdInitialize([]string{"--port", "49124"}, &bytes.Buffer{}); err == nil {
		t.Fatal("port conflict accepted")
	}
}

package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEnrollmentStdinBoundary(t *testing.T) {
	for _, input := range []string{"enr-synthetic\n", "enr-synthetic\r\n", "enr-synthetic"} {
		code, err := readEnrollmentCode(strings.NewReader(input))
		if err != nil || code != "enr-synthetic" {
			t.Fatal("valid bounded code rejected")
		}
	}
	for _, input := range []string{"", " \n", "enr bad\n", strings.Repeat("s", 1025)} {
		code, err := readEnrollmentCode(strings.NewReader(input))
		if err == nil || code != "" || strings.Contains(err.Error(), strings.TrimSpace(input)) && len(input) > 10 {
			t.Fatal("invalid input accepted or echoed")
		}
	}
}
func TestEnrollmentPreservesExistingState(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	p := filepath.Join(dir, "state.json")
	before := []byte("synthetic existing state")
	if err := os.WriteFile(p, before, 0600); err != nil {
		t.Fatal(err)
	}
	err := cmdRegister(context.Background(), []string{"--control-plane", "http://127.0.0.1:1", "--enrollment-code", "synthetic"})
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatal("registration attempted despite existing state", err)
	}
	after, _ := os.ReadFile(p)
	if string(after) != string(before) {
		t.Fatal("existing state changed")
	}
}

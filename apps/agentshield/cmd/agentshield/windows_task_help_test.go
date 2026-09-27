package main

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWindowsTaskHelpIsReadOnlyWithoutCompatibleState(t *testing.T) {
	for _, command := range []struct {
		name string
		run  func([]string, io.Writer) error
	}{
		{"task-start", cmdWindowsTaskStart}, {"task-stop", cmdWindowsTaskStop},
	} {
		for _, flag := range []string{"--help", "-h"} {
			t.Run(command.name+flag, func(t *testing.T) {
				root := t.TempDir()
				dir := filepath.Join(root, "absent-state")
				t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
				var out bytes.Buffer
				if err := checkCommandState(command.name, flag); err != nil {
					t.Fatal(err)
				}
				if err := command.run([]string{flag}, &out); err != nil {
					t.Fatal(err)
				}
				if !strings.Contains(out.String(), "Usage:") || !strings.Contains(out.String(), command.name) {
					t.Fatal("missing command help")
				}
				if _, err := os.Stat(dir); !os.IsNotExist(err) {
					t.Fatal("help initialized state")
				}
				if err := os.Mkdir(dir, 0700); err != nil {
					t.Fatal(err)
				}
				marker := filepath.Join(dir, "state-format.json")
				if err := os.WriteFile(marker, []byte("invalid marker"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := checkCommandState(command.name, flag); err != nil {
					t.Fatal("help blocked by state", err)
				}
				if err := command.run([]string{flag}, &out); err != nil {
					t.Fatal(err)
				}
				if err := checkCommandState(command.name, "--confirm-start"); err == nil {
					t.Fatal("action bypassed state barrier")
				}
				if err := command.run([]string{flag, "--confirm-start"}, &out); err == nil {
					t.Fatal("mixed help/action accepted")
				}
				entries, err := os.ReadDir(dir)
				if err != nil || len(entries) != 1 {
					t.Fatal("help modified state")
				}
			})
		}
	}
}

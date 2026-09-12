package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestUserLoginExactLinkAndInterruptedDisable(t *testing.T) {
	source := filepath.Join(t.TempDir(), "siq.service")
	if err := os.WriteFile(source, []byte("owned"), 0600); err != nil {
		t.Fatal(err)
	}
	registration := filepath.Join(t.TempDir(), "siq.service")
	if err := os.Symlink(source, registration); err != nil {
		t.Skip("symlink unavailable")
	}
	status := "linked-runtime"
	failReload := false
	control := func(args ...string) (string, error) {
		switch args[0] {
		case "show":
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=%s\n", registration, status), nil
		case "daemon-reload":
			if failReload {
				return "", errors.New("reload interrupted")
			}
			status = "linked-runtime"
			if _, err := os.Lstat(loginLinkPath(registration)); err == nil {
				status = "enabled-runtime"
			}
			return "", nil
		default:
			t.Fatalf("unexpected manager mutation %v", args)
			return "", nil
		}
	}
	if err := setUserLogin(control, source, "siq.service", true); err != nil {
		t.Fatal(err)
	}
	if err := setUserLogin(control, source, "siq.service", true); err != nil {
		t.Fatal("enable repeat", err)
	}
	other := filepath.Join(filepath.Dir(loginLinkPath(registration)), "unrelated.service")
	if err := os.WriteFile(other, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	failReload = true
	if err := setUserLogin(control, source, "siq.service", false); err == nil {
		t.Fatal("reload failure hidden")
	}
	failReload = false
	if err := setUserLogin(control, source, "siq.service", false); err != nil {
		t.Fatal("interrupted disable recovery", err)
	}
	if raw, err := os.ReadFile(other); err != nil || string(raw) != "keep" {
		t.Fatal("other entry changed")
	}
	if err := os.WriteFile(loginLinkPath(registration), []byte("user object"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, enable := range []bool{true, false} {
		if err := setUserLogin(control, source, "siq.service", enable); err == nil {
			t.Fatal("unknown entry modified")
		}
	}
}

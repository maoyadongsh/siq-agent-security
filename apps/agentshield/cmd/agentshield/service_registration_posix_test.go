//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

// Directory fsync and these service link formats belong to POSIX backends.
// Windows tests exercise platform refusal and Task Scheduler recovery instead.
func TestLaunchRegistrationExclusiveReuseAndPreservation(t *testing.T) {
	home, source, label := launchRegistrationFixture(t)
	link, err := publishLaunchRegistration(home, source, label)
	if err != nil {
		t.Fatal(err)
	}
	if target, err := os.Readlink(link); err != nil || target != source {
		t.Fatal("wrong registration target", err)
	}
	if _, err := publishLaunchRegistration(home, source, label); err != nil {
		t.Fatal("repeat publication", err)
	}
	{
		info, err := os.Stat(filepath.Dir(link))
		if err != nil || info.Mode().Perm() != 0700 {
			t.Fatal("new directory permissions", err)
		}
	}
	if err := os.Remove(link); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(link, []byte("unrelated user data"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := publishLaunchRegistration(home, source, label); err == nil {
		t.Fatal("unknown file adopted")
	}
	if raw, _ := os.ReadFile(link); string(raw) != "unrelated user data" {
		t.Fatal("user file changed")
	}
}

func TestTeardownResumesAfterRegistrationRemoval(t *testing.T) {
	st, source, _, record := upgradeFixture(t)
	path := filepath.Join(st.Dir, record.UnitName)
	fragment := filepath.Join(t.TempDir(), record.UnitName)
	if err := os.Symlink(path, fragment); err != nil {
		t.Skip("symlinks unavailable")
	}
	active, pid, loaded := "active", "200", true
	reloads := 0
	control := func(args ...string) (string, error) {
		switch args[0] {
		case "show":
			if !loaded {
				return "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\nActiveState=inactive\nMainPID=0\n", nil
			}
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=success\n", fragment, active, pid), nil
		case "stop":
			active, pid = "inactive", "0"
			return "", nil
		case "daemon-reload":
			reloads++
			if reloads == 2 {
				return "", errors.New("injected unregister reload failure")
			}
			if _, err := os.Lstat(fragment); os.IsNotExist(err) {
				loaded = false
			}
			return "", nil
		default:
			t.Fatalf("unexpected teardown action %v", args)
			return "", nil
		}
	}
	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := teardownUserService(st, source, control); err == nil {
		t.Fatal("interrupted removal reported success")
	}
	if _, err := os.Lstat(fragment); !os.IsNotExist(err) {
		t.Fatal("failure did not reach removed registration")
	}
	if err := teardownUserService(st, source, control); err != nil {
		t.Fatal("reload recovery", err)
	}
	if loaded {
		t.Fatal("registration remained")
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || string(after) != string(config) {
		t.Fatal("data changed")
	}
}

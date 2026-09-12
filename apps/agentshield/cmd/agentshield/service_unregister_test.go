package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const absentService = "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\nActiveState=inactive\nMainPID=0\nResult=success\n"

func TestUnregisterExactLinkAndRetry(t *testing.T) {
	for _, interrupted := range []bool{false, true} {
		t.Run(fmt.Sprint(interrupted), func(t *testing.T) {
			dir := t.TempDir()
			source := filepath.Join(dir, "source")
			if err := os.WriteFile(source, []byte("unit"), 0600); err != nil {
				t.Fatal(err)
			}
			link := filepath.Join(dir, "unit.service")
			if !interrupted {
				if err := os.Symlink(source, link); err != nil {
					t.Fatal(err)
				}
			}
			alias := filepath.Join(dir, "user-alias.service")
			if err := os.Symlink(source, alias); err != nil {
				t.Fatal(err)
			}
			reads := 0
			control := func(args ...string) (string, error) {
				if args[0] == "show" {
					reads++
					if reads > 1 {
						return absentService, nil
					}
					return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=inactive\nMainPID=0\nResult=success\n", link), nil
				}
				if args[0] != "daemon-reload" {
					t.Fatal("broad removal attempted")
				}
				return "", nil
			}
			if err := unregisterUserUnit(control, source, "unit.service"); err != nil {
				t.Fatal(err)
			}
			if _, err := os.Lstat(link); !os.IsNotExist(err) {
				t.Fatal("link remains")
			}
			if _, err := os.Lstat(alias); err != nil {
				t.Fatal("unknown alias removed")
			}
			if _, err := os.Stat(source); err != nil {
				t.Fatal("source removed")
			}
			if err := unregisterUserUnit(func(...string) (string, error) { return absentService, nil }, source, "unit.service"); err != nil {
				t.Fatal(err)
			}
		})
	}
}
func TestUnregisterRejectsUnknownAndFailedReload(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(dir, "unit.service")
	if err := os.WriteFile(source, []byte("user data"), 0600); err != nil {
		t.Fatal(err)
	}
	raw := fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked\nActiveState=inactive\nMainPID=0\nResult=success\n", source)
	for _, r := range []string{raw, strings.Replace(raw, "inactive", "active", 1), strings.Replace(raw, "DropInPaths=", "DropInPaths=/override", 1), strings.Replace(raw, "Result=success", "Result=timeout", 1)} {
		if err := unregisterUserUnit(func(args ...string) (string, error) {
			if args[0] != "show" {
				t.Fatal("mutated foreign service")
			}
			return r, nil
		}, source, "unit.service"); err == nil {
			t.Fatal("accepted unknown service")
		}
	}
	target := filepath.Join(dir, "owned")
	if err := os.WriteFile(target, []byte("owned"), 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "unit.service")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	raw = strings.Replace(raw, source, link, 1)
	err := unregisterUserUnit(func(args ...string) (string, error) {
		if args[0] == "show" {
			return raw, nil
		}
		return "", errors.New("reload failure")
	}, target, "unit.service")
	if err == nil {
		t.Fatal("reported success on reload failure")
	}
	if _, err := os.Stat(source); err != nil {
		t.Fatal("user file removed")
	}
}

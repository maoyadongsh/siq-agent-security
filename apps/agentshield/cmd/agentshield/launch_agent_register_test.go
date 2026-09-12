package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func launchRegistrationFixture(t *testing.T) (string, string, string) {
	t.Helper()
	home := t.TempDir()
	label := "dev.siq.agent-security." + strings.Repeat("a", 64)
	source := filepath.Join(t.TempDir(), label+".plist")
	if err := os.WriteFile(source, []byte("signed source fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	// A symlink capability probe is isolated; no real user LaunchAgents touched.
	probe := filepath.Join(t.TempDir(), "probe")
	if err := os.Symlink(source, probe); err != nil {
		t.Skip("symlink unavailable")
	}
	return home, source, label
}
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
	if runtime.GOOS != "windows" {
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
func TestLaunchRegistrationRefusesRedirectedDirectoriesAndLinks(t *testing.T) {
	for _, kind := range []string{"library", "agents", "foreign", "relative", "invalid-label", "source"} {
		t.Run(kind, func(t *testing.T) {
			home, source, label := launchRegistrationFixture(t)
			other := t.TempDir()
			library := filepath.Join(home, "Library")
			agents := filepath.Join(library, "LaunchAgents")
			if kind == "library" {
				if err := os.Symlink(other, library); err != nil {
					t.Fatal(err)
				}
			} else {
				if err := os.Mkdir(library, 0700); err != nil {
					t.Fatal(err)
				}
				if kind == "agents" {
					if err := os.Symlink(other, agents); err != nil {
						t.Fatal(err)
					}
				} else {
					if err := os.Mkdir(agents, 0700); err != nil {
						t.Fatal(err)
					}
					if kind == "foreign" || kind == "relative" {
						target := filepath.Join(other, "unknown.plist")
						if kind == "relative" {
							var err error
							target, err = filepath.Rel(agents, source)
							if err != nil {
								t.Fatal(err)
							}
						}
						if err := os.Symlink(target, filepath.Join(agents, label+".plist")); err != nil {
							t.Fatal(err)
						}
					}
				}
			}
			if kind == "invalid-label" {
				label = "../escape"
			}
			if kind == "source" {
				if err := os.Remove(source); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := publishLaunchRegistration(home, source, label); err == nil {
				t.Fatal("unsafe registration accepted")
			}
			entries, err := os.ReadDir(other)
			if err != nil || len(entries) != 0 {
				t.Fatal("wrote redirected directory")
			}
		})
	}
}

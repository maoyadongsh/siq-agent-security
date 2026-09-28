package main

import (
	"os"
	"path/filepath"
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

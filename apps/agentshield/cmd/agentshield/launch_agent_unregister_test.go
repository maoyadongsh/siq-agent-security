package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestUnregisterLaunchAgent(t *testing.T) {
	for _, mode := range []string{"unregister", "already unloaded", "already removed", "running", "foreign", "writer conflict", "bootout failed", "still loaded", "readback failed", "unknown link", "link changed", "missing link loaded"} {
		t.Run(mode, func(t *testing.T) {
			st, err := state.Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			w, err := state.AcquireWriter(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			instance, err := st.Initialize(w, 0)
			if err != nil {
				t.Fatal(err)
			}
			key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
			if err != nil {
				t.Fatal(err)
			}
			rendered, err := renderLaunchAgent("/test/siq", st.Dir, instance.InstanceID)
			if err != nil {
				t.Fatal(err)
			}
			plist := []byte(rendered)
			record, err := st.PrepareLaunchAgent(w, key, plist)
			if err != nil {
				t.Fatal(err)
			}
			if err := w.Release(); err != nil {
				t.Fatal(err)
			}
			home := t.TempDir()
			source := mustResolve(t, filepath.Join(st.Dir, record.Label+".plist"))
			if _, err := publishLaunchRegistration(home, source, record.Label); err != nil {
				t.Fatal(err)
			}

			link := filepath.Join(home, "Library", "LaunchAgents", record.Label+".plist")
			if mode == "already removed" || mode == "missing link loaded" || mode == "unknown link" {
				if err := os.Remove(link); err != nil {
					t.Fatal(err)
				}
				if mode == "unknown link" {
					if err := os.WriteFile(link, []byte("user file"), 0600); err != nil {
						t.Fatal(err)
					}
				}
			}
			if mode == "writer conflict" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer lock.Release()
			}
			loaded := mode != "already unloaded" && mode != "already removed"
			bootouts := 0
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					if bootouts > 0 && mode == "readback failed" {
						return "", errors.New("query failed")
					}
					raw := "PID\tStatus\tLabel\n"
					if loaded {
						raw += "-\t0\t" + record.Label + "\n"
					}
					return raw, nil
				case "print " + launchPrintTarget(501, record.Label):
					if mode == "foreign" {
						return mustLaunchPrint(t, rendered, source, 0, "", "other"), nil
					}
					if mode == "running" {
						return mustLaunchPrint(t, rendered, source, 123, "", ""), nil
					}
					return mustLaunchPrint(t, rendered, source, 0, "", ""), nil
				case "bootout gui/501/" + record.Label:
					bootouts++
					if lock, err := state.AcquireWriter(st.Dir); err == nil {
						_ = lock.Release()
						t.Fatal("writer not held")
					}
					if mode == "bootout failed" {
						return "", errors.New("failed")
					}
					loaded = mode == "still loaded"
					if mode == "link changed" {
						if err := os.Remove(link); err != nil {
							t.Fatal(err)
						}
						if err := os.WriteFile(link, []byte("user file"), 0600); err != nil {
							t.Fatal(err)
						}
					}
					return "", nil
				default:
					t.Fatal("unexpected command", args)
					return "", nil
				}
			}
			err = unregisterLaunchAgent(st, key, plist, home, 501, control)
			valid := mode == "unregister" || mode == "already unloaded" || mode == "already removed"
			if (err == nil) != valid {
				t.Fatal("unexpected result", err)
			}
			mutates := mode == "unregister" || mode == "bootout failed" || mode == "still loaded" || mode == "readback failed" || mode == "link changed"
			if (mutates && bootouts != 1) || (!mutates && bootouts != 0) {
				t.Fatal("unexpected bootout count", bootouts)
			}
			if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
				t.Fatal("source changed", err)
			}
			if valid {
				if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("registration remains", err)
				}
				if err := unregisterLaunchAgent(st, key, plist, home, 501, control); err != nil {
					t.Fatal("repeat failed", err)
				}
			} else if mode != "missing link loaded" {
				if _, err := os.Lstat(link); err != nil {
					t.Fatal("removed registration on failure", err)
				}
			}
		})
	}
}
func TestLaunchAgentUnregisterRequiresConfirmation(t *testing.T) {
	for _, args := range [][]string{nil, {"--confirm-unregister=false"}, {"--confirm-unregister", "extra"}} {
		if err := cmdLaunchAgentUnregister(args, io.Discard); err == nil {
			t.Fatal("confirmation bypass")
		}
	}
}

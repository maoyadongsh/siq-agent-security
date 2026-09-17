package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestTeardownLaunchAgentRecoveryAndRetention(t *testing.T) {
	for _, mode := range []string{"running", "idle", "already removed", "stop failed", "unload failed", "query failed", "missing link loaded", "unknown link"} {
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
			before := map[string][]byte{}
			err = filepath.WalkDir(st.Dir, func(path string, entry os.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.IsDir() {
					return nil
				}
				raw, err := os.ReadFile(path)
				if err == nil {
					before[path] = raw
				}
				return err
			})
			if err != nil {
				t.Fatal(err)
			}
			loaded := mode != "already removed"
			running := mode == "running" || mode == "stop failed" || mode == "unload failed"
			var daemon *state.Writer
			if running {
				daemon, err = state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer daemon.Release()
			}
			var mutations []string
			retry := false
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					if mode == "query failed" {
						return "", errors.New("unavailable")
					}
					raw := "PID\tStatus\tLabel\n"
					if loaded {
						raw += "-\t0\t" + record.Label + "\n"
					}
					return raw, nil
				case "print " + launchPrintTarget(501, record.Label):
					if running {
						return mustLaunchPrint(t, rendered, source, 123, "(never exited)", ""), nil
					}
					return mustLaunchPrint(t, rendered, source, 0, "0", ""), nil
				case "stop " + record.Label:
					mutations = append(mutations, "stop")
					if mode == "stop failed" {
						return "", errors.New("stop failed")
					}
					if daemon != nil {
						if err := daemon.Release(); err != nil {
							t.Fatal(err)
						}
						daemon = nil
					}
					running = false
					return "", nil
				case "bootout gui/501/" + record.Label:
					mutations = append(mutations, "bootout")
					if mode == "unload failed" && !retry {
						return "", errors.New("unload failed")
					}
					loaded = false
					return "", nil
				default:
					t.Fatal("unexpected command", args)
					return "", nil
				}
			}
			err = teardownLaunchAgent(st, key, plist, home, 501, control)
			valid := mode == "running" || mode == "idle" || mode == "already removed"
			if (err == nil) != valid {
				t.Fatal("unexpected result", err)
			}
			if mode == "stop failed" && strings.Join(mutations, ",") != "stop" {
				t.Fatal("unloaded after stop failure", mutations)
			}
			if mode == "query failed" || mode == "missing link loaded" || mode == "unknown link" {
				if len(mutations) != 0 {
					t.Fatal("mutated unconfirmed task", mutations)
				}
			}
			if mode == "unload failed" {
				retry = true
				if err := teardownLaunchAgent(st, key, plist, home, 501, control); err != nil {
					t.Fatal("retry failed", err)
				}
				if strings.Join(mutations, ",") != "stop,bootout,bootout" {
					t.Fatal("unexpected recovery sequence", mutations)
				}
				valid = true
			}
			if valid {
				if err := teardownLaunchAgent(st, key, plist, home, 501, control); err != nil {
					t.Fatal("repeat failed", err)
				}
				if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("registration retained", err)
				}
			}
			for path, want := range before {
				got, err := os.ReadFile(path)
				if err != nil || !bytes.Equal(got, want) {
					t.Fatal("state changed", filepath.Base(path), err)
				}
			}
		})
	}
}

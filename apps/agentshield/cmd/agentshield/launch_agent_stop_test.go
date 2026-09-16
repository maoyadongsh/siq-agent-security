package main

import (
	"bytes"
	"errors"
	"io"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestStopRegisteredLaunchAgent(t *testing.T) {
	for _, mode := range []string{"stop", "idle", "absent", "foreign", "stop failed", "still running", "exit error", "missing exit", "writer conflict", "disappeared"} {
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

			if mode == "writer conflict" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer lock.Release()
			}
			running := mode != "idle" && mode != "absent" && mode != "writer conflict"
			stopped, stops := false, 0
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					raw := "PID\tStatus\tLabel\n"
					if mode != "absent" {
						raw += "-\t0\t" + record.Label + "\n"
					}
					return raw, nil
				case "print " + launchPrintTarget(501, record.Label):
					if stopped && mode == "disappeared" {
						return "", errors.New("missing")
					}
					if mode == "foreign" {
						return mustLaunchPrint(t, rendered, source, 0, "", "other"), nil
					}
					if running {
						return mustLaunchPrint(t, rendered, source, 123, "(never exited)", ""), nil
					}
					lastExit := "(never exited)"
					if stopped && mode != "missing exit" {
						lastExit = "0"
						if mode == "exit error" {
							lastExit = "15"
						}
					}
					return mustLaunchPrint(t, rendered, source, 0, lastExit, ""), nil
				case "stop " + record.Label:
					stops++
					stopped = true
					if mode == "stop failed" {
						return "", errors.New("failure")
					}
					running = mode == "still running"
					return "", nil
				default:
					t.Fatal("unexpected command", args)
					return "", nil
				}
			}
			err = stopRegisteredLaunchAgent(st, key, plist, home, 501, control, 0)
			valid := mode == "stop" || mode == "idle" || mode == "absent"
			if (err == nil) != valid {
				t.Fatal("unexpected stop result", err)
			}
			noStop := mode == "idle" || mode == "absent" || mode == "foreign" || mode == "writer conflict"
			if (noStop && stops != 0) || (!noStop && stops != 1) {
				t.Fatal("unexpected stop count", stops)
			}
			if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
				t.Fatal("configuration changed", err)
			}
			if mode != "writer conflict" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal("writer leaked", err)
				}
				_ = lock.Release()
			}
		})
	}
}
func TestLaunchAgentStopRequiresConfirmation(t *testing.T) {
	for _, args := range [][]string{nil, {"--confirm-stop=false"}, {"--confirm-stop", "extra"}} {
		if err := cmdLaunchAgentStop(args, io.Discard); err == nil {
			t.Fatal("confirmation bypass")
		}
	}
}

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

func TestStartRegisteredLaunchAgent(t *testing.T) {
	for _, mode := range []string{"start", "reuse", "unhealthy", "no PID", "kickstart failed", "foreign", "writer conflict", "health drift"} {
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
			source := filepath.Join(st.Dir, record.Label+".plist")
			if _, err := publishLaunchRegistration(home, source, record.Label); err != nil {
				t.Fatal(err)
			}
			if mode == "writer conflict" || mode == "reuse" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer lock.Release()
			}
			running := mode == "reuse"
			starts, healthCalls := 0, 0
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					return "PID\tStatus\tLabel\n-\t0\t" + record.Label + "\n", nil
				case "list -x " + record.Label:
					if mode == "foreign" {
						return strings.Replace(rendered, "<string>serve</string>", "<string>other</string>", 1), nil
					}
					if running {
						at := strings.LastIndex(rendered, "</dict>")
						return rendered[:at] + "<key>PID</key><integer>123</integer>" + rendered[at:], nil
					}
					return rendered, nil
				case "kickstart gui/501/" + record.Label:
					starts++
					lock, err := state.AcquireWriter(st.Dir)
					if err != nil {
						t.Fatal("start blocked by caller writer", err)
					}
					_ = lock.Release()
					if mode == "kickstart failed" {
						return "", errors.New("failed")
					}
					running = mode != "no PID"
					return "", nil
				default:
					t.Fatal("unexpected command", args)
					return "", nil
				}
			}
			health := func() error {
				healthCalls++
				if mode == "unhealthy" {
					return errors.New("wrong instance")
				}
				if mode == "health drift" {
					if err := os.WriteFile(source, []byte("changed"), 0600); err != nil {
						t.Fatal(err)
					}
				}
				return nil
			}
			err = startRegisteredLaunchAgent(st, key, plist, home, 501, control, health, 0)
			valid := mode == "start" || mode == "reuse"
			if (err == nil) != valid {
				t.Fatal("unexpected result", err)
			}
			noStart := mode == "reuse" || mode == "foreign" || mode == "writer conflict"
			if (noStart && starts != 0) || (!noStart && starts != 1) {
				t.Fatal("unexpected starts", starts)
			}
			if mode == "no PID" && healthCalls != 0 {
				t.Fatal("health accepted without process")
			}
		})
	}
}
func TestLaunchAgentStartRequiresConfirmation(t *testing.T) {
	for _, args := range [][]string{nil, {"--confirm-start=false"}, {"--confirm-start", "extra"}} {
		if err := cmdLaunchAgentStart(args, io.Discard); err == nil {
			t.Fatal("confirmation bypass")
		}
	}
}

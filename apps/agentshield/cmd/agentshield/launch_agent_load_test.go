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

func TestLoadRegisteredLaunchAgent(t *testing.T) {
	for _, mode := range []string{"load", "reuse running", "writer conflict", "foreign", "query failed", "bootstrap failed", "readback absent", "readback foreign", "source changed", "link changed", "appeared", "wrong domain"} {
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
			link, err := publishLaunchRegistration(home, source, record.Label)
			if err != nil {
				t.Fatal(err)
			}
			if mode == "writer conflict" || mode == "reuse running" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer lock.Release()
			}
			present := mode == "reuse running" || mode == "foreign"
			bootstraps, lists := 0, 0
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					if mode == "wrong domain" {
						return "502", nil
					}
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					lists++
					if mode == "query failed" {
						return "", errors.New("unavailable")
					}
					if mode == "appeared" && lists == 2 {
						present = true
					}
					raw := "PID\tStatus\tLabel\n"
					if present {
						raw += "-\t0\t" + record.Label + "\n"
					}
					return raw, nil
				case "list -x " + record.Label:
					if mode == "foreign" || mode == "readback foreign" {
						return strings.Replace(rendered, "<string>serve</string>", "<string>other</string>", 1), nil
					}
					if mode == "reuse running" {
						at := strings.LastIndex(rendered, "</dict>")
						return rendered[:at] + "<key>PID</key><integer>123</integer>" + rendered[at:], nil
					}
					return rendered, nil
				case "bootstrap gui/501 " + link:
					bootstraps++
					// No daemon can acquire the writer while loading this non-autostart configuration.
					if lock, err := state.AcquireWriter(st.Dir); err == nil {
						_ = lock.Release()
						t.Fatal("writer not held during load")
					}
					if mode == "bootstrap failed" {
						return "", errors.New("timeout")
					}
					if mode != "readback absent" {
						present = true
					}
					if mode == "source changed" {
						if err := os.WriteFile(source, []byte("changed"), 0600); err != nil {
							t.Fatal(err)
						}
					}
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
			err = loadRegisteredLaunchAgent(st, key, plist, home, 501, control)
			valid := mode == "load" || mode == "reuse running" || mode == "appeared"
			if (err == nil) != valid {
				t.Fatal("unexpected result", err)
			}
			mutate := mode == "load" || mode == "bootstrap failed" || strings.HasPrefix(mode, "readback") || mode == "source changed" || mode == "link changed"
			if (mutate && bootstraps != 1) || (!mutate && bootstraps != 0) {
				t.Fatal("unexpected bootstrap count", bootstraps)
			}
			if mode == "link changed" {
				raw, _ := os.ReadFile(link)
				if string(raw) != "user file" {
					t.Fatal("unknown file removed")
				}
			}
			if mode != "writer conflict" && mode != "reuse running" {
				lock, err := state.AcquireWriter(st.Dir)
				if err != nil {
					t.Fatal("writer leaked", err)
				}
				_ = lock.Release()
			}
		})
	}
}
func TestLaunchAgentLoadRequiresExplicitConfirmation(t *testing.T) {
	for _, args := range [][]string{nil, {"--confirm-load=false"}, {"--confirm-load", "extra"}} {
		if err := cmdLaunchAgentLoad(args, io.Discard); err == nil {
			t.Fatal("invalid confirmation accepted")
		}
	}
}

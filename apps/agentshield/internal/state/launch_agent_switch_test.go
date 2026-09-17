package state

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"strings"
	"testing"
)

func launchSwitchFixture(t *testing.T) (*Store, *Writer, *signing.Key, LaunchAgentRecord, []byte, []byte, ServiceBinaryBindings) {
	t.Helper()
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	before, after := []byte("<plist>old</plist>"), []byte("<plist>new</plist>")
	record, err := s.PrepareLaunchAgent(w, key, before)
	if err != nil {
		t.Fatal(err)
	}
	bindings := ServiceBinaryBindings{SourceSHA256: strings.Repeat("a", 64), TargetSHA256: strings.Repeat("b", 64)}
	return s, w, key, record, before, after, bindings
}

func TestLaunchAgentSwitchPartialRecoveryAndDrift(t *testing.T) {
	for _, phase := range []string{"before", "plist", "pair", "drift"} {
		t.Run(phase, func(t *testing.T) {
			s, w, key, record, before, after, bindings := launchSwitchFixture(t)
			defer w.Release()
			id, err := s.PrepareLaunchAgentSwitch(w, key, before, after, bindings)
			if err != nil {
				t.Fatal(err)
			}
			if s.CheckServiceSwitchPending() == nil {
				t.Fatal("pending did not block startup")
			}
			if _, err = s.PrepareLaunchAgentSwitch(w, key, before, []byte("other"), bindings); err == nil {
				t.Fatal("overlapping switch")
			}
			if _, err = s.PrepareServiceSwitch(w, key, before, after); err == nil {
				t.Fatal("Linux switch prepared over pending macOS switch")
			}
			path := filepath.Join(s.Dir, record.Label+".plist")
			if phase == "plist" || phase == "pair" {
				if err = os.WriteFile(path, after, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if phase == "pair" {
				raw, _ := os.ReadFile(filepath.Join(s.Dir, serviceSwitchPending))
				p, err := s.validateLaunchAgentSwitch(key, raw)
				if err != nil {
					t.Fatal(err)
				}
				r, _ := json.Marshal(p.TargetRecord)
				if err = os.WriteFile(filepath.Join(s.Dir, "launch-agent.json"), r, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if phase == "drift" {
				if err = os.WriteFile(path, []byte("unknown"), 0600); err != nil {
					t.Fatal(err)
				}
				if s.ApplyLaunchAgentSwitch(w, key, id) == nil {
					t.Fatal("unknown bytes replaced")
				}
				if s.CheckServiceSwitchPending() == nil {
					t.Fatal("pending cleared after drift")
				}
				return
			}
			if err = s.ApplyLaunchAgentSwitch(w, key, id); err != nil {
				t.Fatal(err)
			}
			if _, err = s.VerifyLaunchAgent(key, after); err != nil {
				t.Fatal("target not verified", err)
			}
			if err = s.CheckServiceSwitchPending(); err != nil {
				t.Fatal("pending not cleared", err)
			}
			// Idempotent completion after the pending marker is gone.
			if err = s.ApplyLaunchAgentSwitch(w, key, id); err != nil {
				t.Fatal("completed switch not idempotent", err)
			}
			if _, err = os.Stat(filepath.Join(s.Dir, "service-switches", id+".done.json")); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestLaunchAgentSwitchRejectsLinuxJournalAndBadBindings(t *testing.T) {
	s, w, key, _, before, after, bindings := launchSwitchFixture(t)
	defer w.Release()
	if _, err := s.PrepareLaunchAgentSwitch(w, key, before, after, ServiceBinaryBindings{SourceSHA256: "x", TargetSHA256: strings.Repeat("b", 64)}); err == nil {
		t.Fatal("non-canonical digest accepted")
	}
	if _, err := s.PrepareLaunchAgentSwitch(w, key, before, before, bindings); err == nil {
		t.Fatal("empty switch accepted")
	}
	id, err := s.PrepareLaunchAgentSwitch(w, key, before, after, bindings)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.ReadServiceSwitch(key, id); err == nil {
		t.Fatal("macOS journal validated as Linux journal")
	}
	other, _ := signing.FromSeed(bytes.Repeat([]byte{1}, 32))
	if _, err = s.ReadLaunchAgentSwitch(other, id); err == nil {
		t.Fatal("foreign key accepted")
	}
	if err = s.ApplyLaunchAgentSwitch(w, other, id); err == nil {
		t.Fatal("foreign key applied")
	}
	raw, _ := os.ReadFile(filepath.Join(s.Dir, "service-switches", id+".json"))
	tampered := bytes.Replace(raw, []byte(strings.Repeat("b", 64)), []byte(strings.Repeat("c", 64)), 1)
	if err = os.WriteFile(filepath.Join(s.Dir, "service-switches", id+".json"), tampered, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.ReadLaunchAgentSwitch(key, id); err == nil {
		t.Fatal("tampered journal accepted")
	}
}

func TestLaunchAgentSwitchRequiresOwnWriter(t *testing.T) {
	s, w, key, _, before, after, bindings := launchSwitchFixture(t)
	w.Release()
	otherDir, _ := Open(t.TempDir())
	foreign, err := AcquireWriter(otherDir.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer foreign.Release()
	if _, err = s.PrepareLaunchAgentSwitch(foreign, key, before, after, bindings); err == nil {
		t.Fatal("foreign writer accepted")
	}
	if err = s.ApplyLaunchAgentSwitch(nil, key, strings.Repeat("0", 64)); err == nil {
		t.Fatal("nil writer accepted")
	}
}

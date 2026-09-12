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

func TestServiceSwitchPartialRecoveryAndDrift(t *testing.T) {
	for _, phase := range []string{"before", "unit", "pair", "drift"} {
		t.Run(phase, func(t *testing.T) {
			s, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			w, err := AcquireWriter(s.Dir)
			if err != nil {
				t.Fatal(err)
			}
			defer w.Release()
			if _, err = s.Initialize(w, 0); err != nil {
				t.Fatal(err)
			}
			key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
			before, after := []byte("old unit"), []byte("new unit")
			record, err := s.PrepareUserService(w, key, before)
			if err != nil {
				t.Fatal(err)
			}
			id, err := s.PrepareServiceSwitch(w, key, before, after)
			if err != nil {
				t.Fatal(err)
			}
			if s.CheckServiceSwitchPending() == nil {
				t.Fatal("pending did not block startup")
			}
			if _, err = s.PrepareServiceSwitch(w, key, before, []byte("other")); err == nil {
				t.Fatal("overlapping switch")
			}
			path := filepath.Join(s.Dir, record.UnitName)
			if phase == "unit" || phase == "pair" {
				if err = os.WriteFile(path, after, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if phase == "pair" {
				raw, _ := os.ReadFile(filepath.Join(s.Dir, serviceSwitchPending))
				p, err := s.validateServiceSwitch(key, raw)
				if err != nil {
					t.Fatal(err)
				}
				r, _ := json.Marshal(p.TargetRecord)
				if err = os.WriteFile(filepath.Join(s.Dir, "user-service.json"), r, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if phase == "drift" {
				if err = os.WriteFile(path, []byte("user data"), 0600); err != nil {
					t.Fatal(err)
				}
				if s.ApplyServiceSwitch(w, key, id) == nil {
					t.Fatal("drift overwritten")
				}
				raw, _ := os.ReadFile(path)
				if string(raw) != "user data" {
					t.Fatal("user data modified")
				}
				return
			}
			if err = s.ApplyServiceSwitch(w, key, id); err != nil {
				t.Fatal(err)
			}
			if err = s.CheckServiceSwitchPending(); err != nil {
				t.Fatal(err)
			}
			if _, err = s.VerifyUserService(key, after); err != nil {
				t.Fatal(err)
			}
			if err = s.ApplyServiceSwitch(w, key, id); err != nil {
				t.Fatal("completed retry", err)
			}
			// A completed journal cannot later reapply its source to roll state back.
			if err = os.WriteFile(path, before, 0600); err != nil {
				t.Fatal(err)
			}
			if s.ApplyServiceSwitch(w, key, id) == nil {
				t.Fatal("completed journal reactivated")
			}
		})
	}
}
func TestServiceSwitchContract(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareUserService(w, key, []byte("old unit")); err != nil {
		t.Fatal(err)
	}
	id, err := s.PrepareServiceSwitch(w, key, []byte("old unit"), []byte("new unit"))
	if err != nil {
		t.Fatal(err)
	}
	journal, err := os.ReadFile(filepath.Join(s.Dir, "service-switches", id+".json"))
	if err != nil {
		t.Fatal(err)
	}
	p, err := s.validateServiceSwitch(key, journal)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range []*UserServiceRecord{&p.SourceRecord, &p.TargetRecord} {
		r.InstanceID = strings.Repeat("a", 64)
		r.DirectoryID = strings.Repeat("b", 64)
		r.UnitName = "siq-agent-security-" + strings.Repeat("a", 32) + ".service"
		r.Signature, err = key.SignCanonical(r.unsigned())
		if err != nil {
			t.Fatal(err)
		}
	}
	doc, _ := p.unsigned()
	p.Signature, err = key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.MarshalIndent(p, "", "  ")
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-service-switch.json"
	if os.Getenv("SIQ_UPDATE_SERVICE_SWITCH_FIXTURE") == "1" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(raw, expected) {
		t.Fatal("fixture drift")
	}
}

package state

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

const switchTestSID = "S-1-5-21-100-200-300-1001"

func winSwitchFixture(t *testing.T) (*Store, *Writer, *signing.Key, []byte, []byte, ServiceBinaryBindings) {
	t.Helper()
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = w.Release() })
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	before, after := []byte("<Task>old</Task>"), []byte("<Task>new</Task>")
	if _, err = s.PrepareWindowsTask(w, key, before, switchTestSID); err != nil {
		t.Fatal(err)
	}
	return s, w, key, before, after, ServiceBinaryBindings{SourceSHA256: strings.Repeat("a", 64), TargetSHA256: strings.Repeat("b", 64)}
}

func winSwitchPlan(t *testing.T) (*Store, *Writer, *signing.Key, string, WindowsTaskSwitch) {
	t.Helper()
	s, w, key, before, after, bindings := winSwitchFixture(t)
	id, err := s.PrepareWindowsTaskSwitch(w, key, before, after, switchTestSID, bindings)
	if err != nil {
		t.Fatal(err)
	}
	p, err := s.ReadWindowsTaskSwitch(key, id)
	if err != nil {
		t.Fatal(err)
	}
	return s, w, key, id, p
}

func writeSwitchTest(t *testing.T, path string, raw []byte) {
	t.Helper()
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestWinSwitchRecovery(t *testing.T) {
	for _, phase := range []string{"before", "xml", "record", "both", "done"} {
		t.Run(phase, func(t *testing.T) {
			s, w, key, id, p := winSwitchPlan(t)
			images := s.windowsTaskSwitchImages(p)
			for i, image := range images {
				if phase == "both" || phase == "done" || (phase == "xml" && i == 0) || (phase == "record" && i == 1) {
					writeSwitchTest(t, image.path, image.after)
				}
			}
			if phase == "done" {
				raw, _, _ := s.readWindowsTaskSwitch(key, id)
				if err := publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".done.json"), raw); err != nil {
					t.Fatal(err)
				}
			}
			if s.CheckWindowsTaskSwitchCompleted(key, id) == nil {
				t.Fatal("pending reported complete")
			}
			if _, err := s.PrepareLaunchAgentSwitch(w, key, []byte(p.SourceXML), []byte(p.TargetXML), p.BinaryBindings); err == nil {
				t.Fatal("overlap allowed")
			}
			if _, err := s.PrepareWindowsTaskSwitch(w, key, []byte(p.SourceXML), []byte(p.TargetXML), switchTestSID, p.BinaryBindings); err == nil {
				t.Fatal("Windows overlap allowed")
			}
			if err := s.ApplyWindowsTaskSwitch(w, key, id); err != nil {
				t.Fatal(err)
			}
			if s.CheckServiceSwitchPending() == nil {
				t.Fatal("application cleared startup barrier")
			}
			if _, err := s.VerifyWindowsTask(key, []byte(p.TargetXML), switchTestSID); err != nil {
				t.Fatal(err)
			}
			if err := s.FinishWindowsTaskSwitch(w, key, id); err != nil {
				t.Fatal(err)
			}
			if err := s.CheckWindowsTaskSwitchCompleted(key, id); err != nil {
				t.Fatal(err)
			}
			if err := s.CheckServiceSwitchPending(); err != nil {
				t.Fatal(err)
			}
			if err := s.ApplyWindowsTaskSwitch(w, key, id); err != nil {
				t.Fatal("completed apply", err)
			}
			if err := s.FinishWindowsTaskSwitch(w, key, id); err != nil {
				t.Fatal("completed finish", err)
			}
		})
	}
}

func TestWinSwitchRefuse(t *testing.T) {
	for _, fault := range []string{"xml", "record", "pending", "lost-pending", "done", "done-before", "finish-before", "completed-before"} {
		t.Run(fault, func(t *testing.T) {
			s, w, key, id, p := winSwitchPlan(t)
			images := s.windowsTaskSwitchImages(p)
			switch fault {
			case "xml":
				writeSwitchTest(t, images[0].path, []byte("unknown"))
			case "record":
				writeSwitchTest(t, images[1].path, []byte("unknown"))
			case "pending":
				writeSwitchTest(t, filepath.Join(s.Dir, serviceSwitchPending), []byte("unknown"))
			case "lost-pending":
				if err := os.Remove(filepath.Join(s.Dir, serviceSwitchPending)); err != nil {
					t.Fatal(err)
				}
			case "done":
				if err := publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".done.json"), []byte("unknown")); err != nil {
					t.Fatal(err)
				}
			case "done-before":
				raw, _, _ := s.readWindowsTaskSwitch(key, id)
				if err := publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".done.json"), raw); err != nil {
					t.Fatal(err)
				}
			case "finish-before":
				if s.FinishWindowsTaskSwitch(w, key, id) == nil {
					t.Fatal("finished source images")
				}
				if s.CheckServiceSwitchPending() == nil {
					t.Fatal("cleared pending")
				}
				return
			case "completed-before":
				if err := s.ApplyWindowsTaskSwitch(w, key, id); err != nil {
					t.Fatal(err)
				}
				if err := s.FinishWindowsTaskSwitch(w, key, id); err != nil {
					t.Fatal(err)
				}
				writeSwitchTest(t, images[0].path, images[0].before)
			}
			before := make([][]byte, len(images))
			for i, image := range images {
				before[i], _ = os.ReadFile(image.path)
			}
			if s.ApplyWindowsTaskSwitch(w, key, id) == nil {
				t.Fatal("accepted drift or missing evidence")
			}
			if s.FinishWindowsTaskSwitch(w, key, id) == nil {
				t.Fatal("finished invalid state")
			}
			if s.CheckWindowsTaskSwitchCompleted(key, id) == nil {
				t.Fatal("reported invalid completion")
			}
			for i, image := range images {
				raw, _ := os.ReadFile(image.path)
				if !bytes.Equal(raw, before[i]) {
					t.Fatal("modified another image before full preflight")
				}
			}
		})
	}
}

func TestWinSwitchJSON(t *testing.T) {
	s, _, key, id, _ := winSwitchPlan(t)
	raw, _, err := s.readWindowsTaskSwitch(key, id)
	if err != nil {
		t.Fatal(err)
	}
	// Duplicate keys below preserve the semantic document and its signature.
	// Only strict decoding, not signature verification alone, can reject them.
	for _, field := range []string{"schema_version", "source_sha256", "instance_id", "user_sid", "signature"} {
		for _, change := range []string{"duplicate", "case", "null", "unknown"} {
			t.Run(field+"/"+change, func(t *testing.T) {
				needle := []byte(`"` + field + `":`)
				start := bytes.Index(raw, needle) + len(needle)
				end := start + 1 + bytes.IndexByte(raw[start+1:], '"') + 1
				value := raw[start:end]
				replacement := append(append(append([]byte{}, needle...), value...), append([]byte(","), needle...)...)
				switch change {
				case "case":
					replacement = []byte(`"` + strings.ToUpper(field) + `":`)
				case "null":
					bad := bytes.Replace(raw, append(append([]byte{}, needle...), value...), append(append([]byte{}, needle...), []byte("null")...), 1)
					if _, err := s.validateWindowsTaskSwitch(key, bad); err == nil {
						t.Fatal("accepted null")
					}
					return
				case "unknown":
					replacement = []byte(`"unknown":0,` + string(needle))
				}
				bad := bytes.Replace(raw, needle, replacement, 1)
				if _, err := s.validateWindowsTaskSwitch(key, bad); err == nil {
					t.Fatal("accepted ambiguous JSON")
				}
			})
		}
	}
	for _, bad := range [][]byte{append(append([]byte{}, raw...), []byte(" {}")...), bytes.Replace(raw, []byte(windowsTaskSwitchSchema), []byte(launchAgentSwitchSchema), 1)} {
		if _, err := s.validateWindowsTaskSwitch(key, bad); err == nil {
			t.Fatal("accepted trailing data/platform confusion")
		}
	}
	if _, err := s.ReadLaunchAgentSwitch(key, id); err == nil {
		t.Fatal("Windows accepted as macOS")
	}
	if _, err := s.ReadServiceSwitch(key, id); err == nil {
		t.Fatal("Windows accepted as Linux")
	}
}

func TestWinSwitchIdentity(t *testing.T) {
	s, w, key, id, p := winSwitchPlan(t)
	other, _ := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
	if _, err := s.ReadWindowsTaskSwitch(other, id); err == nil {
		t.Fatal("foreign key accepted")
	}
	for _, bad := range []string{"../other", strings.ToUpper(id), strings.Repeat("0", 64)} {
		if _, err := s.ReadWindowsTaskSwitch(key, bad); err == nil {
			t.Fatal("bad id accepted")
		}
	}
	if s.ApplyWindowsTaskSwitch(nil, key, id) == nil || s.FinishWindowsTaskSwitch(nil, key, id) == nil {
		t.Fatal("nil writer accepted")
	}
	foreign, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	fw, err := AcquireWriter(foreign.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer fw.Release()
	if s.ApplyWindowsTaskSwitch(fw, key, id) == nil || s.FinishWindowsTaskSwitch(fw, key, id) == nil {
		t.Fatal("foreign writer accepted")
	}
	if _, err := s.PrepareWindowsTaskSwitch(fw, key, []byte(p.SourceXML), []byte(p.TargetXML), switchTestSID, p.BinaryBindings); err == nil {
		t.Fatal("foreign writer prepared")
	}
	if err = w.Release(); err != nil {
		t.Fatal(err)
	}
	if s.ApplyWindowsTaskSwitch(w, key, id) == nil {
		t.Fatal("released writer accepted")
	}
	for _, mutate := range []func(*WindowsTaskSwitch){
		func(p *WindowsTaskSwitch) { p.TargetRecord.UserSID = "S-1-5-21-101-200-300-1001" },
		func(p *WindowsTaskSwitch) { p.TargetRecord.InstanceID = strings.Repeat("c", 64) },
		func(p *WindowsTaskSwitch) { p.TargetRecord.DirectoryID = strings.Repeat("c", 64) },
		func(p *WindowsTaskSwitch) { p.TargetRecord.XMLSHA256 = strings.Repeat("c", 64) },
		func(p *WindowsTaskSwitch) { p.SourceXML = p.TargetXML },
	} {
		bad := p
		mutate(&bad)
		bad.TargetRecord.Signature, _ = key.SignCanonical(bad.TargetRecord.unsigned())
		doc, _ := bad.unsigned()
		bad.Signature, _ = key.SignCanonical(doc)
		raw, _ := json.Marshal(bad)
		if _, err := s.validateWindowsTaskSwitch(key, raw); err == nil {
			t.Fatal("accepted signed identity drift")
		}
	}
	raw, _, _ := s.readWindowsTaskSwitch(key, id)
	writeSwitchTest(t, filepath.Join(s.Dir, "service-switches", id+".json"), append(raw, '\n'))
	if _, err := s.ReadWindowsTaskSwitch(key, id); err == nil {
		t.Fatal("byte identity drift accepted")
	}
}

func TestWinSwitchPrepare(t *testing.T) {
	s, w, key, before, after, bindings := winSwitchFixture(t)
	for _, test := range []struct {
		source, target []byte
		sid            string
		binding        ServiceBinaryBindings
	}{
		{before, before, switchTestSID, bindings}, {before, after, "S-1-5-18", bindings},
		{before, after, switchTestSID, ServiceBinaryBindings{}}, {[]byte("foreign"), after, switchTestSID, bindings},
		{before, bytes.Repeat([]byte("<"), 16384), switchTestSID, bindings},
	} {
		if _, err := s.PrepareWindowsTaskSwitch(w, key, test.source, test.target, test.sid, test.binding); err == nil {
			t.Fatal("invalid preparation accepted")
		}
		if err := s.CheckServiceSwitchPending(); err != nil {
			t.Fatal("invalid input created barrier")
		}
	}
}

func TestWinSwitchContract(t *testing.T) {
	root := filepath.Join("..", "..", "testdata", "contracts")
	raw, err := os.ReadFile(filepath.Join(root, "local-windows-task-switch.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture WindowsTaskSwitch
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	sourceRaw, err := os.ReadFile(filepath.Join(root, "local-windows-task-record.json"))
	if err != nil {
		t.Fatal(err)
	}
	var source WindowsTaskRecord
	if err = json.Unmarshal(sourceRaw, &source); err != nil {
		t.Fatal(err)
	}
	sourceXML, err := os.ReadFile(filepath.Join(root, "windows-task.sample.xml"))
	if err != nil {
		t.Fatal(err)
	}
	targetXML := bytes.Replace(sourceXML, []byte(`\siq.exe`), []byte(`\siq-next.exe`), 1)
	target := source
	hash := sha256.Sum256(targetXML)
	target.XMLSHA256 = hex.EncodeToString(hash[:])
	target.Signature, _ = key.SignCanonical(target.unsigned())
	p := WindowsTaskSwitch{TransactionNonce: strings.Repeat("e", 32), BinaryBindings: ServiceBinaryBindings{SourceSHA256: strings.Repeat("c", 64), TargetSHA256: strings.Repeat("d", 64)}, SchemaVersion: windowsTaskSwitchSchema, SourceRecord: source, TargetRecord: target, SourceXML: string(sourceXML), TargetXML: string(targetXML)}
	doc, _ := p.unsigned()
	p.Signature, _ = key.SignCanonical(doc)
	if p != fixture {
		t.Fatal("Go serialized document differs from cross-language signed fixture")
	}
}

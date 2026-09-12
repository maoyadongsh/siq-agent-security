package state

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func initializationStore(t *testing.T) (*Store, *Writer) {
	t.Helper()
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = w.Release() })
	return st, w
}

func TestInitializationPreservesConfigurationAndIdentity(t *testing.T) {
	st, w := initializationStore(t)
	first, err := st.Initialize(w, 0)
	if err != nil || first.Port != 47611 || first.Status != "initialized" {
		t.Fatalf("init: %+v %v", first, err)
	}
	cfg, err := st.LoadConfig()
	if err != nil || cfg.EnforcementMode != "block" {
		t.Fatal("unsafe defaults")
	}
	original := []byte("{\n\"port\":49123,\"enforcement_mode\":\"warn\",\"custom_setting\":true\n}")
	if err := os.WriteFile(filepath.Join(st.Dir, "config.json"), original, 0600); err != nil {
		t.Fatal(err)
	}
	again, err := st.Initialize(w, 0)
	if err != nil || again.InstanceID != first.InstanceID || again.Port != 49123 {
		t.Fatalf("repeat: %+v %v", again, err)
	}
	if _, err := st.Initialize(w, 49123); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Initialize(w, 49124); err == nil {
		t.Fatal("existing port changed")
	}
	actual, _ := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if !bytes.Equal(actual, original) {
		t.Fatal("existing config was rewritten")
	}
	for _, name := range []string{"token", "admin-recovery.token", "keys/signing.seed"} {
		if _, err := os.Stat(filepath.Join(st.Dir, name)); !os.IsNotExist(err) {
			t.Fatalf("initialization generated credential %s", name)
		}
	}
}

func TestInitializationRejectsCorruptionBeforePublishing(t *testing.T) {
	for _, tc := range []struct{ name, file, body string }{
		{"null config", "config.json", "null"},
		{"invalid config", "config.json", "{"},
		{"bad port", "config.json", `{"port":0}`},
		{"bad mode", "config.json", `{"enforcement_mode":"allow"}`},
		{"large config", "config.json", strings.Repeat(" ", 65537)},
		{"null identity", "local-instance.json", "null"},
		{"future identity", "local-instance.json", `{"schema_version":"local-client-instance/v99","instance_id":"` + strings.Repeat("a", 64) + `"}`},
		{"bad identity", "local-instance.json", `{"schema_version":"local-client-instance/v1","instance_id":"short"}`},
		{"unknown field", "local-instance.json", `{"schema_version":"local-client-instance/v1","instance_id":"` + strings.Repeat("a", 64) + `","token":"unexpected"}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			st, w := initializationStore(t)
			path := filepath.Join(st.Dir, tc.file)
			if err := os.WriteFile(path, []byte(tc.body), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := st.Initialize(w, 0); err == nil {
				t.Fatal("corrupt input accepted")
			}
			got, _ := os.ReadFile(path)
			if string(got) != tc.body {
				t.Fatal("corrupt file overwritten")
			}
			other := "config.json"
			if tc.file == other {
				other = "local-instance.json"
			}
			if _, err := os.Stat(filepath.Join(st.Dir, other)); !os.IsNotExist(err) {
				t.Fatal("published before validation")
			}
		})
	}
}

func TestInitializationRequiresWriterAndRejectsSymlinks(t *testing.T) {
	st, w := initializationStore(t)
	if _, err := st.Initialize(nil, 0); err == nil {
		t.Fatal("missing writer accepted")
	}
	forged := *w
	forged.owner = "wrong"
	if _, err := st.Initialize(&forged, 0); err == nil {
		t.Fatal("forged writer accepted")
	}
	if _, err := AcquireWriter(st.Dir); err == nil {
		t.Fatal("second writer accepted")
	}
	for _, name := range []string{"config.json", "local-instance.json"} {
		path := filepath.Join(st.Dir, name)
		outside := filepath.Join(t.TempDir(), "outside")
		if err := os.WriteFile(outside, []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(outside, path); err != nil {
			t.Skip("symlinks unavailable")
		}
		if _, err := st.Initialize(w, 0); err == nil {
			t.Fatal("symlink accepted")
		}
		got, _ := os.ReadFile(outside)
		if string(got) != "{}" {
			t.Fatal("external file modified")
		}
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Initialize(w, 0); err == nil {
		t.Fatal("released writer accepted")
	}
}

func TestInitializationRecoversPartialMetadata(t *testing.T) {
	for _, keep := range []string{"config.json", "local-instance.json"} {
		t.Run(keep, func(t *testing.T) {
			st, w := initializationStore(t)
			first, err := st.Initialize(w, 49123)
			if err != nil {
				t.Fatal(err)
			}
			remove := "config.json"
			if keep == remove {
				remove = "local-instance.json"
			}
			original, _ := os.ReadFile(filepath.Join(st.Dir, keep))
			if err := os.Remove(filepath.Join(st.Dir, remove)); err != nil {
				t.Fatal(err)
			}
			result, err := st.Initialize(w, 49123)
			if err != nil || result.Port != 49123 {
				t.Fatal("partial initialization did not recover")
			}
			actual, _ := os.ReadFile(filepath.Join(st.Dir, keep))
			if !bytes.Equal(original, actual) {
				t.Fatal("published metadata replaced")
			}
			if keep == "local-instance.json" && result.InstanceID != first.InstanceID {
				t.Fatal("identity reset")
			}
		})
	}
}

func TestInitializationContractFixtures(t *testing.T) {
	st, w := initializationStore(t)
	result, err := st.Initialize(w, 0)
	if err != nil {
		t.Fatal(err)
	}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		t.Fatal(err)
	}
	result.InstanceID = strings.Repeat("a", 64)
	result.StateDirectoryID = strings.Repeat("b", 64)
	instance.InstanceID = result.InstanceID
	for name, value := range map[string]any{"local-initialization": result, "local-instance": instance} {
		raw, _ := json.Marshal(value)
		fixture, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", name+".json"))
		if err != nil {
			t.Fatal(err)
		}
		var got, want any
		if json.Unmarshal(raw, &got) != nil || json.Unmarshal(fixture, &want) != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("fixture differs: %s", name)
		}
	}
}

func TestInitializationFileBudgetAndPrivatePublication(t *testing.T) {
	st, w := initializationStore(t)
	config := []byte("{}" + strings.Repeat(" ", 65534))
	if err := os.WriteFile(filepath.Join(st.Dir, "config.json"), config, 0600); err != nil {
		t.Fatal(err)
	}
	first, err := st.Initialize(w, 0)
	if err != nil {
		t.Fatal("64 KiB configuration rejected", err)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(filepath.Join(st.Dir, "local-instance.json"))
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatal("instance record is not private")
		}
	}
	other, otherWriter := initializationStore(t)
	second, err := other.Initialize(otherWriter, 0)
	if err != nil || second.InstanceID == first.InstanceID {
		t.Fatal("separate installations share an identity")
	}
}

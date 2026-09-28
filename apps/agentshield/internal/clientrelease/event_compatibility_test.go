package clientrelease

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func TestLegacyCandidateRejectsV2HistoryBeforeStaging(t *testing.T) {
	for _, where := range []string{"pending", "receipt"} {
		t.Run(where, func(t *testing.T) {
			dir := t.TempDir()
			manifest, binary, m, key := fixture(t)
			m.ManifestVersion = 3
			m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
			m.StateCompatibility = skillmanifest.CurrentStateCompatibility()
			m.StateCompatibility.ReaderVersion, m.StateCompatibility.WriterVersion = 3, 3
			writeManifest(t, manifest, m, key)
			check := func() error {
				_, err := checkUpgrade(manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public(), dir)
				return err
			}
			name, legacy, modern := "pending/decisions.jsonl", `{"schema":"pending_decision/v1","signed":false}`, `{"schema":"pending_decision/v2","signed":false}`
			if where == "receipt" {
				name, legacy, modern = "receipts/local/2026-09-28.jsonl", `{"record_type":"decision","seq":0}`, `{"schema_version":"runtime-receipt/v2","record_type":"local_failure","seq":1}`
			}
			path := filepath.Join(dir, filepath.FromSlash(name))
			if err := statefs.MkdirAllPrivate(filepath.Dir(path)); err != nil {
				t.Fatal(err)
			}
			if err := statefs.WriteFile(path, []byte(legacy+"\n"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := check(); err != nil {
				t.Fatal("legacy history rejected", err)
			}
			original := []byte(legacy + "\n" + modern + "\n")
			if err := statefs.WriteFile(path, original, 0600); err != nil {
				t.Fatal(err)
			}
			if err := check(); !errors.Is(err, errEventCompatibility) {
				t.Fatal("old reader accepted v2 history", err)
			}
			if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); !errors.Is(err, errEventCompatibility) {
				t.Fatal("old reader staged", err)
			}
			if _, err := os.Lstat(filepath.Join(dir, "client-releases")); !os.IsNotExist(err) {
				t.Fatal("rejected candidate created staging", err)
			}
			got, err := os.ReadFile(path)
			if err != nil || string(got) != string(original) {
				t.Fatal("compatibility check changed history")
			}
			m.StateCompatibility = skillmanifest.CurrentStateCompatibility()
			writeManifest(t, manifest, m, key)
			if err := check(); err != nil {
				t.Fatal("compatible release rejected", err)
			}
		})
	}
}

func TestLegacyHistoryMalformedUnknownAndUnsafeRefused(t *testing.T) {
	for _, line := range []string{`[]`, `{}`, `{"schema":"pending_decision/v3"}`, `{"schema":null}`, `{"schema":"pending_decision/v2","schema":"pending_decision/v1"}`, `{"Schema":"pending_decision/v1"}`, `{"schema":"pending_decision/v1"} {}`, `{"schema_version":"runtime-receipt/v2"}`, `{"record_type":"local_failure"}`, `{"local_origin":null}`, strings.Repeat("x", (1<<20)+1)} {
		if line == "{}" { // Legacy empty objects were accepted; this is not a signature validator.
			if !legacyEventLine([]byte(line), true) {
				t.Fatal("legacy parser compatibility changed")
			}
			continue
		}
		t.Run("invalid", func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, "pending", "decisions.jsonl")
			if err := statefs.MkdirAllPrivate(filepath.Dir(path)); err != nil {
				t.Fatal(err)
			}
			if err := statefs.WriteFile(path, []byte(line+"\n"), 0600); err != nil {
				t.Fatal(err)
			}
			if !errors.Is(checkLegacyEventCompatibility(dir), errEventCompatibility) {
				t.Fatal("unknown or malformed data accepted")
			}
		})
	}
	t.Run("directory-as-log", func(t *testing.T) {
		dir := t.TempDir()
		if err := statefs.MkdirAllPrivate(filepath.Join(dir, "pending", "decisions.jsonl")); err != nil {
			t.Fatal(err)
		}
		if !errors.Is(checkLegacyEventCompatibility(dir), errEventCompatibility) {
			t.Fatal("nonregular log accepted")
		}
	})
	t.Run("oversized-log", func(t *testing.T) {
		dir := t.TempDir()
		path := filepath.Join(dir, "pending", "decisions.jsonl")
		if err := statefs.MkdirAllPrivate(filepath.Dir(path)); err != nil {
			t.Fatal(err)
		}
		f, err := statefs.CreatePrivate(path)
		if err != nil {
			t.Fatal(err)
		}
		err = f.Truncate((256 << 20) + 1)
		closeErr := f.Close()
		if err != nil || closeErr != nil {
			t.Fatal(err, closeErr)
		}
		if !errors.Is(checkLegacyEventCompatibility(dir), errEventCompatibility) {
			t.Fatal("oversized history accepted")
		}
	})
}

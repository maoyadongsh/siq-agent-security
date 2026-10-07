package clientrelease

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func TestNativeStateRejectsOldCandidateBeforeStaging(t *testing.T) {
	for name, sample := range map[string]string{
		"skill-contexts-v2/context.json":               "skill-execution-context-v2.sample.json",
		"skill-context-revocations-v2/revocation.json": "skill-execution-context-revocation-v2.sample.json",
		"native-skill-sessions/session.json":           "native-skill-managed-session-v1.sample.json",
		"native-skill-calls/call.json":                 "native-skill-call-with-skill-v1.sample.json",
		"native-skill-calls/.unfinished":               "native-skill-call-no-skill-v1.sample.json",
		"receipts/local/native.jsonl":                  "native-receipt-with-skill-v3.sample.json",
		"runtime-identities/native-root.json":          "local-runtime-identity-native-v4.sample.json",
		"runtime-identities/native-child.json":         "local-runtime-identity-native-v5.sample.json",
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			manifest, binary, m, key := fixture(t)
			m.ManifestVersion = 3
			m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
			m.StateCompatibility = skillmanifest.CurrentStateCompatibility()
			path := filepath.Join(dir, filepath.FromSlash(name))
			if err := statefs.MkdirAllPrivate(filepath.Dir(path)); err != nil {
				t.Fatal(err)
			}
			// Product-generated signed samples remain byte-identical after refusal.
			// Authority directories reject any entry, including unfinished writes.
			original, err := os.ReadFile("../../testdata/contracts/" + sample)
			if err != nil {
				t.Fatal(err)
			}
			if name == "receipts/local/native.jsonl" {
				var compact bytes.Buffer
				if err := json.Compact(&compact, original); err != nil {
					t.Fatal(err)
				}
				original = append(compact.Bytes(), '\n')
			}
			if err := statefs.WriteFile(path, original, 0600); err != nil {
				t.Fatal(err)
			}
			for _, versions := range [][2]int{{3, 3}, {4, 4}, {5, 4}, {4, 5}} {
				m.StateCompatibility.ReaderVersion, m.StateCompatibility.WriterVersion = versions[0], versions[1]
				writeManifest(t, manifest, m, key)
				if err := checkStateDeclaration(dir, m); !errors.Is(err, errEventCompatibility) {
					t.Fatalf("state declaration %v accepted native history: %v", versions, err)
				}
				// writer < reader is already rejected by manifest validation.
				if _, err := checkUpgrade(manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public(), dir); err == nil || (versions[0] <= versions[1] && !errors.Is(err, errEventCompatibility)) {
					t.Fatalf("candidate %v accepted native state: %v", versions, err)
				}
				if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err == nil || (versions[0] <= versions[1] && !errors.Is(err, errEventCompatibility)) {
					t.Fatalf("candidate %v staged: %v", versions, err)
				}
			}
			if _, err := os.Lstat(filepath.Join(dir, "client-releases")); !os.IsNotExist(err) {
				t.Fatal("created staging", err)
			}
			got, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(got, original) {
				t.Fatal("history changed", err)
			}
			m.StateCompatibility = skillmanifest.CurrentStateCompatibility()
			writeManifest(t, manifest, m, key)
			if _, err := checkUpgrade(manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public(), dir); err != nil {
				t.Fatal("current candidate rejected", err)
			}
		})
	}
}

func TestReader4AcceptsHistoricalEventsAndEmptyNativeDirectories(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"skill-contexts-v2", "skill-context-revocations-v2", "native-skill-sessions", "native-skill-calls", "pending", "receipts/local"} {
		if err := statefs.MkdirAllPrivate(filepath.Join(dir, name)); err != nil {
			t.Fatal(err)
		}
	}
	for name, raw := range map[string]string{
		"pending/decisions.jsonl":  "{\"schema\":\"pending_decision/v1\"}\n{\"schema\":\"pending_decision/v2\",\"local_origin\":{}}\n",
		"receipts/local/old.jsonl": "{\"record_type\":\"decision\"}\n{\"schema_version\":\"runtime-receipt/v2\",\"record_type\":\"local_failure\"}\n",
	} {
		if err := statefs.WriteFile(filepath.Join(dir, name), []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
	}
	manifest, binary, m, key := fixture(t)
	m.ManifestVersion = 3
	m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
	m.StateCompatibility = skillmanifest.CurrentStateCompatibility()
	m.StateCompatibility.ReaderVersion, m.StateCompatibility.WriterVersion = 4, 4
	writeManifest(t, manifest, m, key)
	if _, err := checkUpgrade(manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public(), dir); err != nil {
		t.Fatal(err)
	}
	if err := checkLegacyEventCompatibility(dir); !errors.Is(err, errEventCompatibility) {
		t.Fatal("reader3 accepted v2", err)
	}
}

func TestReader4RejectsUnsupportedEvidence(t *testing.T) {
	for _, raw := range []string{
		`{"schema_version":"runtime-receipt/v3"}`, `{"schema_version":"runtime-receipt/v99"}`,
		`{"Schema_Version":"runtime-receipt/v2"}`, `{"schema_version":null}`,
		`{"schema_version":"runtime-receipt/v3","schema_version":"runtime-receipt/v2"}`,
		`{"native_invocation":null}`, `{"Native_Invocation":{}}`,
		`{"schema_version":"runtime-receipt/v2"} {}`, `{"Local_Origin":{}}`,
	} {
		if compatibleEventLine([]byte(raw), false, 4) {
			t.Fatalf("unsupported evidence accepted: %s", raw)
		}
	}
	if compatibleEventLine([]byte(`{"schema":"pending_decision/v3"}`), true, 4) {
		t.Fatal("future pending accepted")
	}
}

func TestReader4RejectsUnsafeNativeDirectory(t *testing.T) {
	for _, kind := range []string{"file", "symlink", "nonprivate"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, "native-skill-calls")
			switch kind {
			case "file":
				if err := statefs.WriteFile(path, []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Symlink(t.TempDir(), path); err != nil {
					t.Skip("symlink unavailable", err)
				}
			case "nonprivate":
				if runtime.GOOS == "windows" {
					t.Skip("POSIX permission fixture")
				}
				if err := os.Mkdir(path, 0755); err != nil {
					t.Fatal(err)
				}
				if err := os.Chmod(path, 0755); err != nil {
					t.Fatal(err)
				}
			}
			if err := checkEventCompatibility(dir, 4); !errors.Is(err, errEventCompatibility) {
				t.Fatal("unsafe directory accepted", err)
			}
		})
	}
}

func TestLegacyIdentityVersionScan(t *testing.T) {
	for _, name := range []string{"local-runtime-identity.json", "local-runtime-identity-v3.json"} {
		raw, err := os.ReadFile("../../testdata/contracts/" + name)
		if err != nil || !legacyIdentityRecord(raw) {
			t.Fatal("old identity refused", name, err)
		}
		dir := t.TempDir()
		path := filepath.Join(dir, "runtime-identities", "old.json")
		if err := statefs.MkdirAllPrivate(filepath.Dir(path)); err != nil {
			t.Fatal(err)
		}
		if err := statefs.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		if err := checkEventCompatibility(dir, 4); err != nil {
			t.Fatal("legacy identity state rejected", err)
		}
	}
	for _, raw := range []string{`{}`, `{"schema_version":"local-runtime-identity/v4"}`, `{"schema_version":"local-runtime-identity/v1","native_skill_policy":null}`, `{"schema_version":"local-runtime-identity/v3","schema_version":"local-runtime-identity/v1"}`} {
		if legacyIdentityRecord([]byte(raw)) {
			t.Fatal("unknown or ambiguous identity accepted")
		}
	}
}

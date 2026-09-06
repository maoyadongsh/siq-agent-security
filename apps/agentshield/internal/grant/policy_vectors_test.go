package grant

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func TestPolicyCompileVectorsV1(t *testing.T) {
	raw, err := os.ReadFile(policyCompileFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Schema    string   `json:"schema"`
		KnownKeys []string `json:"known_keys"`
		Vectors   []struct {
			Name            string         `json:"name"`
			Expect          string         `json:"expect"`
			Desired         map[string]any `json:"desired"`
			Capabilities    map[string]any `json:"capabilities"`
			ArtifactHash    string         `json:"artifact_hash"`
			Unsupported     []string       `json:"unsupported"`
			NeedsGeneration bool           `json:"needs_generation"`
			EnforcementMode string         `json:"enforcement_mode"`
			ErrorContains   string         `json:"error_contains"`
		} `json:"vectors"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Schema != "policy_compile_vectors/v1" {
		t.Fatalf("schema %s", doc.Schema)
	}
	if len(doc.KnownKeys) < 10 {
		t.Fatalf("known_keys too short: %v", doc.KnownKeys)
	}
	for _, k := range doc.KnownKeys {
		if !knownKeys[k] {
			t.Fatalf("fixture known key %q missing from Go knownKeys", k)
		}
	}
	for k := range knownKeys {
		found := false
		for _, fk := range doc.KnownKeys {
			if fk == k {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("Go knownKeys %q missing from fixture allowlist", k)
		}
	}

	for _, vec := range doc.Vectors {
		caps := capsFromFixture(t, vec.Capabilities)
		switch vec.Expect {
		case "ok":
			c, err := CompilePolicy(vec.Desired, caps)
			if err != nil {
				t.Fatalf("%s: %v", vec.Name, err)
			}
			if c.ArtifactHash != vec.ArtifactHash {
				rawArt, _ := canon.Marshal(c.Artifact)
				t.Fatalf("%s: artifact_hash got %s want %s artifact=%s", vec.Name, c.ArtifactHash, vec.ArtifactHash, rawArt)
			}
			if c.NeedsGeneration != vec.NeedsGeneration {
				t.Fatalf("%s: needs_generation got %v want %v", vec.Name, c.NeedsGeneration, vec.NeedsGeneration)
			}
			if c.EnforcementMode != vec.EnforcementMode {
				t.Fatalf("%s: enforcement_mode got %s want %s", vec.Name, c.EnforcementMode, vec.EnforcementMode)
			}
			if len(c.Unsupported) != len(vec.Unsupported) {
				t.Fatalf("%s: unsupported got %v want %v", vec.Name, c.Unsupported, vec.Unsupported)
			}
			for i := range vec.Unsupported {
				if c.Unsupported[i] != vec.Unsupported[i] {
					t.Fatalf("%s: unsupported[%d] got %q want %q", vec.Name, i, c.Unsupported[i], vec.Unsupported[i])
				}
			}
		case "reject_unknown_keys":
			_, err := CompilePolicy(vec.Desired, caps)
			var ue *ErrUnsupported
			if err == nil || !errorsAs(err, &ue) {
				t.Fatalf("%s: want ErrUnsupported, got %v", vec.Name, err)
			}
			if vec.ErrorContains != "" && !strings.Contains(err.Error(), vec.ErrorContains) {
				t.Fatalf("%s: error %q missing %q", vec.Name, err.Error(), vec.ErrorContains)
			}
		default:
			t.Fatalf("%s: unknown expect %q", vec.Name, vec.Expect)
		}
	}
}

func capsFromFixture(t *testing.T, m map[string]any) Capabilities {
	t.Helper()
	c := Capabilities{
		Backend:                     strField(m, "backend"),
		SchemaVersion:               strField(m, "schema_version"),
		DynamicNetworkUpdate:        boolField(m, "dynamic_network_update"),
		ProviderCredentialInjection: boolField(m, "provider_credential_injection"),
		Items:                       map[string]CapabilityItem{},
	}
	items, _ := m["items"].(map[string]any)
	for k, v := range items {
		im, ok := v.(map[string]any)
		if !ok {
			t.Fatalf("bad capability item %s", k)
		}
		c.Items[k] = CapabilityItem{
			Status:    strField(im, "status"),
			Semantics: strField(im, "semantics"),
			Basis:     strField(im, "basis"),
		}
	}
	return c
}

func strField(m map[string]any, k string) string {
	s, _ := m[k].(string)
	return s
}

func boolField(m map[string]any, k string) bool {
	b, _ := m[k].(bool)
	return b
}

func policyCompileFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("caller")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "..", ".."))
	return filepath.Join(root, "packages", "contracts", "fixtures", "policy_compile_vectors_v1.json")
}

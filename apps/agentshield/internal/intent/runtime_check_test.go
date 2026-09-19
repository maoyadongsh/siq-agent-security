package intent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func runtimeCheckContractFixture() Contract {
	suffix := strings.Repeat("a", 32)
	now := time.Now().UTC()
	return Contract{SchemaVersion: RuntimeCheckSchema, AuthorityKind: "runtime_check", FilesystemProfile: string(runtimeaction.FilesystemWindowsLocalDriveV1), IntentID: "rci-" + suffix, TaskID: "rct-" + suffix, Principal: Principal{Type: "user", ID: "component-operator"}, Agent: Agent{ID: "rca-" + suffix, Platform: "hermes"}, Purpose: RuntimeCheckPurpose, AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "C:/Synthetic/runtime-check-materials/rc-" + suffix + "/allowed"}}, ParameterConstraints: []ParameterConstraint{}, IssuedAt: now.Format(time.RFC3339Nano), ValidFrom: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(120 * time.Second).Format(time.RFC3339Nano), Authority: Authority{Issuer: "local-runtime-check", Revision: strings.Repeat("b", 64), EvidenceIDs: []string{}}}
}

func TestWindowsRuntimeCheckEnvelopeIsClosed(t *testing.T) {
	c := runtimeCheckContractFixture()
	if err := c.Validate(); err != nil {
		t.Fatal(err)
	}
	for name, alter := range map[string]func(*Contract){
		"managed issuer": func(c *Contract) { c.Authority.Issuer = "local-runtime-identity" },
		"managed kind":   func(c *Contract) { c.AuthorityKind = "instance_permission" },
		"other platform": func(c *Contract) { c.Agent.Platform = "openclaw" },
		"other agent":    func(c *Contract) { c.Agent.ID = "rca-" + strings.Repeat("c", 32) },
		"other task":     func(c *Contract) { c.TaskID = "rct-" + strings.Repeat("c", 32) },
		"unknown effect": func(c *Contract) { c.AllowedEffects = []string{"unknown"} },
		"write tool":     func(c *Contract) { c.AllowedTools = []string{"write_file"} },
		"resource scope": func(c *Contract) {
			c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "C:/"}}
		},
		"other check directory": func(c *Contract) {
			c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "C:/Synthetic/runtime-check-materials/rc-" + strings.Repeat("c", 32) + "/allowed"}}
		},
		"long lifetime": func(c *Contract) {
			at, _ := time.Parse(time.RFC3339Nano, c.IssuedAt)
			c.ExpiresAt = at.Add(120*time.Second + time.Nanosecond).Format(time.RFC3339Nano)
		},
		"delayed valid from": func(c *Contract) {
			at, _ := time.Parse(time.RFC3339Nano, c.IssuedAt)
			c.ValidFrom = at.Add(time.Second).Format(time.RFC3339Nano)
		},
		"legacy downgrade":  func(c *Contract) { c.SchemaVersion = "intent/v2" },
		"managed downgrade": func(c *Contract) { c.SchemaVersion = "intent/v4" },
	} {
		t.Run(name, func(t *testing.T) {
			copy := c
			alter(&copy)
			if copy.Validate() == nil {
				t.Fatal("invalid self-check authority accepted")
			}
		})
	}
	root := c.ResourceConstraints[0].Value.(string)
	if err := c.Authorize("hermes", c.Agent.ID, c.Principal.ID, "read_file", map[string]any{"path": root + "/first.txt"}, time.Now()); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{root + "-other/first.txt", root + "/../outside", root + "/file:stream"} {
		if c.Authorize("hermes", c.Agent.ID, c.Principal.ID, "read_file", map[string]any{"path": path}, time.Now()) == nil {
			t.Fatal("invalid resource accepted")
		}
	}
}

func TestWindowsRuntimeCheckDecodeRejectsAliasesAndVersionMix(t *testing.T) {
	c := runtimeCheckContractFixture()
	raw, _ := json.Marshal(c)
	var decoded Contract
	if err := json.Unmarshal(raw, &decoded); err != nil || decoded.Validate() != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{
		strings.Replace(string(raw), `"issuer":"local-runtime-check"`, `"issuer":"local-runtime-check","issuer":"local-runtime-check"`, 1),
		strings.Replace(string(raw), `"issuer":`, `"Issuer":`, 1),
		strings.Replace(string(raw), `"intent/v5"`, `"intent/v4"`, 1),
		strings.Replace(string(raw), `"intent/v5"`, `"intent/v3"`, 1),
		strings.Replace(string(raw), `"resource_constraints":`, `"Resource_Constraints":`, 1),
		strings.TrimSuffix(string(raw), "}") + `,"effect_requirements":[]}`,
	} {
		var got Contract
		if json.Unmarshal([]byte(bad), &got) == nil && got.Validate() == nil {
			t.Fatal("version/field ambiguity accepted")
		}
	}
}

func TestWindowsRuntimeCheckStaticSignatureVector(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "intent-contract.v5.sample.json"))
	if err != nil {
		t.Fatal(err)
	}
	var c Contract
	if json.Unmarshal(raw, &c) != nil || c.Validate() != nil {
		t.Fatal("invalid v5 vector")
	}
	key, err := signing.FromSeed([]byte(strings.Repeat("\x07", 32)))
	if err != nil {
		t.Fatal(err)
	}
	m := unsignedMap(c)
	d, err := digest(m)
	if err != nil || d != c.Digest {
		t.Fatal("v5 digest differs")
	}
	m["digest"] = d
	if !signing.VerifyCanonical(key.Public(), m, c.Signature) {
		t.Fatal("v5 signature differs")
	}
}

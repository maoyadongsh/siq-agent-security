package skillcontext

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func invocationFixture(t *testing.T) InvocationContext {
	t.Helper()
	base, _ := vectorFixtures(t)
	base.SchemaVersion, base.EvidenceLevel = InvocationSchema, EvidenceInvocation
	return InvocationContext{
		Context:        base,
		AgentAuthority: AuthorityRef{GrantID: "grt-agent-baseline", GrantDigest: strings.Repeat("3", 64)},
		Loader: NativeLoadRef{LoadID: "nload-" + strings.Repeat("4", 32),
			SkillFileSHA256: strings.Repeat("5", 64), RuntimeArtifactSHA256: strings.Repeat("6", 64)},
	}
}

func TestInvocationShapeRejectsAmbiguousAuthority(t *testing.T) {
	for name, change := range map[string]func(*InvocationContext){
		"v1":                     func(c *InvocationContext) { c.SchemaVersion = Schema },
		"missing_task":           func(c *InvocationContext) { c.Subject.TaskID = "" },
		"other_agent":            func(c *InvocationContext) { c.Subject.AgentID = "hri-" + strings.Repeat("f", 32) },
		"same_grant":             func(c *InvocationContext) { c.AgentAuthority = c.Authority },
		"missing_agent_digest":   func(c *InvocationContext) { c.AgentAuthority.GrantDigest = "" },
		"missing_load":           func(c *InvocationContext) { c.Loader.LoadID = "" },
		"missing_runtime_digest": func(c *InvocationContext) { c.Loader.RuntimeArtifactSHA256 = "" },
		"missing_file_digest":    func(c *InvocationContext) { c.Loader.SkillFileSHA256 = "" },
		"unsigned_parent":        func(c *InvocationContext) { c.Parent = &ParentRef{ContextID: "sec-" + strings.Repeat("f", 32)} },
		"self_parent": func(c *InvocationContext) {
			c.Parent = &ParentRef{ContextID: c.ContextID, Signature: strings.Repeat("a", 128)}
		},
		"long_lease":           func(c *InvocationContext) { c.ExpiresAt = "2026-09-14T01:00:00.000000001Z" },
		"wrong_signing_schema": func(c *InvocationContext) { c.SigningSchema = "" },
	} {
		t.Run(name, func(t *testing.T) {
			c := invocationFixture(t)
			if err := c.Validate(); err != nil {
				t.Fatal(err)
			}
			change(&c)
			if c.Validate() == nil {
				t.Fatal("invalid invocation accepted")
			}
		})
	}
}

func TestInvocationSignatureCoversAuthorityLoaderAndParent(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(*InvocationContext){
		"agent_grant":  func(c *InvocationContext) { c.AgentAuthority.GrantID = "another-agent-grant" },
		"agent_digest": func(c *InvocationContext) { c.AgentAuthority.GrantDigest = strings.Repeat("8", 64) },
		"skill_grant":  func(c *InvocationContext) { c.Authority.GrantID = "another-skill-grant" },
		"load":         func(c *InvocationContext) { c.Loader.LoadID = "nload-" + strings.Repeat("8", 32) },
		"file":         func(c *InvocationContext) { c.Loader.SkillFileSHA256 = strings.Repeat("8", 64) },
		"runtime":      func(c *InvocationContext) { c.Loader.RuntimeArtifactSHA256 = strings.Repeat("8", 64) },
		"parent": func(c *InvocationContext) {
			c.Parent = &ParentRef{ContextID: "sec-" + strings.Repeat("8", 32), Signature: strings.Repeat("a", 128)}
		},
		"task": func(c *InvocationContext) { c.Subject.TaskID = "other-task" },
	} {
		t.Run(name, func(t *testing.T) {
			c := invocationFixture(t)
			c.Signature, err = key.SignCanonical(c.Unsigned())
			if err != nil || c.VerifySignature(key.Public()) != nil {
				t.Fatal("valid signature refused")
			}
			change(&c)
			if c.Validate() != nil {
				t.Fatal("tamper fixture must remain structurally valid")
			}
			if c.VerifySignature(key.Public()) == nil {
				t.Fatal("tampered invocation authenticated")
			}
		})
	}
}

func TestInvocationContractSampleAndV1Separation(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	c := invocationFixture(t)
	c.Signature, err = key.SignCanonical(c.Unsigned())
	if err != nil || c.VerifySignature(key.Public()) != nil {
		t.Fatal("invalid invocation")
	}
	if c.Context.Validate() == nil {
		t.Fatal("v1 must not accept v2")
	}
	if signing.VerifyWithSchema(c.SigningSchema, key.Public(), c.Context.Unsigned(), c.Signature) == nil {
		t.Fatal("removing v2 authority must invalidate signature")
	}
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	path := "../../testdata/contracts/skill-execution-context-v2.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, append(raw, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(bytes.TrimSpace(want), raw) {
		t.Fatal("v2 contract sample differs")
	}
}

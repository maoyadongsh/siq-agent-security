package skillinstall

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestWorkBuddyV2CanonicalContractVectors(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"local-skill-install-plan.v1.sample.json", "local-skill-install-plan.v2.sample.json", "local-skill-install-plan.v2.user.sample.json"} {
		t.Run(name, func(t *testing.T) {
			raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", name))
			if err != nil {
				t.Fatal(err)
			}
			value, err := canon.Decode(raw)
			if err != nil {
				t.Fatal(err)
			}
			canonical, err := canon.Marshal(value)
			if err != nil {
				t.Fatal(err)
			}
			var p Plan
			if err := (&Store{key: key}).verifySignedMetadata(canonical, &p); err != nil {
				t.Fatal("independent signature or exact typed bytes changed", err)
			}
			id, err := p.identity()
			if err != nil || id != p.PlanID || !validPlanTarget(p) {
				t.Fatal("independent identity vector changed", id, err)
			}
			if p.SchemaVersion == planV2 {
				original := p.TargetRef.TargetID
				p.TargetRef.Scope = "unknown"
				if validPlanTarget(p) {
					t.Fatal("unknown scope accepted")
				}
				p.TargetRef.Scope = "user"
				p.TargetRef.TargetID = "sit-" + strings.Repeat("0", 64)
				if validPlanTarget(p) {
					t.Fatal("target namespace substitution accepted", original)
				}
			}
		})
	}
}

func TestWorkBuddyV2TargetLocatorUsesCanonicalWindowsPath(t *testing.T) {
	instance := "hi-" + strings.Repeat("b", 32)
	a, err := ScopedTargetID(instance, "project", "C:/SIQ-Contract-Fixture/Project")
	if err != nil || a != "sit-112b9c11595f39953c2f17b24eaae94cb9315d331382b441b411d78c6a4d1a39" {
		t.Fatal(a, err)
	}
	b, err := ScopedTargetID(instance, "project", `c:\SIQ-Contract-Fixture\Project`)
	if err != nil || a != b {
		t.Fatal("unsigned accepted path spelling changed canonical locator", b, err)
	}
	c, err := ScopedTargetID(instance, "user", "C:/SIQ-Contract-Fixture/Project")
	if err != nil || c == a {
		t.Fatal("scope missing from target identity")
	}
	for _, bad := range []string{`\\server\share`, `C:\project.`, `C:\project\..`, `C:relative`, `C:\project:stream`} {
		if _, err := ScopedTargetID(instance, "project", bad); err == nil {
			t.Fatal("invalid path became a target ID", bad)
		}
	}
}

func TestWorkBuddyV2CannotUseLegacyResolverOrVersion(t *testing.T) {
	f := setup(t)
	r := f.request
	r.SchemaVersion = "local-skill-install-stage-create/v2"
	r.TargetID = "sit-" + strings.Repeat("a", 64)
	if _, _, err := f.store.Stage(nil, r); err == nil {
		t.Fatal("missing v2 resolver fell back to legacy user root")
	}
	r.SchemaVersion = "local-skill-install-stage-create/v1"
	if _, _, err := f.store.Stage(nil, r); err == nil {
		t.Fatal("v1 accepted a target selector")
	}
	if _, err := os.Lstat(filepath.Join(f.root, "skills")); !os.IsNotExist(err) {
		t.Fatal("rejected request changed host", err)
	}
}

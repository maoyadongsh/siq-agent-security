package grant

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// This exercises the signed admission/build/convert path. The HTTP boundary
// separately verifies the persistent imported snapshot before publishing.
func windowsImportedFixture(t *testing.T, platform string) (Grant, ResourceEdit) {
	t.Helper()
	_, input, _ := windowsResources(t)
	sourceDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(sourceDir, "SKILL.md"), []byte("---\nname: windows-import\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\nRead a synthetic report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	admitted, err := admission.Admit(sourceDir, admission.Options{Key: key(t), Pack: pack, Version: "fixture"})
	if err != nil {
		t.Fatal(err)
	}
	source := importsource.Source{SchemaVersion: "local-skill-import-permission-source/v1", ImportID: "si-" + strings.Repeat("a", 32), ArtifactDigest: strings.Repeat("b", 64), AnalysisSHA256: strings.Repeat("c", 64)}
	bound, err := source.Bind(admitted.Admission, key(t))
	if err != nil {
		t.Fatal(err)
	}
	built, err := BuildImported(bound, Options{Key: key(t), Platform: platform, Subject: Subject{Type: "agent_instance", ID: "hri-" + strings.Repeat("d", 32)}}, "fixture-operator", "ip-"+strings.Repeat("e", 32))
	if err != nil || built.Grant.Skill == nil {
		t.Fatal("imported fixture lost Skill identity", err)
	}
	return built.Grant, input
}

func TestWindowsImportedSkillProfileRetainsSourceAndAttribution(t *testing.T) {
	for _, platform := range []string{"workbuddy", "hermes", "openclaw"} {
		t.Run(platform, func(t *testing.T) {
			original, input := windowsImportedFixture(t, platform)
			before, _ := json.Marshal(original)
			converted, _, err := PrepareWindowsResources(original, input, true, key(t))
			if err != nil {
				t.Fatal("signed imported Skill could not select Windows resources", err)
			}
			after, _ := json.Marshal(original)
			if !bytes.Equal(before, after) || converted.AdmissionID != original.AdmissionID || converted.GrantID != original.GrantID ||
				!reflect.DeepEqual(converted.Skill, original.Skill) || converted.Subject != original.Subject || converted.Status != "pending_approval" || converted.ApprovedBy != nil || converted.EffectiveReadback != nil {
				t.Fatal("Windows conversion changed source, Skill, original bytes or approval")
			}
			if !Verify(key(t).Public(), converted) || RecheckFilesystemBindings(converted) != nil {
				t.Fatal("new imported grant lacks signed Windows file identity")
			}
			raw, _ := json.Marshal(converted)
			var restored Grant
			if json.Unmarshal(raw, &restored) != nil || !Verify(key(t).Public(), restored) || !reflect.DeepEqual(restored.Skill, original.Skill) {
				t.Fatal("signed Skill/profile could not round trip")
			}
			approved, err := Approve(restored, human(), key(t))
			if err != nil {
				t.Fatal(err)
			}
			if _, err := MarkDeployed(approved, key(t)); err != ErrImportInstallationRequired {
				t.Fatal("Windows conversion bypassed installed Skill requirement", err)
			}
			if _, err := MarkEffective(approved, Readback{}, nil, key(t)); err != ErrImportInstallationRequired {
				t.Fatal("Windows imported grant acquired ordinary effective authority", err)
			}
			if revoked, err := Revoke(approved, key(t)); err != nil || !Verify(key(t).Public(), revoked) || !reflect.DeepEqual(revoked.Skill, original.Skill) {
				t.Fatal("revocation discarded Skill provenance", err)
			}
		})
	}
}

func TestWindowsImportedSkillProfileRejectsMissingOrForeignIdentity(t *testing.T) {
	original, input := windowsImportedFixture(t, "workbuddy")
	for name, change := range map[string]func(*Grant){
		"ordinary-skill":      func(g *Grant) { g.AdmissionID = "adm-4af17a9f9719" },
		"malformed-import-id": func(g *Grant) { g.AdmissionID = "adm-si-forged" },
		"missing-skill":       func(g *Grant) { g.Skill = nil },
		"missing-skill-id":    func(g *Grant) { g.Skill.SkillID = "" },
		"bad-content":         func(g *Grant) { g.Skill.ContentHash = "not-a-content-hash" },
		"unmanaged-subject":   func(g *Grant) { g.Subject.ID = "model-chosen-instance" },
		"asset-subject":       func(g *Grant) { g.Subject.Type = "agent_asset" },
	} {
		t.Run(name, func(t *testing.T) {
			raw, _ := json.Marshal(original)
			var changed Grant
			if err := json.Unmarshal(raw, &changed); err != nil {
				t.Fatal(err)
			}
			change(&changed)
			resign(key(t), &changed)
			if _, _, err := PrepareWindowsResources(changed, input, true, key(t)); err != ErrFilesystemProfile {
				t.Fatal("invalid imported identity converted to Windows authority", err)
			}
		})
	}
	if _, _, err := PrepareWindowsResources(original, input, false, key(t)); err != ErrFilesystemProfile {
		t.Fatal("import provenance substituted for explicit profile confirmation", err)
	}
	converted, _, err := PrepareWindowsResources(original, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	converted.Skill = nil
	resign(key(t), &converted)
	if Verify(key(t).Public(), converted) || ValidateFilesystemProfile(converted) != ErrFilesystemProfile {
		t.Fatal("dropping Skill converted imported Windows grant into a baseline")
	}
}

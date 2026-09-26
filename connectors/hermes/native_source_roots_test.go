package main

import (
	"encoding/json"
	"path/filepath"
	"testing"
)

// Exercise actual NDJSON output, not production collection helpers. All files
// and HOME are synthetic; custom roots are passed explicitly, never inferred
// from the developer's HERMES_HOME or environment.
func TestNativeProfileLayoutsAndSourceV2(t *testing.T) {
	home := t.TempDir()
	standard := filepath.Join(home, ".hermes")
	named := filepath.Join(standard, "profiles", "sample")
	custom := filepath.Join(home, "custom-profile")
	config := "model:\n  default: fixture\n"
	for _, dir := range []string{standard, named, custom} {
		writeFixtureFile(t, filepath.Join(dir, "config.yaml"), config, 0600)
		writeFixtureFile(t, filepath.Join(dir, "SOUL.md"), "fixture", 0600)
	}
	session := startNativeSession(t, home)
	batch, _ := session.collect(t, "named-only", []string{"~/.hermes/profiles/*"}, []string{"config.yaml"}, 10, 4096)
	if candidates := indexCandidates(t, batch); len(candidates) != 1 || candidates[wantCandidateID(named)] == nil {
		t.Fatal("explicit named-profile scope expanded or missed its profile")
	}
	batch, _ = session.collect(t, "explicit-layouts", []string{"~/.hermes", "~/.hermes/profiles/*", custom}, []string{"config.yaml"}, 10, 4096)
	checkReferenceIntegrity(t, batch)
	candidates, evidence := indexCandidates(t, batch), indexEvidence(t, batch)
	if len(candidates) != 3 || len(evidence) != 3 {
		t.Fatal("explicit roots must produce exactly three distinct configuration sources")
	}
	for _, dir := range []string{standard, named, custom} {
		candidate := candidates[wantCandidateID(dir)]
		if candidate == nil {
			t.Fatal("missing path-bound profile")
		}
		attrs := attributesOf(t, candidate)
		var source map[string]string
		if err := json.Unmarshal([]byte(strOf(t, attrs, "framework_source")), &source); err != nil || len(source) != 5 {
			t.Fatal("source wire shape")
		}
		if source["schema_version"] != "enterprise-framework-source/v2" || source["framework"] != "hermes" || source["instance_key"] != sha256Hex([]byte(dir)) || source["config_sha256"] != sha256Hex([]byte(config)) || source["evidence_id"] != wantEvidenceID(dir, "config.yaml") {
			t.Fatal("source wire binding")
		}
		if evidence[source["evidence_id"]] == nil {
			t.Fatal("source references missing evidence")
		}
		if filepath.Separator == '/' {
			var roots map[string]any
			if err := json.Unmarshal([]byte(strOf(t, attrs, "skill_source_roots")), &roots); err != nil || len(roots) != 4 {
				t.Fatal("roots wire shape")
			}
			if roots["schema_version"] != "enterprise-role-skill-roots/v2" || roots["basis"] != "hermes_profile_layout" || roots["status"] != "layout_candidate" {
				t.Fatal("roots semantic boundary")
			}
			items := listOf(t, roots, "roots")
			if len(items) != 1 {
				t.Fatal("unexpected layout root count")
			}
			root := mapOf(t, items[0], "root")
			if len(root) != 2 || root["kind"] != "profile_skills" || root["locator_sha256"] != sha256Hex([]byte(filepath.Join(dir, "skills"))) {
				t.Fatal("layout path hash differs from independent formula")
			}
		}
	}
	batch, _ = session.collect(t, "soul-only", []string{custom}, []string{"SOUL.md"}, 10, 4096)
	if len(indexCandidates(t, batch)) != 1 {
		t.Fatal("SOUL fixture was not collected")
	}
	for _, candidate := range indexCandidates(t, batch) {
		attrs := attributesOf(t, candidate)
		if _, exists := attrs["framework_source"]; exists {
			t.Fatal("excluded config acquired source")
		}
		if _, exists := attrs["skill_source_roots"]; exists {
			t.Fatal("excluded config acquired layout")
		}
	}
}

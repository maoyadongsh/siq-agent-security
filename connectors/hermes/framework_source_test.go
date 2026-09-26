package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestHermesSourceRequiresCompleteIncludedConfig(t *testing.T) {
	for _, mode := range []string{"complete", "truncated", "soul_only"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			config := []byte("model: fixture-model\n")
			if os.WriteFile(filepath.Join(root, "config.yaml"), config, 0600) != nil || os.WriteFile(filepath.Join(root, "SOUL.md"), []byte("fixture"), 0600) != nil {
				t.Fatal("fixture write")
			}
			include, budget := []string{"config.yaml"}, int64(1024)
			if mode == "truncated" {
				budget = 8
			}
			if mode == "soul_only" {
				include = []string{"SOUL.md"}
			}
			batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}, Include: include}, Limits: protocol.CollectLimits{MaxFiles: 5, MaxBytes: budget}})
			if err != nil || len(batch.Candidates) != 1 {
				t.Fatalf("collection: %v", err)
			}
			raw, exists := batch.Candidates[0].Attributes["framework_source"]
			if mode != "complete" {
				if exists || batch.Candidates[0].Attributes["skill_source_roots"] != "" {
					t.Fatal("partial or excluded config acquired source")
				}
				return
			}
			var source map[string]string
			if json.Unmarshal([]byte(raw), &source) != nil || len(source) != 5 {
				t.Fatal("source shape")
			}
			if source["schema_version"] != "enterprise-framework-source/v2" || source["framework"] != "hermes" || source["instance_key"] != protocol.ContentHash([]byte(root)) || source["config_sha256"] != protocol.ContentHash(config) {
				t.Fatal("source identity")
			}
			if len(batch.Evidence) != 1 || source["evidence_id"] != batch.Evidence[0].EvidenceID || source["config_sha256"] != batch.Evidence[0].ContentHash {
				t.Fatal("source evidence mismatch")
			}
			if filepath.Separator == '/' {
				var roots struct {
					Schema string `json:"schema_version"`
					Basis  string `json:"basis"`
					Status string `json:"status"`
					Roots  []struct {
						Kind   string `json:"kind"`
						Digest string `json:"locator_sha256"`
					} `json:"roots"`
				}
				sum := sha256.Sum256([]byte(filepath.Join(root, "skills")))
				if err := json.Unmarshal([]byte(batch.Candidates[0].Attributes["skill_source_roots"]), &roots); err != nil || roots.Schema != "enterprise-role-skill-roots/v2" || roots.Basis != "hermes_profile_layout" || roots.Status != "layout_candidate" || len(roots.Roots) != 1 || roots.Roots[0].Kind != "profile_skills" || roots.Roots[0].Digest != hex.EncodeToString(sum[:]) {
					t.Fatal("profile layout roots")
				}
				if _, err := os.Stat(filepath.Join(root, "skills")); !os.IsNotExist(err) {
					t.Fatal("layout report must not create skills directory")
				}
			}
		})
	}
}

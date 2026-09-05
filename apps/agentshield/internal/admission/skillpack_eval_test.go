package admission

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func skillPackRoot(t *testing.T) string {
	t.Helper()
	root := filepath.Join("..", "..", "..", "..", "skills", "siq-agent-security")
	if _, err := os.Stat(filepath.Join(root, "SKILL.md")); err != nil {
		t.Skip("skills/siq-agent-security not present")
	}
	return root
}

func TestAgentShieldSkillIsNotQuarantined(t *testing.T) {
	root := skillPackRoot(t)
	res, err := Admit(root, testOpts(t, root, "unknown"))
	if err != nil {
		t.Fatal(err)
	}
	if res.Admission.Verdict == "quarantine" {
		t.Fatalf("self-scan must not quarantine: %v", findingRules(res, dispQuarantine))
	}
	if res.Admission.Verdict != "admit_with_conditions" {
		t.Fatalf("this skill declares terminal/read_file so verdict should be admit_with_conditions, got %s (%v)", res.Admission.Verdict, findingRules(res, ""))
	}
	if findingRules(res, dispQuarantine)["adm-user-deception"] || findingRules(res, dispQuarantine)["adm-credential-path"] {
		t.Fatalf("self-scan raised a hard finding: %v", findingRules(res, dispQuarantine))
	}
}

func TestSkillPackEvalsJSON(t *testing.T) {
	root := skillPackRoot(t)
	raw, err := os.ReadFile(filepath.Join(root, "evals", "evals.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		ID                  string   `json:"id"`
		Type                string   `json:"type"`
		Fixture             string   `json:"fixture"`
		ExpectedVerdict     string   `json:"expected_verdict"`
		ExpectedExit        int      `json:"expected_exit"`
		MustIncludeRules    []string `json:"must_include_rules"`
		MustNotIncludeRules []string `json:"must_not_include_rules"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) < 5 {
		t.Fatal("evals.json must cover the shipped fixtures")
	}
	for _, c := range cases {
		if c.Type == "routing_negative" || c.Fixture == "" {
			continue
		}
		t.Run(c.ID, func(t *testing.T) {
			dir := filepath.Join(root, "evals", c.Fixture)
			res, err := Admit(dir, testOpts(t, dir, "unknown"))
			if err != nil {
				t.Fatal(err)
			}
			if res.Admission.Verdict != c.ExpectedVerdict {
				t.Fatalf("verdict=%s want %s q=%v all=%v", res.Admission.Verdict, c.ExpectedVerdict, findingRules(res, dispQuarantine), findingRules(res, ""))
			}
			have := findingRules(res, "")
			for _, r := range c.MustIncludeRules {
				if !have[r] {
					t.Fatalf("missing rule %s in %v", r, have)
				}
			}
			q := findingRules(res, dispQuarantine)
			for _, r := range c.MustNotIncludeRules {
				if q[r] {
					t.Fatalf("rule %s must not quarantine", r)
				}
			}
		})
	}
}

func TestSkillDescriptionBound(t *testing.T) {
	root := skillPackRoot(t)
	raw, err := os.ReadFile(filepath.Join(root, "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	fm := parseFrontmatter(string(raw))
	d := fm.Fields["description"]
	if d == "" || d[len(d)-1] != '.' || len([]rune(d)) > 60 {
		t.Fatalf("description must be ≤60 chars, one sentence, period-terminated: %q (%d)", d, len([]rune(d)))
	}
	if fm.Fields["name"] != "siq-agent-security" {
		t.Fatalf("name=%s", fm.Fields["name"])
	}
}

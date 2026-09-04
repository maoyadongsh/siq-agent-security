package threat

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// Shared corpus with the Python baseline (docs/detection-baseline.md).
const corpusPath = "../../../control-api/app/tests/fixtures/threat/corpus.json"

type sample struct {
	ID       string `json:"id"`
	Label    string `json:"label"`
	Category string `json:"category"`
	RuleID   string `json:"rule_id"`
	Filename string `json:"filename"`
	Content  string `json:"content"`
}

func loadCorpus(t *testing.T) []sample {
	t.Helper()
	raw, err := os.ReadFile(corpusPath)
	if err != nil {
		t.Skipf("shared corpus not available: %v", err)
	}
	var doc struct {
		Samples []sample `json:"samples"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	return doc.Samples
}

func analyzer(t *testing.T) *Analyzer {
	t.Helper()
	p, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	return New(p)
}

func ruleIDs(r Result) map[string]bool {
	out := map[string]bool{}
	for _, m := range r.Matches {
		out[m.RuleID] = true
	}
	return out
}

// Parity with the Python engine on the shared corpus: every malicious sample
// must hit its labelled rule, every benign sample must be clean, and the one
// recorded false positive must still fire (so a future rule change that fixes
// it forces the corpus and both implementations to be updated together).
func TestCorpusParityWithPython(t *testing.T) {
	a := analyzer(t)
	var malicious, benign int
	for _, s := range loadCorpus(t) {
		got := ruleIDs(a.Analyze([]byte(s.Content), s.Filename, ""))
		switch s.Label {
		case "malicious":
			malicious++
			if !got[s.RuleID] {
				t.Errorf("%s: expected %s, got %v", s.ID, s.RuleID, keys(got))
			}
		case "benign":
			benign++
			if len(got) != 0 {
				t.Errorf("%s: benign sample produced %v", s.ID, keys(got))
			}
		case "benign_known_fp":
			if !got[s.RuleID] {
				t.Errorf("%s: recorded false positive %s no longer fires; update corpus + detection-baseline.md", s.ID, s.RuleID)
			}
		default:
			t.Errorf("%s: unknown label %q", s.ID, s.Label)
		}
	}
	if malicious < 20 || benign < 10 {
		t.Fatalf("corpus too small: malicious=%d benign=%d", malicious, benign)
	}
}

// Every rulepack rule (regex layer) must be exercised by the corpus, so the Go
// port cannot silently lose coverage relative to Python.
func TestEveryRuleCoveredByCorpus(t *testing.T) {
	a := analyzer(t)
	covered := map[string]bool{}
	for _, s := range loadCorpus(t) {
		if s.Label != "malicious" {
			continue
		}
		for id := range ruleIDs(a.Analyze([]byte(s.Content), s.Filename, "")) {
			covered[id] = true
		}
	}
	for _, r := range a.pack.Rules {
		if !covered[r.ID] {
			t.Errorf("rule %s never fires on the shared corpus", r.ID)
		}
	}
}

func TestCrontabRewriteKeepsPythonSemantics(t *testing.T) {
	// The negative lookahead (?![el]\b) was rewritten for RE2; these cases were
	// verified against the original pattern under CPython before the change.
	a := analyzer(t)
	hit := map[string]bool{
		"crontab -e":         false,
		"crontab -l":         false,
		"crontab -r":         true,
		"crontab -":          true,
		"crontab -ee":        true,
		"crontab -u root f":  true,
		"echo x | crontab":   true,
		"crontab -l > b":     false,
		"crontab -eX":        true,
		"systemctl status x": false,
	}
	for line, want := range hit {
		got := ruleIDs(a.Analyze([]byte(line+"\n"), "job.sh", ""))["threat-persist-crontab"]
		if got != want {
			t.Errorf("%q: crontab rule hit=%v want %v", line, got, want)
		}
	}
}

func TestExcerptIsRedactedAndTruncated(t *testing.T) {
	a := analyzer(t)
	secret := "sk-" + strings.Repeat("A", 40)
	r := a.Analyze([]byte("OPENAI_API_KEY=\""+secret+"\"\n"), "conf.sh", "")
	if len(r.Matches) == 0 {
		t.Fatal("hardcoded secret must be detected")
	}
	for _, m := range r.Matches {
		if strings.Contains(m.Excerpt, secret) {
			t.Fatalf("excerpt leaked secret: %s", m.Excerpt)
		}
		if len([]rune(m.Excerpt)) > ExcerptMax {
			t.Fatalf("excerpt longer than %d: %q", ExcerptMax, m.Excerpt)
		}
		if len(m.ExcerptSHA256) != 64 {
			t.Fatalf("excerpt_sha256 must be hex sha256")
		}
	}
}

func TestDetectTypeMirrorsPython(t *testing.T) {
	cases := []struct {
		content, filename, want string
	}{
		{"\x7fELF\x01\x02", "", "binary"},
		{"MZ\x90\x00", "", "binary"},
		{"PK\x03\x04", "skill.zip", "binary"},
		{"#!/usr/bin/env python3\nprint(1)\n", "", "python"},
		{"#!/bin/bash\nls\n", "", "shell"},
		{"#!/usr/bin/env pwsh\n", "", "powershell"},
		{"#!/usr/bin/env node\n", "", "javascript"},
		{"plain\x00text", "", "binary"},
		{"echo hi", "run.sh", "shell"},
		{"console.log(1)", "x.mjs", "javascript"},
		{"import os\n", "", "python"},
		{"just prose", "", "unknown"},
		{"\xff\xfe\xfd", "", "binary"},
	}
	for _, c := range cases {
		if got := DetectType([]byte(c.content), c.filename, ""); got != c.want {
			t.Errorf("DetectType(%q,%q)=%s want %s", c.content, c.filename, got, c.want)
		}
	}
	if got := DetectType([]byte("x"), "", "text/x-python; charset=utf-8"); got != "python" {
		t.Errorf("content-type hint ignored: %s", got)
	}
}

func TestFirstHitPerRuleOnly(t *testing.T) {
	a := analyzer(t)
	r := a.Analyze([]byte("curl a | sh\ncurl b | bash\n"), "x.sh", "")
	n := 0
	for _, m := range r.Matches {
		if m.RuleID == "threat-download-exec-pipe" {
			n++
			if m.Line != 1 {
				t.Fatalf("first hit must be line 1, got %d", m.Line)
			}
		}
	}
	if n != 1 {
		t.Fatalf("rule must be recorded once per blob, got %d", n)
	}
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

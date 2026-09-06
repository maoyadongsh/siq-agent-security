// Package threat is the Go port of apps/control-api/app/threat_analysis.py:
// a purely static analyzer (never executes or imports the analysed content).
//
// Parity contract with the Python implementation (checked against the shared
// corpus in threat_test.go):
//   - identical type sniffing (magic bytes, shebang, NUL, extension, content
//     type, Python marker) with "unknown" when evidence is insufficient;
//   - each rule records only its first line hit; excerpt is redacted with the
//     pack's redaction patterns and truncated to 40 characters; excerpt_sha256
//     is computed over the un-redacted hit;
//   - shell joins POSIX trailing-backslash continuations; powershell joins
//     trailing-backtick continuations before regex matching; other types keep
//     physical lines.
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
// Shell joins POSIX “\“ and DEV06-E pseudo pipe (next line starts with “|“);
// PowerShell joins trailing “ ` “ and the same pseudo-pipe heuristic.
func (a *Analyzer) Analyze(content []byte, filename, contentType string) Result {
	sum := sha256.Sum256(content)
	detected := DetectType(content, filename, contentType)
	res := Result{SHA256: hex.EncodeToString(sum[:]), DetectedType: detected, Matches: []Match{}}
	text := strings.ToValidUTF8(string(content), "\uFFFD")
	lines := scanLines(text, detected)
	for _, rule := range a.pack.Rules {
	scan:
		for _, sl := range lines {
			for _, p := range rule.Patterns {
				if loc := p.FindStringIndex(sl.Text); loc != nil {
					res.Matches = append(res.Matches, a.makeMatch(rule, sl.Line, sl.Text[loc[0]:loc[1]]))
					break scan
				}
			}
		}
	}
	return res
}

type scanLine struct {
	Line int
	Text string
}

// scanLines mirrors Python _scan_lines:
//   - shell: join trailing POSIX “\“ continuations (H5a / DEV06-B)
//   - powershell: join trailing backtick continuations (DEV06-D)
//   - shell and powershell: also join when the next physical line starts with “|“
//     after optional whitespace (DEV06-E pseudo pipe; join without embedding “\n“
//     so patterns that forbid newlines still match)
//   - other types: physical lines only
func scanLines(s, detected string) []scanLine {
	physical := splitLines(s)
	var contSuffix string
	switch detected {
	case "shell":
		contSuffix = `\`
	case "powershell":
		contSuffix = "`"
	default:
		out := make([]scanLine, len(physical))
		for i, line := range physical {
			out[i] = scanLine{Line: i + 1, Text: line}
		}
		return out
	}
	out := make([]scanLine, 0, len(physical))
	for i := 0; i < len(physical); {
		start := i + 1
		buf := physical[i]
		i++
		for i < len(physical) {
			if contSuffix != "" && strings.HasSuffix(buf, contSuffix) {
				buf = strings.TrimSuffix(buf, contSuffix) + physical[i]
				i++
				continue
			}
			if pipeContinuationLine(physical[i]) {
				// Drop trailing spaces on the left fragment so "| bash" attaches cleanly.
				buf = strings.TrimRight(buf, " \t") + strings.TrimLeft(physical[i], " \t")
				i++
				continue
			}
			break
		}
		out = append(out, scanLine{Line: start, Text: buf})
	}
	return out
}

func pipeContinuationLine(line string) bool {
	return strings.HasPrefix(strings.TrimLeft(line, " \t"), "|")
}

// splitLines mirrors Python str.splitlines() separators used by the control-plane
// analyzer (DEV06-G / M-D2): LF, CR, CRLF, VT, FF, file/group/record separators,
// NEL (U+0085), LS (U+2028), PS (U+2029). A trailing terminator does not create
// an empty final line beyond what Split yields after TrimSuffix.
func splitLines(s string) []string {
	if s == "" {
		return nil
	}
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		i += size
		switch r {
		case '\r':
			if i < len(s) {
				nr, nsize := utf8.DecodeRuneInString(s[i:])
				if nr == '\n' {
					i += nsize
				}
			}
			b.WriteByte('\n')
		case '\n', '\v', '\f', '\x1c', '\x1d', '\x1e', '\u0085', '\u2028', '\u2029':
			b.WriteByte('\n')
		default:
			b.WriteRune(r)
		}
	}
	out := strings.TrimSuffix(b.String(), "\n")
	return strings.Split(out, "\n")
}

func itoa(i int) string { return strconv.Itoa(i) }

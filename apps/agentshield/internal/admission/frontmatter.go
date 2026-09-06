package admission

import (
	"regexp"
	"strings"
)

// Frontmatter is the subset of SKILL.md YAML frontmatter that admission
// understands (dev-spec §3.6.3). It is deliberately not a YAML parser: flat
// "key: value", inline lists "[a, b]", block lists "- x" and one nested map
// level ("metadata:"). Anything else is reported as an unparsed key.
type Frontmatter struct {
	Present  bool
	Valid    bool
	Fields   map[string]string   // scalar values
	Lists    map[string][]string // list values (allowed-tools, platforms, ...)
	Nested   map[string]map[string]string
	Unparsed []string
	Body     string // markdown after the closing ---
	EndLine  int    // 1-based line number of closing ---
}

var (
	kvRe      = regexp.MustCompile(`^([A-Za-z0-9_-]+):\s*(.*)$`)
	nestedKV  = regexp.MustCompile(`^\s{2,}([A-Za-z0-9_.-]+):\s*(.*)$`)
	listItem  = regexp.MustCompile(`^\s*-\s+(.*)$`)
	skillName = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)
)

// parseFrontmatter splits SKILL.md into frontmatter and body.
func parseFrontmatter(text string) Frontmatter {
	fm := Frontmatter{Fields: map[string]string{}, Lists: map[string][]string{}, Nested: map[string]map[string]string{}}
	text = strings.ReplaceAll(text, "\r\n", "\n")
	if !strings.HasPrefix(text, "---\n") {
		fm.Body = text
		return fm
	}
	fm.Present = true
	rest := text[4:]
	end := strings.Index(rest, "\n---\n")
	closeAtEOF := false
	if end < 0 {
		if strings.HasSuffix(rest, "\n---") {
			end = len(rest) - 4
			closeAtEOF = true
		} else {
			fm.Body = text
			return fm
		}
	}
	block := rest[:end]
	if closeAtEOF {
		fm.Body = ""
	} else {
		fm.Body = rest[end+5:]
	}
	fm.EndLine = strings.Count(block, "\n") + 3
	fm.Valid = true

	lines := strings.Split(block, "\n")
	var curList string
	var curNested string
	for _, line := range lines {
		if strings.TrimSpace(line) == "" || strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		if curList != "" {
			if m := listItem.FindStringSubmatch(line); m != nil {
				fm.Lists[curList] = append(fm.Lists[curList], unquote(m[1]))
				continue
			}
			curList = ""
		}
		if curNested != "" {
			if m := nestedKV.FindStringSubmatch(line); m != nil {
				fm.Nested[curNested][m[1]] = unquote(m[2])
				continue
			}
			if strings.HasPrefix(line, " ") {
				fm.Unparsed = append(fm.Unparsed, curNested+"."+strings.TrimSpace(line))
				continue
			}
			curNested = ""
		}
		m := kvRe.FindStringSubmatch(line)
		if m == nil {
			fm.Unparsed = append(fm.Unparsed, strings.TrimSpace(line))
			continue
		}
		key, val := m[1], strings.TrimSpace(m[2])
		switch {
		case val == "":
			// block list or nested map follows; decide by next non-empty line prefix
			curList, curNested = key, key
			fm.Nested[key] = map[string]string{}
		case strings.HasPrefix(val, "[") && strings.HasSuffix(val, "]"):
			inner := strings.TrimSpace(val[1 : len(val)-1])
			if inner == "" {
				fm.Lists[key] = []string{}
				break
			}
			for _, item := range strings.Split(inner, ",") {
				fm.Lists[key] = append(fm.Lists[key], unquote(strings.TrimSpace(item)))
			}
		default:
			fm.Fields[key] = unquote(val)
		}
	}
	// a key that opened a block but received neither list items nor nested
	// pairs is a scalar with empty value
	for k, nested := range fm.Nested {
		if len(nested) == 0 {
			if _, isList := fm.Lists[k]; !isList {
				fm.Fields[k] = ""
			}
			delete(fm.Nested, k)
		}
	}
	return fm
}

func unquote(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 2 && ((s[0] == '"' && s[len(s)-1] == '"') || (s[0] == '\'' && s[len(s)-1] == '\'')) {
		return s[1 : len(s)-1]
	}
	return s
}

// allowedTools returns the declared tool list: either the `allowed-tools`
// list form or the agentskills.io space-separated string form.
func (fm Frontmatter) allowedTools() []string {
	if l, ok := fm.Lists["allowed-tools"]; ok {
		return dedupe(l)
	}
	if s, ok := fm.Fields["allowed-tools"]; ok && s != "" {
		parts := strings.FieldsFunc(s, func(r rune) bool { return r == ' ' || r == ',' })
		return dedupe(parts)
	}
	return nil
}

func dedupe(in []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(in))
	for _, s := range in {
		s = strings.TrimSpace(s)
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

// sanitizeName produces a schema-valid skill_name from an arbitrary string.
func sanitizeName(s string) string {
	s = strings.ToLower(s)
	var b strings.Builder
	lastDash := true
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
			lastDash = false
		default:
			if !lastDash {
				b.WriteByte('-')
				lastDash = true
			}
		}
	}
	out := strings.Trim(b.String(), "-")
	if out == "" {
		return "unnamed-skill"
	}
	if len(out) > 64 {
		out = strings.Trim(out[:64], "-")
	}
	return out
}

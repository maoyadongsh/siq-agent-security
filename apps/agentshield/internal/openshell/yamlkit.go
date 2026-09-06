package openshell

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode"
)

// parseYAML loads the indent-based subset emitted by `policy get --full`.
// It is not a general YAML 1.1 parser: unknown constructs fail closed.
func parseYAML(src string) (any, error) {
	lines, err := yamlLines(src)
	if err != nil {
		return nil, err
	}
	if len(lines) == 0 {
		return map[string]any{}, nil
	}
	p := &yamlParser{lines: lines}
	v, err := p.parseBlock(-1)
	if err != nil {
		return nil, err
	}
	if p.i < len(p.lines) {
		return nil, failf("策略 YAML 解析失败（fail-closed）: trailing content at indent %d", p.lines[p.i].indent)
	}
	return v, nil
}

type yamlLine struct {
	indent  int
	content string
	no      int
}

type yamlParser struct {
	lines []yamlLine
	i     int
}

func (p *yamlParser) peek() *yamlLine {
	if p.i >= len(p.lines) {
		return nil
	}
	return &p.lines[p.i]
}

func (p *yamlParser) parseBlock(parentIndent int) (any, error) {
	n := p.peek()
	if n == nil || n.indent <= parentIndent {
		return nil, nil
	}
	if isYAMLSeqItem(n.content) {
		return p.parseSeq(parentIndent)
	}
	return p.parseMap(parentIndent)
}

func (p *yamlParser) parseMap(parentIndent int) (map[string]any, error) {
	m := map[string]any{}
	expected := -1
	for {
		n := p.peek()
		if n == nil || n.indent <= parentIndent {
			break
		}
		if isYAMLSeqItem(n.content) {
			return nil, failf("策略 YAML 解析失败（fail-closed）: sequence item in mapping (line %d)", n.no)
		}
		if expected < 0 {
			expected = n.indent
		}
		if n.indent != expected {
			return nil, failf("策略 YAML 解析失败（fail-closed）: inconsistent indent (line %d)", n.no)
		}
		key, rest, ok := splitYAMLKey(n.content)
		if !ok {
			return nil, failf("策略 YAML 解析失败（fail-closed）: expected mapping key (line %d)", n.no)
		}
		p.i++
		if rest == "" {
			next := p.peek()
			switch {
			case next != nil && next.indent > expected:
				v, err := p.parseBlock(expected)
				if err != nil {
					return nil, err
				}
				m[key] = v
			case next != nil && next.indent == expected && isYAMLSeqItem(next.content):
				// PyYAML indentless sequence: the dashes sit at the key indent.
				v, err := p.parseSeq(expected - 1)
				if err != nil {
					return nil, err
				}
				m[key] = v
			default:
				m[key] = nil
			}
			continue
		}
		m[key] = parseYAMLScalar(rest)
	}
	return m, nil
}

func (p *yamlParser) parseSeq(parentIndent int) ([]any, error) {
	var seq []any
	expected := -1
	for {
		n := p.peek()
		if n == nil || n.indent <= parentIndent {
			break
		}
		if !isYAMLSeqItem(n.content) {
			break
		}
		if expected < 0 {
			expected = n.indent
		}
		if n.indent != expected {
			break
		}
		item := ""
		if strings.HasPrefix(n.content, "- ") {
			item = strings.TrimSpace(n.content[2:])
		}
		p.i++
		if item == "" {
			v, err := p.parseBlock(expected)
			if err != nil {
				return nil, err
			}
			seq = append(seq, v)
			continue
		}
		if key, rest, ok := splitYAMLKey(item); ok {
			inner := map[string]any{key: nil}
			if rest != "" {
				inner[key] = parseYAMLScalar(rest)
			} else {
				next := p.peek()
				if next != nil && next.indent > expected {
					v, err := p.parseBlock(expected)
					if err != nil {
						return nil, err
					}
					inner[key] = v
				}
			}
			if p.peek() != nil && p.peek().indent > expected && !strings.HasPrefix(p.peek().content, "-") {
				more, err := p.parseMap(expected)
				if err != nil {
					return nil, err
				}
				for k, v := range more {
					inner[k] = v
				}
			}
			seq = append(seq, inner)
			continue
		}
		seq = append(seq, parseYAMLScalar(item))
	}
	return seq, nil
}

func isYAMLSeqItem(content string) bool {
	return strings.HasPrefix(content, "- ") || content == "-"
}

func yamlLines(src string) ([]yamlLine, error) {
	var out []yamlLine
	for i, raw := range strings.Split(src, "\n") {
		raw = strings.TrimRight(raw, "\r")
		s, err := stripYAMLComment(raw)
		if err != nil {
			return nil, err
		}
		if strings.TrimSpace(s) == "" {
			continue
		}
		indent := 0
		for _, r := range s {
			if r == ' ' {
				indent++
				continue
			}
			if r == '\t' {
				return nil, fail("策略 YAML 解析失败（fail-closed）: tabs not allowed")
			}
			break
		}
		out = append(out, yamlLine{indent: indent, content: strings.TrimSpace(s), no: i + 1})
	}
	return out, nil
}

func stripYAMLComment(s string) (string, error) {
	inSingle, inDouble, escape := false, false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		if escape {
			escape = false
			continue
		}
		if inDouble && c == '\\' {
			escape = true
			continue
		}
		if !inDouble && c == '\'' {
			inSingle = !inSingle
			continue
		}
		if !inSingle && c == '"' {
			inDouble = !inDouble
			continue
		}
		if !inSingle && !inDouble && c == '#' {
			if i == 0 || s[i-1] == ' ' {
				return s[:i], nil
			}
		}
	}
	if inSingle || inDouble {
		return "", fail("策略 YAML 解析失败（fail-closed）: unterminated quote")
	}
	return s, nil
}

func splitYAMLKey(s string) (key, rest string, ok bool) {
	i := strings.IndexByte(s, ':')
	if i <= 0 {
		return "", "", false
	}
	key = s[:i]
	for _, r := range key {
		if unicode.IsSpace(r) {
			return "", "", false
		}
	}
	rest = strings.TrimSpace(s[i+1:])
	return key, rest, true
}

func parseYAMLScalar(s string) any {
	if s == "~" || s == "null" || s == "Null" || s == "NULL" {
		return nil
	}
	switch s {
	case "true", "True", "TRUE", "yes", "Yes", "YES":
		return true
	case "false", "False", "FALSE", "no", "No", "NO":
		return false
	}
	if len(s) >= 2 {
		if (s[0] == '\'' && s[len(s)-1] == '\'') || (s[0] == '"' && s[len(s)-1] == '"') {
			return s[1 : len(s)-1]
		}
	}
	if n, err := strconv.ParseInt(s, 10, 64); err == nil {
		if n >= int64(int(n)) && n == int64(int(n)) {
			return int(n)
		}
		return n
	}
	return s
}

func dumpYAML(v any) string {
	var b strings.Builder
	dumpYAMLValue(&b, v, 0, true)
	return b.String()
}

func dumpYAMLValue(b *strings.Builder, v any, indent int, top bool) {
	switch t := v.(type) {
	case nil:
		if top {
			b.WriteString("{}\n")
			return
		}
		b.WriteString("null\n")
	case map[string]any:
		if len(t) == 0 {
			if !top {
				b.WriteByte(' ')
			}
			b.WriteString("{}\n")
			return
		}
		if !top {
			b.WriteByte('\n')
		}
		for _, k := range yamlKeyOrder(t) {
			writeIndent(b, indent)
			b.WriteString(k)
			b.WriteString(":")
			if list, ok := t[k].([]any); ok && len(list) > 0 {
				b.WriteByte('\n')
				for _, item := range list {
					writeIndent(b, indent)
					b.WriteString("-")
					dumpYAMLSeqItem(b, item, indent+2)
				}
				continue
			}
			dumpYAMLValue(b, t[k], indent+2, false)
		}
	case []any:
		if len(t) == 0 {
			if !top {
				b.WriteByte(' ')
			}
			b.WriteString("[]\n")
			return
		}
		if !top {
			b.WriteByte('\n')
		}
		for _, item := range t {
			writeIndent(b, indent)
			b.WriteString("-")
			dumpYAMLSeqItem(b, item, indent+2)
		}
	case bool:
		if !top {
			b.WriteByte(' ')
		}
		if t {
			b.WriteString("true\n")
		} else {
			b.WriteString("false\n")
		}
	case int:
		if !top {
			b.WriteByte(' ')
		}
		fmt.Fprintf(b, "%d\n", t)
	case int64:
		if !top {
			b.WriteByte(' ')
		}
		fmt.Fprintf(b, "%d\n", t)
	case string:
		if !top {
			b.WriteByte(' ')
		}
		b.WriteString(quoteYAMLString(t))
		b.WriteByte('\n')
	default:
		if !top {
			b.WriteByte(' ')
		}
		fmt.Fprintf(b, "%v\n", t)
	}
}

func dumpYAMLSeqItem(b *strings.Builder, item any, indent int) {
	m, ok := item.(map[string]any)
	if !ok {
		dumpYAMLValue(b, item, indent, false)
		return
	}
	keys := yamlKeyOrder(m)
	if len(keys) == 0 {
		b.WriteString(" {}\n")
		return
	}
	b.WriteByte(' ')
	b.WriteString(keys[0])
	b.WriteByte(':')
	dumpYAMLValue(b, m[keys[0]], indent+2, false)
	for _, k := range keys[1:] {
		writeIndent(b, indent)
		b.WriteString(k)
		b.WriteByte(':')
		dumpYAMLValue(b, m[k], indent+2, false)
	}
}

func writeIndent(b *strings.Builder, n int) {
	for i := 0; i < n; i++ {
		b.WriteByte(' ')
	}
}

func quoteYAMLString(s string) string {
	if s == "" {
		return `""`
	}
	need := strings.ContainsAny(s, ":#{}[]&*!|>'\"%@`") || strings.Contains(s, " ") ||
		s == "true" || s == "false" || s == "null" || s == "yes" || s == "no"
	if _, err := strconv.Atoi(s); err == nil {
		need = true
	}
	if !need {
		return s
	}
	return strconv.Quote(s)
}

func yamlKeyOrder(m map[string]any) []string {
	preferred := []string{
		"version", "filesystem_policy", "landlock", "process", "network_policies",
		"include_workdir", "read_only", "read_write",
		"run_as_user", "run_as_group",
		"name", "endpoints", "binaries",
		"host", "port", "path", "compatibility",
	}
	seen := map[string]bool{}
	var out []string
	for _, k := range preferred {
		if _, ok := m[k]; ok {
			out = append(out, k)
			seen[k] = true
		}
	}
	var rest []string
	for k := range m {
		if !seen[k] {
			rest = append(rest, k)
		}
	}
	sort.Strings(rest)
	return append(out, rest...)
}

func asMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

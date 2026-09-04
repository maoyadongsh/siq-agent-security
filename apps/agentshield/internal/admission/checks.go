package admission

import (
	"path"
	"regexp"
	"strings"
	"unicode"
)

// Built-in admission checks (dev-spec §3.6.4). Each returns raw hits; the
// caller turns hits into findings with evidence and applies the disposition.

type rawHit struct {
	ruleID     string
	category   string
	severity   string
	confidence float64
	disp       string
	path       string
	line       int    // 1-based, 0 = whole file
	excerpt    string // unredacted; caller redacts + truncates
	cap        *declaredCapability
}

var (
	htmlComment   = regexp.MustCompile(`(?s)<!--(.*?)-->`)
	instructionRe = regexp.MustCompile(`(?i)\b(ignore|override|disregard|always|never|do not tell|don'?t tell|system prompt|you must|secretly|without (?:telling|informing))\b`)
	deceptionRe   = regexp.MustCompile(`(?i)(?:do not|don'?t|never)\s+(?:tell|inform|mention|reveal|disclose|show)[^\n]{0,40}\buser\b|\bhide[^\n]{0,40}\bfrom the user\b|不要告诉用户|别告诉用户|不要让用户知道|隐瞒用户`)
	urlRe         = regexp.MustCompile(`https?://([A-Za-z0-9.-]+)(?::(\d+))?`)
	fetchVerbRe   = regexp.MustCompile(`(?i)\b(curl|wget|fetch|requests\.|httpx\.|urllib|http\.get|axios|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b`)
	pkgInstallRe  = regexp.MustCompile(`(?i)\b(pip3?|uv pip|uv tool|pipx|npm|pnpm|yarn|bun|brew|apt(?:-get)?|dnf|yum|apk|cargo|go|gem|conda)\s+(install|add)\b`)
	writeOutside  = regexp.MustCompile(`(?:>>?|\b(?:cp|mv|tee|install|touch|mkdir(?: -p)?)\s+[^\n]*?)\s*(~/|\$HOME/|/etc/|/usr/|/opt/|/var/|%APPDATA%|%USERPROFILE%|%LOCALAPPDATA%)([^\s;&|"']*)`)
	pyWriteRe     = regexp.MustCompile(`open\(\s*["'](~/|/etc/|/usr/|/opt/|/var/)([^"']*)["']\s*,\s*["'][wa]`)
	identRe       = regexp.MustCompile(`[\p{L}\p{N}_]+`)
)

var localHosts = map[string]bool{"localhost": true, "127.0.0.1": true, "0.0.0.0": true, "::1": true, "[::1]": true}

// invisibleRune flags zero-width and BiDi control characters (U+FEFF only when
// not at offset 0).
func invisibleRune(r rune, offset int) bool {
	switch {
	case r >= 0x200B && r <= 0x200F, r >= 0x2060 && r <= 0x2064, r >= 0x202A && r <= 0x202E, r >= 0x2066 && r <= 0x2069:
		return true
	case r == 0xFEFF:
		return offset != 0
	}
	return false
}

func checkHiddenComments(text string) []rawHit {
	var hits []rawHit
	for _, m := range htmlComment.FindAllStringSubmatchIndex(text, -1) {
		body := strings.TrimSpace(text[m[2]:m[3]])
		line := strings.Count(text[:m[0]], "\n") + 1
		if body == "" || strings.HasPrefix(strings.ToUpper(body), "TODO") {
			hits = append(hits, rawHit{"adm-hidden-html-comment", catInfo, "info", 0.5, dispInfo, "SKILL.md", line, body, nil})
			continue
		}
		if instructionRe.MatchString(body) {
			hits = append(hits, rawHit{"adm-hidden-html-comment", catHidden, "high", 0.9, dispQuarantine, "SKILL.md", line, body, nil})
		} else {
			hits = append(hits, rawHit{"adm-hidden-html-comment", catInfo, "low", 0.5, dispInfo, "SKILL.md", line, body, nil})
		}
	}
	return hits
}

func checkInvisible(p, text string) []rawHit {
	line := 1
	for i, r := range text {
		if r == '\n' {
			line++
			continue
		}
		if invisibleRune(r, i) {
			return []rawHit{{"adm-unicode-invisible", catHidden, "high", 0.95, dispQuarantine, p, line, "U+" + strings.ToUpper(hex4(r)), nil}}
		}
	}
	return nil
}

func hex4(r rune) string {
	const digits = "0123456789abcdef"
	var b [8]byte
	i := len(b)
	for r > 0 {
		i--
		b[i] = digits[r&0xf]
		r >>= 4
	}
	for len(b)-i < 4 {
		i--
		b[i] = '0'
	}
	return string(b[i:])
}

// checkHomoglyph flags identifiers mixing Latin with Cyrillic/Greek letters.
func checkHomoglyph(p, text string) []rawHit {
	for ln, line := range strings.Split(text, "\n") {
		for _, tok := range identRe.FindAllString(line, -1) {
			latin, other := false, false
			for _, r := range tok {
				switch {
				case r < 128 && unicode.IsLetter(r):
					latin = true
				case unicode.Is(unicode.Cyrillic, r), unicode.Is(unicode.Greek, r):
					other = true
				}
			}
			if latin && other {
				return []rawHit{{"adm-unicode-homoglyph", catDeception, "high", 0.9, dispQuarantine, p, ln + 1, tok, nil}}
			}
		}
	}
	return nil
}

// checkDeception scans the SKILL.md body; lines inside fenced code blocks or
// blockquotes are examples and only inform.
func checkDeception(body string, bodyStartLine int) []rawHit {
	var hits []rawHit
	inFence := false
	for i, line := range strings.Split(body, "\n") {
		t := strings.TrimSpace(line)
		if strings.HasPrefix(t, "```") || strings.HasPrefix(t, "~~~") {
			inFence = !inFence
			continue
		}
		m := deceptionRe.FindString(line)
		if m == "" {
			continue
		}
		ln := bodyStartLine + i
		if inFence || strings.HasPrefix(t, ">") || strings.Count(line, "\"") >= 2 || strings.Count(line, "“") >= 1 {
			hits = append(hits, rawHit{"adm-user-deception", catInfo, "low", 0.4, dispInfo, "SKILL.md", ln, m, nil})
			continue
		}
		hits = append(hits, rawHit{"adm-user-deception", catDeception, "high", 0.85, dispQuarantine, "SKILL.md", ln, m, nil})
	}
	return hits
}

// checkEgress finds outbound hosts. In SKILL.md only lines with a fetch verb
// count (documentation links are not egress); in scripts every URL counts.
func checkEgress(p, text string) (hits []rawHit, hasEgress bool) {
	zone := zoneOf(p)
	if zone == zoneDocs || zone == zoneOther {
		return nil, false
	}
	seen := map[string]bool{}
	for ln, line := range strings.Split(text, "\n") {
		if zone == zoneSkillMD && !fetchVerbRe.MatchString(line) {
			continue
		}
		for _, m := range urlRe.FindAllStringSubmatch(line, -1) {
			host := strings.ToLower(m[1])
			port := m[2]
			if port == "" {
				if strings.HasPrefix(strings.ToLower(m[0]), "https") {
					port = "443"
				} else {
					port = "80"
				}
			}
			ep := host + ":" + port
			if seen[ep] {
				continue
			}
			seen[ep] = true
			if localHosts[host] {
				hits = append(hits, rawHit{"adm-egress-domain", catInfo, "info", 0.5, dispInfo, p, ln + 1, m[0], nil})
				continue
			}
			hasEgress = true
			hits = append(hits, rawHit{"adm-egress-domain", catCapability, "medium", 0.9, dispDeclare, p, ln + 1, m[0],
				&declaredCapability{"network", "http.request", "endpoint", ep}})
		}
	}
	return hits, hasEgress
}

func checkPackageInstall(p, text string) []rawHit {
	if z := zoneOf(p); z == zoneDocs || z == zoneOther {
		return nil
	}
	var hits []rawHit
	seen := map[string]bool{}
	for ln, line := range strings.Split(text, "\n") {
		m := pkgInstallRe.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		mgr := strings.ToLower(strings.Fields(m[1])[0])
		if seen[mgr] {
			continue
		}
		seen[mgr] = true
		hits = append(hits, rawHit{"adm-package-install", catCapability, "medium", 0.85, dispDeclare, p, ln + 1, m[0],
			&declaredCapability{"resource", "package.install", "package", mgr}})
	}
	return hits
}

func checkWritesOutside(p, text string) []rawHit {
	if zoneOf(p) != zoneScripts {
		return nil
	}
	var hits []rawHit
	seen := map[string]bool{}
	for ln, line := range strings.Split(text, "\n") {
		var prefix string
		var full string
		if m := writeOutside.FindStringSubmatch(line); m != nil {
			prefix, full = m[1]+m[2], m[0]
		} else if m := pyWriteRe.FindStringSubmatch(line); m != nil {
			prefix, full = m[1]+m[2], m[0]
		} else {
			continue
		}
		target := path.Clean("/" + strings.TrimPrefix(strings.TrimPrefix(prefix, "~/"), "$HOME/"))
		if strings.HasPrefix(prefix, "~/") || strings.HasPrefix(prefix, "$HOME/") {
			target = "~" + target
		}
		if seen[target] {
			continue
		}
		seen[target] = true
		hits = append(hits, rawHit{"adm-writes-outside-skill", catCapability, "medium", 0.8, dispDeclare, p, ln + 1, full,
			&declaredCapability{"filesystem", "fs.write", "path", target}})
	}
	return hits
}

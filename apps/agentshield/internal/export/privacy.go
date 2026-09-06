// Package export — privacy profile helpers (DEV15-B / M-G5).
package export

import (
	"crypto/sha256"
	"encoding/hex"
	"path"
	"regexp"
	"strings"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/display"
)

// PrivacyProfileID identifies the share-facing field policy applied by Build.
const PrivacyProfileID = "agentshield.export.privacy.v1"

const (
	maxReasonRunes   = 240
	maxLocatorRunes  = 256
	maxResourceRunes = 256
)

var (
	// Absolute POSIX / Windows-ish home prefixes (usernames must not appear in share bundles).
	reHomePOSIX = regexp.MustCompile(`(?i)^/(?:home|Users)/([^/]+)(/.*)?$`)
	reHomeWin   = regexp.MustCompile(`(?i)^[A-Za-z]:\\Users\\([^\\]+)(\\.*)?$`)
	reUserSeg   = regexp.MustCompile(`(?i)(?:^|/)(home|Users)/[^/]+`)
	// Mid-string home segments in free text (reasons).
	reEmbeddedHome = regexp.MustCompile(`(?i)/(?:home|Users)/[^/\s"'\\]+`)
)

// NormalizeAbsPath replaces host absolute paths and usernames with a portable scope.
// Governance keeps a relative-ish form or an irreversible digest — never the raw home path.
func NormalizeAbsPath(p string) string {
	p = strings.TrimSpace(p)
	if p == "" {
		return ""
	}
	if m := reHomePOSIX.FindStringSubmatch(p); m != nil {
		rest := m[2]
		if rest == "" {
			return "~"
		}
		return "~" + path.Clean(rest)
	}
	if m := reHomeWin.FindStringSubmatch(p); m != nil {
		rest := m[2]
		if rest == "" {
			return "~"
		}
		rest = strings.ReplaceAll(rest, `\`, `/`)
		return "~" + path.Clean(rest)
	}
	if strings.HasPrefix(p, "/") || (len(p) > 2 && p[1] == ':') {
		sum := sha256.Sum256([]byte(p))
		return "pathsha256:" + hex.EncodeToString(sum[:8])
	}
	return clampRunes(p, maxResourceRunes)
}

// NormalizeLocator applies path normalization to file-like locators; scheme forms stay.
func NormalizeLocator(loc string) string {
	loc = strings.TrimSpace(loc)
	if loc == "" {
		return ""
	}
	// Already portable scheme locators (hermes://, mcp://~, skill://…) — still scrub embedded homes.
	if strings.Contains(loc, "://") {
		scrubbed := reUserSeg.ReplaceAllStringFunc(loc, func(seg string) string {
			// keep prefix slash if present
			prefix := ""
			body := seg
			if strings.HasPrefix(seg, "/") {
				prefix = "/"
				body = seg[1:]
			}
			parts := strings.SplitN(body, "/", 3)
			if len(parts) < 2 {
				return prefix + "${USER_HOME}"
			}
			rest := ""
			if len(parts) == 3 {
				rest = "/" + parts[2]
			}
			return prefix + parts[0] + "/${USER}" + rest
		})
		return clampRunes(scrubbed, maxLocatorRunes)
	}
	return clampRunes(NormalizeAbsPath(loc), maxLocatorRunes)
}

// SanitizeReason keeps governance text, length-limits, and strips C0/ESC controls (DEV15-C).
func SanitizeReason(reason string) string {
	if reason == "" {
		return ""
	}
	out := display.ForTerminal(reason)
	out = reEmbeddedHome.ReplaceAllString(out, "/${USER}")
	return clampRunes(out, maxReasonRunes)
}

// NormalizeResourceValue applies path policy to permission resource values.
func NormalizeResourceValue(v string) string {
	v = strings.TrimSpace(v)
	if v == "" {
		return ""
	}
	if strings.HasPrefix(v, "/") || reHomePOSIX.MatchString(v) || reHomeWin.MatchString(v) {
		return NormalizeAbsPath(v)
	}
	return clampRunes(v, maxResourceRunes)
}

func clampRunes(s string, max int) string {
	if max <= 0 || utf8.RuneCountInString(s) <= max {
		return s
	}
	runes := []rune(s)
	return string(runes[:max]) + "…"
}

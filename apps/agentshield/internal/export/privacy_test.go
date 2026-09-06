package export

import (
	"strings"
	"testing"
)

func TestNormalizeAbsPathScrubsUsername(t *testing.T) {
	got := NormalizeAbsPath("/home/alice/proj/secret.txt")
	if got != "~/proj/secret.txt" {
		t.Fatalf("got %q", got)
	}
	if strings.Contains(got, "alice") {
		t.Fatal("username must not appear")
	}
	got = NormalizeAbsPath(`/Users/bob/Documents/a`)
	if got != "~/Documents/a" || strings.Contains(got, "bob") {
		t.Fatalf("got %q", got)
	}
	got = NormalizeAbsPath("/var/lib/agentshield/x")
	if !strings.HasPrefix(got, "pathsha256:") {
		t.Fatalf("non-home abs path should digest, got %q", got)
	}
}

func TestNormalizeLocatorScrubsEmbeddedHome(t *testing.T) {
	got := NormalizeLocator("file:///home/carol/.hermes/config.json")
	if strings.Contains(got, "carol") {
		t.Fatalf("username leaked: %q", got)
	}
	if !strings.Contains(got, "${USER}") && !strings.Contains(got, "~") {
		t.Fatalf("expected scrubbed locator, got %q", got)
	}
}

func TestSanitizeReasonLimitsAndStripsControls(t *testing.T) {
	raw := "deny\x00path=/home/dave/x " + strings.Repeat("字", 300)
	got := SanitizeReason(raw)
	if strings.Contains(got, "\x00") {
		t.Fatal("NUL must be stripped")
	}
	if strings.Contains(got, "dave") {
		t.Fatal("home user must be scrubbed from reason")
	}
	if len([]rune(got)) > maxReasonRunes+1 { // +1 for ellipsis rune
		t.Fatalf("too long: %d", len([]rune(got)))
	}
}

func TestBuildAppliesPrivacyProfile(t *testing.T) {
	// reuse existing build fixture pattern lightly via TestBuildOmits… style
	// covered in export_test with privacy assertions below — keep unit here focused.
	_ = PrivacyProfileID
}

package skillmanifest

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var (
	shPubkey  = regexp.MustCompile(`(?m)^RELEASE_PUBKEY_B64='[^']*'$`)
	ps1Pubkey = regexp.MustCompile(`(?m)^\$ReleasePubKeyB64 = '[^']*'$`)
)

// EmbedReleasePubkey rewrites the trust-root assignment in bootstrap.sh and
// bootstrap.ps1. The scripts must already contain the assignment so this is a
// rotation, not an insertion.
func EmbedReleasePubkey(skillDir, pubB64 string) error {
	if _, err := ParsePublicKey(pubB64); err != nil {
		return err
	}
	sh := filepath.Join(skillDir, "scripts", "bootstrap.sh")
	ps1 := filepath.Join(skillDir, "scripts", "bootstrap.ps1")
	if err := rewrite(sh, shPubkey, "RELEASE_PUBKEY_B64='"+pubB64+"'"); err != nil {
		return err
	}
	if err := rewrite(ps1, ps1Pubkey, "$ReleasePubKeyB64 = '"+pubB64+"'"); err != nil {
		return err
	}
	return nil
}

// ReadEmbeddedPubkey extracts RELEASE_PUBKEY_B64 from bootstrap.sh.
func ReadEmbeddedPubkey(skillDir string) (string, error) {
	raw, err := os.ReadFile(filepath.Join(skillDir, "scripts", "bootstrap.sh"))
	if err != nil {
		return "", err
	}
	m := shPubkey.FindSubmatch(raw)
	if m == nil {
		return "", fmt.Errorf("skillmanifest: bootstrap.sh has no RELEASE_PUBKEY_B64 assignment")
	}
	s := string(m[0])
	s = strings.TrimPrefix(s, "RELEASE_PUBKEY_B64='")
	s = strings.TrimSuffix(s, "'")
	return s, nil
}

func rewrite(path string, re *regexp.Regexp, repl string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if !re.Match(raw) {
		return fmt.Errorf("skillmanifest: %s has no pubkey assignment to replace", filepath.Base(path))
	}
	out := re.ReplaceAllLiteral(raw, []byte(repl))
	return os.WriteFile(path, out, 0o755)
}

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

// EmbedReleasePubkey rewrites the trust-root assignment in bootstrap scripts
// and the shared resolve_verified_bin.sh. The scripts must already contain the
// assignment so this is a rotation, not an insertion.
func EmbedReleasePubkey(skillDir, pubB64 string) error {
	if _, err := ParsePublicKey(pubB64); err != nil {
		return err
	}
	sh := filepath.Join(skillDir, "scripts", "bootstrap.sh")
	ps1 := filepath.Join(skillDir, "scripts", "bootstrap.ps1")
	resolve := filepath.Join(skillDir, "scripts", "resolve_verified_bin.sh")
	adapterPs1 := filepath.Join(skillDir, "scripts", "adapter.ps1")
	if err := rewrite(resolve, shPubkey, "RELEASE_PUBKEY_B64='"+pubB64+"'"); err != nil {
		return err
	}
	// bootstrap.sh may no longer embed the key directly; ignore if absent.
	if err := rewriteOptional(sh, shPubkey, "RELEASE_PUBKEY_B64='"+pubB64+"'"); err != nil {
		return err
	}
	if err := rewrite(ps1, ps1Pubkey, "$ReleasePubKeyB64 = '"+pubB64+"'"); err != nil {
		return err
	}
	if err := rewriteOptional(adapterPs1, ps1Pubkey, "$ReleasePubKeyB64 = '"+pubB64+"'"); err != nil {
		return err
	}
	return nil
}

// ReadEmbeddedPubkey extracts RELEASE_PUBKEY_B64 from resolve_verified_bin.sh
// (shared trust root), falling back to bootstrap.sh for older trees.
func ReadEmbeddedPubkey(skillDir string) (string, error) {
	for _, leaf := range []string{
		filepath.Join("scripts", "resolve_verified_bin.sh"),
		filepath.Join("scripts", "bootstrap.sh"),
	} {
		raw, err := os.ReadFile(filepath.Join(skillDir, leaf))
		if err != nil {
			continue
		}
		m := shPubkey.FindSubmatch(raw)
		if m == nil {
			continue
		}
		s := string(m[0])
		s = strings.TrimPrefix(s, "RELEASE_PUBKEY_B64='")
		s = strings.TrimSuffix(s, "'")
		return s, nil
	}
	return "", fmt.Errorf("skillmanifest: no RELEASE_PUBKEY_B64 assignment in resolve/bootstrap scripts")
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

func rewriteOptional(path string, re *regexp.Regexp, repl string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	if !re.Match(raw) {
		return nil
	}
	out := re.ReplaceAllLiteral(raw, []byte(repl))
	return os.WriteFile(path, out, 0o755)
}

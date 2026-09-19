package signing

import (
	"bytes"
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestWindowsStatePathSigningFileBranches(t *testing.T) {
	t.Setenv(product.EnvSigningSeed, "")
	t.Setenv(product.EnvSigningSeedOld, "")
	for _, existing := range []bool{false, true} {
		parent := t.TempDir()
		target := filepath.Join(parent, "target")
		if err := os.Mkdir(target, 0700); err != nil {
			t.Fatal(err)
		}
		var original []byte
		seedPath := filepath.Join(target, "keys", "signing.seed")
		if existing {
			key, err := Load(target)
			if err != nil {
				t.Fatal(err)
			}
			again, err := LoadExisting(target)
			if err != nil || !bytes.Equal(key.Public(), again.Public()) {
				t.Fatal("valid existing identity changed")
			}
			original, err = os.ReadFile(seedPath)
			if err != nil {
				t.Fatal(err)
			}
		}
		for _, raw := range []string{target + ".", target + " ", parent + `\bad.\..\target`, parent + `/bad /../target`} {
			for _, load := range []func(string) (*Key, error){Load, LoadExisting} {
				key, err := load(raw)
				if key != nil || !errors.Is(err, stateformat.ErrCorrupt) {
					t.Error("signing accepted aliased root")
				}
			}
		}
		if existing {
			got, err := os.ReadFile(seedPath)
			if err != nil || !bytes.Equal(got, original) {
				t.Error("existing seed changed")
			}
		} else if entries, err := os.ReadDir(target); err != nil || len(entries) != 0 {
			t.Error("rejected input created key state")
		}
	}
	// Environment-only seed loading historically ignores the directory, even
	// empty. This patch changes only the file-backed state-path branch.
	t.Setenv(product.EnvSigningSeed, base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32)))
	for _, raw := range []string{"", "invalid. "} {
		for _, load := range []func(string) (*Key, error){Load, LoadExisting} {
			if key, err := load(raw); err != nil || key == nil {
				t.Error("environment seed semantics changed")
			}
		}
	}
}

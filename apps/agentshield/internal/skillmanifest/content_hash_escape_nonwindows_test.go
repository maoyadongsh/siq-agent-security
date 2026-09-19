//go:build !windows

package skillmanifest

import (
	"os"
	"path/filepath"
	"testing"
)

func makeHashEscape(t *testing.T, root, outside string) {
	t.Helper()
	if err := os.Symlink(filepath.Join(outside, "secret"), filepath.Join(root, "leak")); err != nil {
		t.Fatal(err)
	}
}

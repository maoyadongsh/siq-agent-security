//go:build linux

package installplan

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestPrivateStaging(t *testing.T) {
	for _, scenario := range []string{"valid", "corrupt", "wide_parent", "symlink_parent", "unknown_publisher"} {
		t.Run(scenario, func(t *testing.T) {
			must := func(err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			r, pub, key := releaseFixture(t)
			source, parent := t.TempDir(), t.TempDir()
			must(os.Chmod(parent, 0700))
			body := []byte("synthetic non-executed staging fixture")
			h := sha256.Sum256(body)
			for i := range r.Artifacts {
				a := &r.Artifacts[i]
				a.SHA256 = hex.EncodeToString(h[:])
				a.Bytes = int64(len(body))
				path := filepath.Join(source, a.Path)
				must(os.MkdirAll(filepath.Dir(path), 0700))
				must(os.WriteFile(path, body, 0700))
			}
			raw := signFixture(t, r, key)
			verified, err := verifyRelease(raw, pub)
			must(err)
			p, err := Parse(fixture(t))
			must(err)
			h = sha256.Sum256(raw)
			p.ReleaseManifestSHA256 = hex.EncodeToString(h[:])
			p.Connectors[0].ArtifactSHA256 = r.Artifacts[1].SHA256
			must(bindRelease(*p, raw, verified))
			switch scenario {
			case "corrupt":
				must(os.WriteFile(filepath.Join(source, r.Artifacts[1].Path), make([]byte, len(body)), 0700))
			case "wide_parent":
				must(os.Chmod(parent, 0755))
			case "symlink_parent":
				link := filepath.Join(t.TempDir(), "alias")
				must(os.Symlink(parent, link))
				parent = link
			case "unknown_publisher":
				path, err := StageBundle(*p, raw, source, parent)
				if err != ErrInvalid || path != "" {
					t.Fatal("untrusted publisher staged")
				}
				files, err := os.ReadDir(parent)
				must(err)
				if len(files) != 0 {
					t.Fatal("untrusted publisher wrote files")
				}
				return
			}
			path, err := stageBundle(*p, raw, verified, source, parent)
			if scenario != "valid" {
				if err != ErrInvalid || path != "" {
					t.Fatal("unsafe stage accepted")
				}
				if scenario == "corrupt" {
					stages, err := os.ReadDir(parent)
					must(err)
					if len(stages) != 1 {
						t.Fatal("partial stage not retained")
					}
					if _, err := os.Stat(filepath.Join(parent, stages[0].Name(), "READY")); !os.IsNotExist(err) {
						t.Fatal("partial stage marked ready")
					}
				}
				return
			}
			must(err)
			must(verifyBundleFiles(*p, verified, path))
			must(verifyStagedFiles(*p, raw, verified, path))
			if VerifyStagedBundle(*p, raw, path) != ErrInvalid {
				t.Fatal("recovery trusted test publisher")
			}
			for _, failure := range []string{"missing_ready", "false_ready", "manifest", "metadata_link", "artifact", "wide_directory"} {
				t.Run(failure, func(t *testing.T) {
					broken, err := stageBundle(*p, raw, verified, source, parent)
					must(err)
					readyPath := filepath.Join(broken, "READY")
					switch failure {
					case "missing_ready":
						must(os.Remove(readyPath))
					case "false_ready":
						must(os.Chmod(readyPath, 0600))
						must(os.WriteFile(readyPath, make([]byte, 65), 0600))
						must(os.Chmod(readyPath, 0400))
					case "manifest":
						f := filepath.Join(broken, "release.json")
						must(os.Chmod(f, 0600))
						must(os.WriteFile(f, make([]byte, len(raw)), 0600))
						must(os.Chmod(f, 0400))
					case "metadata_link":
						must(os.Remove(readyPath))
						must(os.Symlink(filepath.Join(path, "READY"), readyPath))
					case "artifact":
						f := filepath.Join(broken, r.Artifacts[0].Path)
						must(os.Chmod(f, 0700))
						must(os.WriteFile(f, make([]byte, len(body)), 0700))
						must(os.Chmod(f, 0500))
					case "wide_directory":
						must(os.Chmod(broken, 0755))
					}
					if verifyStagedFiles(*p, raw, verified, broken) != ErrInvalid {
						t.Fatal("invalid recovery accepted")
					}
				})
			}
			ready, err := os.ReadFile(filepath.Join(path, "READY"))
			must(err)
			if string(ready) != p.ReleaseManifestSHA256+"\n" {
				t.Fatal("bad completion digest")
			}
			manifest, err := os.ReadFile(filepath.Join(path, "release.json"))
			must(err)
			if string(manifest) != string(raw) {
				t.Fatal("manifest changed")
			}
			for _, a := range r.Artifacts {
				info, err := os.Stat(filepath.Join(path, a.Path))
				must(err)
				if info.Mode().Perm() != 0500 {
					t.Fatal("staged executable is writable")
				}
				must(os.WriteFile(filepath.Join(source, a.Path), []byte("changed source"), 0700))
			}
			must(verifyBundleFiles(*p, verified, path))
			// A failed retry creates a separate incomplete stage, never rewrites success.
			if next, err := stageBundle(*p, raw, verified, source, parent); err != ErrInvalid || next != "" {
				t.Fatal("bad retry accepted")
			}
			must(verifyBundleFiles(*p, verified, path))
		})
	}
}

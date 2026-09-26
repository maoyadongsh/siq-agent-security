//go:build linux

package installplan

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestBundlePreflight(t *testing.T) {
	for _, scenario := range []string{"valid", "modified", "short", "long", "missing", "symlink", "parent_symlink", "root_symlink", "hardlink", "directory", "fifo", "writable", "not_executable"} {
		t.Run(scenario, func(t *testing.T) {
			r, pub, key := releaseFixture(t)
			root := t.TempDir()
			body := []byte("synthetic fixture, never executed")
			hash := sha256.Sum256(body)
			for i := range r.Artifacts {
				a := &r.Artifacts[i]
				a.Bytes = int64(len(body))
				a.SHA256 = hex.EncodeToString(hash[:])
				path := filepath.Join(root, a.Path)
				if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, body, 0700); err != nil {
					t.Fatal(err)
				}
			}
			raw := signFixture(t, r, key)
			verified, err := verifyRelease(raw, pub)
			if err != nil {
				t.Fatal(err)
			}
			p, err := Parse(fixture(t))
			if err != nil {
				t.Fatal(err)
			}
			manifestHash := sha256.Sum256(raw)
			p.ReleaseManifestSHA256 = hex.EncodeToString(manifestHash[:])
			p.Connectors[0].ArtifactSHA256 = r.Artifacts[1].SHA256
			if err := bindRelease(*p, raw, verified); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, r.Artifacts[0].Path)
			must := func(err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			switch scenario {
			case "modified":
				must(os.WriteFile(path, make([]byte, len(body)), 0700))
			case "short":
				must(os.WriteFile(path, body[:1], 0700))
			case "long":
				must(os.WriteFile(path, append(body, 0), 0700))
			case "missing":
				must(os.Remove(path))
			case "symlink":
				must(os.Remove(path))
				must(os.Symlink(filepath.Join(root, r.Artifacts[1].Path), path))
			case "hardlink":
				must(os.Link(path, filepath.Join(root, "alias")))
			case "directory":
				must(os.Remove(path))
				must(os.Mkdir(path, 0700))
			case "fifo":
				must(os.Remove(path))
				must(syscall.Mkfifo(path, 0700))
			case "writable":
				must(os.Chmod(path, 0770))
			case "not_executable":
				must(os.Chmod(path, 0600))
			case "parent_symlink":
				parent := filepath.Join(root, "bin")
				moved := filepath.Join(root, "other")
				must(os.Rename(parent, moved))
				must(os.Symlink(moved, parent))
			case "root_symlink":
				alias := filepath.Join(t.TempDir(), "alias")
				must(os.Symlink(root, alias))
				root = alias
			}
			err = verifyBundleFiles(*p, verified, root)
			if scenario == "valid" && err != nil {
				t.Fatal(err)
			}
			if scenario != "valid" && err != ErrInvalid {
				t.Fatal("unsafe bundle accepted")
			}
			if VerifyBundle(*p, raw, root) != ErrInvalid {
				t.Fatal("test-signed bundle trusted by production entry")
			}
			allErr := verifyReleaseFiles(verified, root)
			if (scenario == "valid") != (allErr == nil) {
				t.Fatal("all-artifact check differs from selected check", allErr)
			}
			if _, err := VerifyReleaseBundle(raw, root); err != ErrInvalid {
				t.Fatal("all-artifact entry trusted a test publisher")
			}
		})
	}
}

func TestReleasePreflightChecksOtherArchitectureAndUnselectedConnector(t *testing.T) {
	r, pub, key := releaseFixture(t)
	r.Artifacts = append(r.Artifacts,
		Artifact{ID: "edge-agent", OS: "linux", Arch: "amd64", Path: "bin/amd64/edge-agent"},
		Artifact{ID: "directory", OS: "linux", Arch: "amd64", Path: "bin/amd64/directory-connector"},
		Artifact{ID: "directory", OS: "linux", Arch: "arm64", Path: "bin/arm64/directory-connector"})
	root := t.TempDir()
	body := []byte("inert release fixture, never execute")
	digest := sha256.Sum256(body)
	for i := range r.Artifacts {
		a := &r.Artifacts[i]
		a.Bytes = int64(len(body))
		a.SHA256 = hex.EncodeToString(digest[:])
		path := filepath.Join(root, a.Path)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, body, 0700); err != nil {
			t.Fatal(err)
		}
	}
	raw := signFixture(t, r, key)
	verified, err := verifyRelease(raw, pub)
	if err != nil {
		t.Fatal(err)
	}
	if verifyReleaseFiles(verified, root) != nil {
		t.Fatal("complete release rejected")
	}
	p, err := Parse(fixture(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, index := range []int{2, 3, 4} {
		path := filepath.Join(root, r.Artifacts[index].Path)
		if err := os.WriteFile(path, []byte("changed"), 0700); err != nil {
			t.Fatal(err)
		}
		if verifyBundleFiles(*p, verified, root) != nil {
			t.Fatal("selected architecture/connector unexpectedly affected")
		}
		if verifyReleaseFiles(verified, root) != ErrInvalid {
			t.Fatal("unselected artifact tampering missed")
		}
		if err := os.WriteFile(path, body, 0700); err != nil {
			t.Fatal(err)
		}
	}
}

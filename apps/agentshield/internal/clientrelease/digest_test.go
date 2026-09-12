package clientrelease

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDigestRejectsInvalidSources(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "binary")
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Digest(path); err == nil {
		t.Fatal("empty accepted")
	}
	if _, err := Digest(dir); err == nil {
		t.Fatal("directory accepted")
	}
	f, err := os.OpenFile(path, os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	err = f.Truncate(maxBinaryBytes + 1)
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Digest(path); err == nil {
		t.Fatal("oversize accepted")
	}
	if err := os.WriteFile(path, []byte("abc"), 0600); err != nil {
		t.Fatal(err)
	}
	digest, err := Digest(path)
	if err != nil || digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatal("digest mismatch", err)
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(path, link); err != nil {
		t.Skip("symlink unavailable")
	}
	if _, err := Digest(link); err == nil {
		t.Fatal("symlink accepted")
	}
}

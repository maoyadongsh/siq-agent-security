//go:build linux

package main

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestHostMetadataReader(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "metadata")
	if err := os.WriteFile(path, []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	value, err := readHostMetadata(path)
	if err != nil || string(value) != "fixture" {
		t.Fatal("regular metadata")
	}
	if err := os.WriteFile(path, []byte(strings.Repeat("x", (16<<10)+1)), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readHostMetadata(path); err == nil {
		t.Fatal("oversized accepted")
	}
	if _, err := readHostMetadata(dir); err == nil {
		t.Fatal("directory accepted")
	}
	fifo := filepath.Join(dir, "fifo")
	if err := syscall.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readHostMetadata(fifo); err == nil {
		t.Fatal("fifo accepted")
	}
}

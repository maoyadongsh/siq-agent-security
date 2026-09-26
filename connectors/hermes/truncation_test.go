package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func TestLimitedReadTruncationBoundaries(t *testing.T) {
	for _, size := range []int{0, 1023, 1024, 1025, 120028} {
		t.Run(strconv.Itoa(size), func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "config.yaml")
			body := bytes.Repeat([]byte("x"), size)
			if err := os.WriteFile(path, body, 0o600); err != nil {
				t.Fatal(err)
			}
			data, truncated, err := readFileLimitedWithTruncation(path, 1024)
			if err != nil {
				t.Fatal(err)
			}
			if truncated != (size > 1024) || !bytes.Equal(data, body[:min(size, 1024)]) {
				t.Fatalf("size=%d: read=%d truncated=%v", size, len(data), truncated)
			}
		})
	}
}

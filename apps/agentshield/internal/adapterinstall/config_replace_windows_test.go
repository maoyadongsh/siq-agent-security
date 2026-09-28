package adapterinstall

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWindowsConfigReplaceWaitsForTemporaryReader(t *testing.T) {
	for _, kind := range []string{"released", "held", "changed"} {
		t.Run(kind, func(t *testing.T) {
			home := t.TempDir()
			path := filepath.Join(home, "host.json")
			putTestFile(t, path, []byte("original"), 0600)
			before, err := readImage(home, path)
			if err != nil {
				t.Fatal(err)
			}
			after := before
			after.Data = []byte("reviewed replacement")
			// os.Open on Windows permits reads/writes but not delete-sharing. A
			// rename onto this path must fail until this actual handle is closed.
			reader, err := os.Open(path)
			if err != nil {
				t.Fatal(err)
			}
			defer reader.Close()
			probe := filepath.Join(home, "rename-probe")
			putTestFile(t, probe, []byte("probe"), 0600)
			if err := os.Rename(probe, path); !errors.Is(err, os.ErrPermission) {
				t.Fatal("delete-sharing denial was not injected", err)
			}
			if err := os.Remove(probe); err != nil {
				t.Fatal(err)
			}
			finished := make(chan error, 1)
			go func() { finished <- writeImage(home, path, before, after) }()
			select {
			case err := <-finished:
				t.Fatal("replacement did not wait for temporary reader", err)
			case <-time.After(30 * time.Millisecond):
			}
			if kind == "changed" {
				putTestFile(t, path, []byte("user change"), 0600)
			}
			if kind != "held" {
				if err := reader.Close(); err != nil {
					t.Fatal(err)
				}
			}
			select {
			case err = <-finished:
			case <-time.After(3 * time.Second):
				t.Fatal("configuration retry did not terminate")
			}
			want := after.Data
			switch kind {
			case "released":
				if err != nil {
					t.Fatal(err)
				}
			case "held":
				if !errors.Is(err, os.ErrPermission) {
					t.Fatal("permanent refusal was ignored", err)
				}
				want = before.Data
			case "changed":
				if !errors.Is(err, ErrPlanChanged) {
					t.Fatal("changed before image was overwritten", err)
				}
				want = []byte("user change")
			}
			raw, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(raw, want) {
				t.Fatal("unexpected final configuration", err)
			}
			entries, err := os.ReadDir(home)
			if err != nil || len(entries) != 1 || entries[0].Name() != "host.json" {
				t.Fatal("failed replacement leaked temporary files", entries, err)
			}
		})
	}
}

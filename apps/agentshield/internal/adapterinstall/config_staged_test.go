package adapterinstall

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestConfigPublicationRechecksAfterStaging(t *testing.T) {
	for _, preserve := range []bool{false, true} {
		for _, change := range []string{"unchanged", "edited", "deleted", "directory"} {
			t.Run(fmt.Sprintf("security=%t/%s", preserve, change), func(t *testing.T) {
				home := t.TempDir()
				path := filepath.Join(home, "host.json")
				putTestFile(t, path, []byte("original"), 0600)
				before, err := readImage(home, path, preserve)
				if err != nil {
					t.Fatal(err)
				}
				after := before
				after.Data = []byte("reviewed replacement")
				injected := false
				previous := transactionBoundary
				t.Cleanup(func() { transactionBoundary = previous })
				transactionBoundary = func(at string) error {
					if at != "config_staged" || injected {
						return nil
					}
					injected = true
					switch change {
					case "edited":
						putTestFile(t, path, []byte("user edit"), 0600)
					case "deleted", "directory":
						if err := os.Remove(path); err != nil {
							t.Fatal(err)
						}
						if change == "directory" {
							if err := os.Mkdir(path, 0700); err != nil {
								t.Fatal(err)
							}
						}
					}
					return nil
				}
				err = writeImage(home, path, before, after, preserve)
				if !injected {
					t.Fatal("staged boundary was not reached")
				}
				if change == "unchanged" {
					if err != nil {
						t.Fatal(err)
					}
				} else if !errors.Is(err, ErrPlanChanged) {
					t.Fatalf("staged drift not refused: %v", err)
				}
				switch change {
				case "edited", "unchanged":
					want := "user edit"
					if change == "unchanged" {
						want = string(after.Data)
					}
					raw, err := os.ReadFile(path)
					if err != nil || string(raw) != want {
						t.Fatal("unexpected final content", err)
					}
				case "deleted":
					if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
						t.Fatal("deleted configuration was recreated", err)
					}
				case "directory":
					info, err := os.Lstat(path)
					if err != nil || !info.IsDir() {
						t.Fatal("user directory replaced", err)
					}
				}
				entries, err := os.ReadDir(home)
				if err != nil {
					t.Fatal(err)
				}
				for _, entry := range entries {
					if entry.Name() != "host.json" {
						t.Fatal("staged file leaked")
					}
				}
			})
		}
	}
}

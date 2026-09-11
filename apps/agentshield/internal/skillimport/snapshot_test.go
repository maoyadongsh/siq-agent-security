package skillimport

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestInstallationSnapshotPinnedScopeAndIndependentMetadata(t *testing.T) {
	store, request := storeFixture(t)
	put(t, filepath.Join(request.Path, "references", "report.txt"), []byte("approved report"), 0600)
	if _, _, _, err := store.Create(nil, request); err != nil {
		t.Fatal(err)
	}
	snapshot, err := store.OpenInstallationSnapshot(nil, request.ImportID)
	if err != nil {
		t.Fatal(err)
	}
	metadata := snapshot.Metadata()
	metadata.ImportID = "si-other"
	metadata.Files[0].Path = "../escape"
	metadata.Directories[0] = "elsewhere"
	put(t, filepath.Join(request.Path, "references", "report.txt"), []byte("later original source"), 0600)
	raw, err := snapshot.ReadFile(nil, "references/report.txt")
	if err != nil || string(raw) != "approved report" {
		t.Fatal("snapshot followed changed original or metadata", err)
	}
	raw[0] = 'x'
	again, err := snapshot.ReadFile(nil, "references/report.txt")
	if err != nil || string(again) != "approved report" {
		t.Fatal("returned buffer changed snapshot", err)
	}
	for _, path := range []string{"../escape", "SKILL.md/../SKILL.md", "references\\report.txt", "missing.txt", "references/REPORT.txt"} {
		if _, err := snapshot.ReadFile(nil, path); !errors.Is(err, ErrInvalid) {
			t.Fatal("unlisted path", path, err)
		}
	}
	if err := snapshot.Verify(nil); err != nil {
		t.Fatal(err)
	}
	current := snapshot.Metadata()
	if current.ImportID != request.ImportID || current.Files[0].Path == "../escape" || current.Directories[0] == "elsewhere" {
		t.Fatal("metadata aliases handle")
	}
}
func TestInstallationSnapshotRejectsPostOpenChanges(t *testing.T) {
	for _, mode := range []string{"auxiliary", "link", "executable", "analysis", "signature", "canceled"} {
		t.Run(mode, func(t *testing.T) {
			store, request := storeFixture(t)
			put(t, filepath.Join(request.Path, "references", "report.txt"), []byte("approved report"), 0600)
			if _, _, _, err := store.Create(nil, request); err != nil {
				t.Fatal(err)
			}
			snapshot, err := store.OpenInstallationSnapshot(nil, request.ImportID)
			if err != nil {
				t.Fatal(err)
			}
			target := filepath.Join(store.blob(request.ImportID), "payload", "references", "report.txt")
			switch mode {
			case "auxiliary":
				put(t, target, []byte("replaced report"), 0600)
			case "link":
				other := filepath.Join(t.TempDir(), "report.txt")
				put(t, other, []byte("approved report"), 0600)
				if err := os.Remove(target); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(other, target); err != nil {
					t.Skip(err)
				}
			case "executable":
				if runtime.GOOS == "windows" {
					t.Skip("native Windows executable semantics need separate verification")
				}
				if err := os.Chmod(target, 0700); err != nil {
					t.Fatal(err)
				}
			case "analysis":
				put(t, filepath.Join(store.blob(request.ImportID), "analysis.json"), []byte("{}"), 0600)
			case "signature":
				put(t, store.record(request.ImportID), []byte("{}"), 0600)
			case "canceled":
				ctx, cancel := context.WithCancel(context.Background())
				cancel()
				if _, err := snapshot.ReadFile(ctx, "references/report.txt"); !errors.Is(err, context.Canceled) {
					t.Fatal(err)
				}
				if err := snapshot.Verify(ctx); !errors.Is(err, context.Canceled) {
					t.Fatal(err)
				}
				return
			}
			raw, readErr := snapshot.ReadFile(nil, "references/report.txt")
			if mode == "analysis" || mode == "signature" {
				// A matching file is not a claim that unrelated analysis/metadata is valid.
				if readErr != nil || !bytes.Equal(raw, []byte("approved report")) {
					t.Fatal("unexpected single-file failure", readErr)
				}
			} else if readErr == nil {
				t.Fatal("changed file accepted")
			}
			if err := snapshot.Verify(nil); err == nil {
				t.Fatal("changed candidate passed final verification")
			}
		})
	}
}
func TestInstallationSnapshotOpenRejectsAlreadyDamagedCandidate(t *testing.T) {
	store, request := storeFixture(t)
	if _, _, _, err := store.Create(nil, request); err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(store.blob(request.ImportID), "payload", "SKILL.md"), []byte("changed"), 0600)
	if _, err := store.OpenInstallationSnapshot(nil, request.ImportID); err == nil {
		t.Fatal("opened damaged candidate")
	}
}

package state

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestWindowsMigrationPublicationCrashHelper(t *testing.T) {
	root := os.Getenv("SIQ_TEST_MIGRATION_PUBLICATION_ROOT")
	if root == "" {
		t.Skip("isolated subprocess only")
	}
	point := os.Getenv("SIQ_TEST_MIGRATION_PUBLICATION_POINT")
	mode, err := strconv.ParseUint(os.Getenv("SIQ_TEST_MIGRATION_PUBLICATION_MODE"), 8, 32)
	if err != nil {
		t.Fatal(err)
	}
	migrationPublicationTestHook = func(at string) {
		if at == point {
			fmt.Fprintln(os.Stdout, "publication-paused")
			for {
				time.Sleep(time.Hour)
			}
		}
	}
	if err := migrationPublish(root, filepath.Join(root, "checkpoint"), []byte("immutable public checkpoint\n"), os.FileMode(mode)); err != nil {
		t.Fatal(err)
	}
	t.Fatal("publication did not reach fault point")
}

func TestWindowsMigrationPublicationRefusesUnsafeSourceOrTarget(t *testing.T) {
	for _, kind := range []string{"source-replaced", "target-exists", "hardlink", "broad-acl", "open-source"} {
		t.Run(kind, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "state")
			scratch := filepath.Join(root, stateformat.MigrationDir, "tmp")
			if err := privatefs.MkdirAll(scratch); err != nil {
				t.Fatal(err)
			}
			f, err := privatefs.CreateTemp(scratch, ".migration-*")
			if err != nil {
				t.Fatal(err)
			}
			if _, err := f.WriteString("owned publication"); err != nil {
				t.Fatal(err)
			}
			created, err := f.Stat()
			if err != nil {
				t.Fatal(err)
			}
			source := f.Name()
			if err := f.Close(); err != nil {
				t.Fatal(err)
			}
			target := filepath.Join(root, "checkpoint")
			switch kind {
			case "source-replaced":
				if err := os.Rename(source, source+".original"); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(source, []byte("foreign replacement"), 0600); err != nil {
					t.Fatal(err)
				}
			case "target-exists":
				if err := os.WriteFile(target, []byte("foreign target"), 0400); err != nil {
					t.Fatal(err)
				}
			case "hardlink":
				if err := os.Link(source, filepath.Join(root, "alias")); err != nil {
					t.Fatal(err)
				}
			case "broad-acl":
				acltest.BroadenRead(t, root, source)
			case "open-source":
				held, err := os.Open(source)
				if err != nil {
					t.Fatal(err)
				}
				defer held.Close()
			}
			before, err := os.ReadFile(source)
			if err != nil {
				t.Fatal(err)
			}
			if moved, err := migrationPublishScratch(source, target, created); err == nil || moved {
				t.Fatal("unsafe publication accepted")
			}
			after, err := os.ReadFile(source)
			if err != nil || string(after) != string(before) {
				t.Fatal("rejected source changed")
			}
			if kind == "target-exists" {
				got, err := os.ReadFile(target)
				if err != nil || string(got) != "foreign target" {
					t.Fatal("foreign target changed")
				}
				info, err := os.Stat(target)
				if err != nil || info.Mode()&0200 != 0 {
					t.Fatal("foreign readonly target changed")
				}
				_ = os.Chmod(target, 0600)
			} else if _, err := os.Lstat(target); !os.IsNotExist(err) {
				t.Fatal("failed publication exposed target")
			}
			if kind == "broad-acl" && privatefs.CheckFilePath(source) == nil {
				t.Fatal("unsafe source ACL repaired")
			}
		})
	}
}

func TestWindowsMigrationPublicationCrashRecovery(t *testing.T) {
	for _, mode := range []os.FileMode{0600, 0400} {
		for _, point := range []string{"before-publish", "published"} {
			t.Run(fmt.Sprintf("%o/%s", mode, point), func(t *testing.T) {
				root := filepath.Join(t.TempDir(), "state")
				if err := privatefs.MkdirAll(filepath.Join(root, stateformat.MigrationDir)); err != nil {
					t.Fatal(err)
				}
				ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestWindowsMigrationPublicationCrashHelper$", "-test.timeout=90s")
				cmd.Env = append(os.Environ(), "SIQ_TEST_MIGRATION_PUBLICATION_ROOT="+root, "SIQ_TEST_MIGRATION_PUBLICATION_POINT="+point, fmt.Sprintf("SIQ_TEST_MIGRATION_PUBLICATION_MODE=%o", mode))
				stdout, err := cmd.StdoutPipe()
				if err != nil {
					t.Fatal(err)
				}
				if err := cmd.Start(); err != nil {
					t.Fatal(err)
				}
				defer func() {
					if cmd.ProcessState == nil {
						_ = cmd.Process.Kill()
						_ = cmd.Wait()
					}
				}()
				scan := bufio.NewScanner(stdout)
				ready := false
				for scan.Scan() {
					if scan.Text() == "publication-paused" {
						ready = true
						break
					}
				}
				if !ready {
					t.Fatal("owned helper did not reach publication boundary")
				}
				if err := cmd.Process.Kill(); err != nil {
					t.Fatal(err)
				}
				if err := cmd.Wait(); err == nil {
					t.Fatal("helper did not exit abnormally")
				}
				path := filepath.Join(root, "checkpoint")
				raw := []byte("immutable public checkpoint\n")
				if point == "published" {
					got, err := os.ReadFile(path)
					if err != nil || string(got) != string(raw) {
						t.Fatal("published object incomplete")
					}
				} else if _, err := os.Lstat(path); !os.IsNotExist(err) {
					t.Fatal("unpublished target exposed")
				}
				if err := migrationPublish(root, path, raw, mode); err != nil {
					t.Fatal("crashed publication cannot resume", err)
				}
				if err := privatefs.CheckFilePath(path); err != nil {
					t.Fatal("resumed output is not private single-link", err)
				}
				info := migrationTestFileIdentity(t, path)
				if info.Mode()&0200 != mode&0200 {
					t.Fatal("readonly attribute changed")
				}
				entries, err := os.ReadDir(filepath.Join(root, stateformat.MigrationDir, "tmp"))
				want := 0
				if point == "before-publish" {
					want = 1
				}
				if err != nil || len(entries) != want {
					t.Fatal("unknown scratch removed or published alias retained")
				}
				_ = os.Chmod(path, 0600) // only this test's readonly fixture, after all assertions
			})
		}
	}
}

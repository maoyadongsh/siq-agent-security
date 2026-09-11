package skillimport

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const skillText = "---\nname: import-fixture\ndescription: Read a synthetic report.\n---\nRead a synthetic report.\n"

func storeFixture(t *testing.T) (*Store, CreateRequest) {
	t.Helper()
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	store, err := Open(t.TempDir(), key, pack, "fixture")
	if err != nil {
		t.Fatal(err)
	}
	source := t.TempDir()
	put(t, filepath.Join(source, "SKILL.md"), []byte(skillText), 0600)
	return store, CreateRequest{"local-skill-import-create/v1", "si-" + strings.Repeat("a", 32), "local_dir", source, "fixture-human"}
}
func put(t *testing.T, path string, raw []byte, mode os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, mode); err != nil {
		t.Fatal(err)
	}
}
func TestImportDirectoryFixedSnapshotAndIdempotency(t *testing.T) {
	s, req := storeFixture(t)
	marker := filepath.Join(t.TempDir(), "executed")
	put(t, filepath.Join(req.Path, "scripts", "run.sh"), []byte("#!/bin/sh\ntouch "+marker+"\n"), 0700)
	put(t, filepath.Join(req.Path, ".git", "hooks", "post-checkout"), []byte("#!/bin/sh\ntouch "+marker+"\n"), 0700)
	put(t, filepath.Join(req.Path, "skill-manifest.json"), []byte(`{"fixture":"before"}`), 0600)
	rec, analysis, reused, err := s.Create(context.Background(), req)
	if err != nil || reused {
		t.Fatal(rec, reused, err)
	}
	if !rec.ExcludedGitMetadata || len(rec.Files) != 3 || !admission.Verify(s.key.Public(), analysis.Admission) || !signing.VerifyCanonical(s.key.Public(), unsigned(*rec), rec.Signature) {
		t.Fatal("unsigned or incomplete import")
	}
	if _, err = os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("executed imported script")
	}
	if _, err = os.Stat(filepath.Join(s.blob(req.ImportID), "payload", ".git")); !os.IsNotExist(err) {
		t.Fatal("copied git metadata")
	}
	raw, _ := json.Marshal(rec)
	if bytes.Contains(raw, []byte(req.Path)) {
		t.Fatal("record leaked source path")
	}
	if rec.ArtifactDigest == sum(nil) || rec.ArtifactDigest == analysis.Admission.ContentHash {
		t.Fatal("missing distinct full artifact identity")
	}
	originalHash := rec.ArtifactDigest
	put(t, filepath.Join(req.Path, "SKILL.md"), []byte(skillText+"Changed original source.\n"), 0600)
	rec, _, reused, err = s.Create(context.Background(), req)
	if err != nil || !reused || rec.ArtifactDigest != originalHash {
		t.Fatal("retry reimported changed source", err)
	}
	rec, _, err = s.Load(context.Background(), req.ImportID)
	if err != nil || rec.ArtifactDigest != originalHash {
		t.Fatal("source changed fixed copy", err)
	}
	other := req
	other.ActorID = "other-human"
	if _, _, _, err = s.Create(context.Background(), other); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	other = req
	other.Path = t.TempDir()
	if _, _, _, err = s.Create(context.Background(), other); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
}
func TestImportTamperAndAnalysisBinding(t *testing.T) {
	for _, kind := range []string{"payload", "signature_auxiliary", "executable", "empty_directory", "analysis", "record", "duplicate_key", "case_alias", "link"} {
		t.Run(kind, func(t *testing.T) {
			s, req := storeFixture(t)
			put(t, filepath.Join(req.Path, "skill-manifest.json"), []byte(`{"fixture":"before"}`), 0600)
			rec, analysis, _, err := s.Create(context.Background(), req)
			if err != nil {
				t.Fatal(err)
			}
			payload := filepath.Join(s.blob(req.ImportID), "payload")
			switch kind {
			case "payload":
				put(t, filepath.Join(payload, "SKILL.md"), []byte(skillText+"changed"), 0600)
			case "signature_auxiliary":
				put(t, filepath.Join(payload, "skill-manifest.json"), []byte(`{"fixture":"after"}`), 0600)
				legacy, _, e := admission.HashDir(payload, admission.DefaultLimits)
				if e != nil || legacy != analysis.Admission.ContentHash {
					t.Fatal("test must preserve legacy admission hash")
				}
			case "executable":
				if err = os.Chmod(filepath.Join(payload, "SKILL.md"), 0700); err != nil {
					t.Fatal(err)
				}
			case "empty_directory":
				if err = os.Mkdir(filepath.Join(payload, "injected"), 0700); err != nil {
					t.Fatal(err)
				}
			case "analysis":
				put(t, filepath.Join(s.blob(req.ImportID), "analysis.json"), []byte(`{}`), 0600)
			case "record":
				rec.ActorID = "changed"
				raw, _ := json.Marshal(rec)
				put(t, s.record(req.ImportID), raw, 0600)
			case "duplicate_key", "case_alias":
				raw, _ := os.ReadFile(s.record(req.ImportID))
				if kind == "duplicate_key" {
					raw = append([]byte(`{"actor_id":"other",`), raw[1:]...)
				} else {
					raw = bytes.Replace(raw, []byte(`"actor_id"`), []byte(`"Actor_ID"`), 1)
				}
				put(t, s.record(req.ImportID), raw, 0600)
			case "link":
				if err = os.Remove(filepath.Join(payload, "SKILL.md")); err != nil {
					t.Fatal(err)
				}
				if err = os.Symlink(filepath.Join(req.Path, "SKILL.md"), filepath.Join(payload, "SKILL.md")); err != nil {
					t.Skip("symlink unavailable")
				}
			}
			if _, _, err = s.Load(context.Background(), req.ImportID); err == nil {
				t.Fatal("accepted changed candidate", kind)
			}
		})
	}
}
func TestImportConcurrentPublicationAndFailureCleanup(t *testing.T) {
	s, req := storeFixture(t)
	var wg sync.WaitGroup
	var created atomic.Int32
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _, reused, err := s.Create(context.Background(), req)
			if err != nil {
				t.Error(err)
			} else if !reused {
				created.Add(1)
			}
		}()
	}
	wg.Wait()
	if created.Load() != 1 {
		t.Fatal("duplicate publication", created.Load())
	}
	for _, kind := range []string{"canceled", "mid-copy-canceled", "missing_skill", "records_unavailable", "orphan", "capacity", "invalid_id", "invalid_source", "invalid_actor"} {
		t.Run(kind, func(t *testing.T) {
			s, req := storeFixture(t)
			ctx := context.Background()
			switch kind {
			case "canceled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			case "mid-copy-canceled":
				ctx = &countdownContext{Context: ctx, left: 6}
			case "missing_skill":
				os.Remove(filepath.Join(req.Path, "SKILL.md"))
			case "records_unavailable":
				if err := os.Remove(filepath.Join(s.dir, "records")); err != nil {
					t.Fatal(err)
				}
				put(t, filepath.Join(s.dir, "records"), []byte("not a directory"), 0600)
			case "orphan":
				put(t, filepath.Join(s.blob(req.ImportID), "retain"), []byte("retain"), 0600)
			case "capacity":
				for i := 0; i < maxImports; i++ {
					if err := os.Mkdir(filepath.Join(s.dir, "blobs", fmt.Sprint(i)), 0700); err != nil {
						t.Fatal(err)
					}
				}
			case "invalid_id":
				req.ImportID = "../outside"
			case "invalid_source":
				req.SourceKind = "https"
			case "invalid_actor":
				req.ActorID = " \n "
			}
			if _, _, _, err := s.Create(ctx, req); err == nil {
				t.Fatal("invalid import succeeded", kind)
			}
			if _, _, err := s.Load(context.Background(), req.ImportID); err == nil {
				t.Fatal("failed candidate visible")
			}
			if kind == "orphan" {
				raw, _ := os.ReadFile(filepath.Join(s.blob(req.ImportID), "retain"))
				if string(raw) != "retain" {
					t.Fatal("deleted orphan without ownership")
				}
			}
			if kind == "canceled" || kind == "mid-copy-canceled" || kind == "missing_skill" {
				if _, err := os.Stat(s.blob(req.ImportID)); !os.IsNotExist(err) {
					t.Fatal("failed candidate not cleaned", err)
				}
			}
		})
	}
}

type countdownContext struct {
	context.Context
	left int
}

func (c *countdownContext) Err() error {
	c.left--
	if c.left <= 0 {
		return context.Canceled
	}
	return nil
}
func TestImportPathAndSizeBoundaries(t *testing.T) {
	for _, path := range []string{"../outside", "/outside", "C:/outside", "a\\b", "NUL.txt", "COM1", "LPT¹.txt", "dir/file ", "file.", "a:b", "a//b", "a\nline", "a\u202eb", strings.Repeat("a/", 16) + "file", strings.Repeat("a", 129)} {
		if validPath(path) {
			t.Fatal("unsafe path accepted", path)
		}
	}
	for _, path := range []string{"SKILL.md", "references/中文说明.md", "folder name/file.txt", strings.Repeat("a/", 15) + "file"} {
		if !validPath(path) {
			t.Fatal("valid path rejected", path)
		}
	}
	source := t.TempDir()
	file := filepath.Join(source, "bounded")
	raw := bytes.Repeat([]byte("x"), int(maxFileBytes))
	put(t, file, raw, 0600)
	if _, _, err := directoryTree(context.Background(), source, "", false); err != nil {
		t.Fatal("exact file limit rejected", err)
	}
	put(t, file, append(raw, 'x'), 0600)
	if _, _, err := directoryTree(context.Background(), source, "", false); !errors.Is(err, ErrLimit) {
		t.Fatal("file limit missed", err)
	}
	put(t, file, raw, 0600)
	for i := 0; i < 7; i++ {
		put(t, filepath.Join(source, fmt.Sprint(i)), raw, 0600)
	}
	if _, _, err := directoryTree(context.Background(), source, "", false); err != nil {
		t.Fatal("exact aggregate limit rejected", err)
	}
	put(t, filepath.Join(source, "overflow"), []byte("x"), 0600)
	if _, _, err := directoryTree(context.Background(), source, "", false); !errors.Is(err, ErrLimit) {
		t.Fatal("aggregate limit missed", err)
	}
}

type zipMember struct {
	name string
	data []byte
	mode os.FileMode
}

func zipBytes(t *testing.T, members []zipMember) []byte {
	t.Helper()
	var out bytes.Buffer
	writer := zip.NewWriter(&out)
	for _, member := range members {
		header := &zip.FileHeader{Name: member.name, Method: zip.Store}
		header.SetMode(member.mode)
		w, err := writer.CreateHeader(header)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = w.Write(member.data); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return out.Bytes()
}
func TestImportZipMatchesDirectoryAndRefusesUnsafeArchives(t *testing.T) {
	s, req := storeFixture(t)
	put(t, filepath.Join(req.Path, "docs", "readme.md"), []byte("fixture"), 0600)
	local, _, _, err := s.Create(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(t.TempDir(), "fixture.zip")
	raw := zipBytes(t, []zipMember{{"SKILL.md", []byte(skillText), 0600}, {"docs/readme.md", []byte("fixture"), 0600}, {"docs/", nil, os.ModeDir | 0700}, {".git/config", []byte("ignored"), 0600}})
	put(t, source, raw, 0600)
	req.ImportID = "si-" + strings.Repeat("b", 32)
	req.SourceKind = "local_zip"
	req.Path = source
	rec, _, _, err := s.Create(context.Background(), req)
	if err != nil || rec.ArtifactDigest != local.ArtifactDigest || !rec.ExcludedGitMetadata {
		t.Fatal("ZIP identity mismatch", rec, err)
	}
	for _, kind := range []string{"traversal", "absolute", "case", "duplicate", "parent_file", "symlink", "crc", "encrypted", "zip64", "central_count", "oversize", "nested_only", "invalid_git_path"} {
		t.Run(kind, func(t *testing.T) {
			s, req := storeFixture(t)
			members := []zipMember{{"SKILL.md", []byte(skillText), 0600}}
			switch kind {
			case "traversal":
				members = append(members, zipMember{"../escaped", []byte("no"), 0600})
			case "absolute":
				members = append(members, zipMember{"/escaped", []byte("no"), 0600})
			case "case":
				members = append(members, zipMember{"skill.md", []byte("no"), 0600})
			case "duplicate":
				members = append(members, members[0])
			case "parent_file":
				members = append(members, zipMember{"docs", []byte("file"), 0600}, zipMember{"docs/file", []byte("no"), 0600})
			case "symlink":
				members = append(members, zipMember{"linked", []byte("/outside"), os.ModeSymlink | 0700})
			case "nested_only":
				members[0].name = "nested/SKILL.md"
			case "invalid_git_path":
				members = append(members, zipMember{".git/../../escape", []byte("no"), 0600})
			}
			data := zipBytes(t, members)
			central := bytes.Index(data, []byte{0x50, 0x4b, 0x01, 0x02})
			end := bytes.LastIndex(data, []byte{0x50, 0x4b, 0x05, 0x06})
			switch kind {
			case "crc":
				at := bytes.Index(data, []byte(skillText))
				data[at] = 'x'
			case "encrypted":
				data[central+8] |= 1
			case "zip64":
				binary.LittleEndian.PutUint16(data[end+10:end+12], 65535)
			case "central_count":
				binary.LittleEndian.PutUint16(data[end+8:end+10], 0)
				binary.LittleEndian.PutUint16(data[end+10:end+12], 0)
			case "oversize":
				binary.LittleEndian.PutUint32(data[central+24:central+28], uint32(maxFileBytes+1))
			}
			source := filepath.Join(t.TempDir(), "fixture.zip")
			put(t, source, data, 0600)
			req.SourceKind = "local_zip"
			req.Path = source
			if _, _, _, err = s.Create(context.Background(), req); err == nil {
				t.Fatal("unsafe ZIP accepted", kind)
			}
			if _, _, err = s.Load(context.Background(), req.ImportID); err == nil {
				t.Fatal("unsafe ZIP published")
			}
		})
	}
}
func TestImportContractSamples(t *testing.T) {
	s, req := storeFixture(t)
	rec, analysis, _, err := s.Create(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	req.Path = "/fixture/skill"
	rec.CreatedAt = "2026-09-10T01:00:00Z"
	rec.SourceLocatorDigest = sum([]byte(req.Path))
	analysis.Admission.DecidedAt = rec.CreatedAt
	rawAdmission, err := json.Marshal(analysis.Admission)
	if err != nil {
		t.Fatal(err)
	}
	value, err := canon.Decode(rawAdmission)
	if err != nil {
		t.Fatal(err)
	}
	doc := value.(map[string]any)
	delete(doc, "signature")
	analysis.Admission.Signature, err = s.key.SignCanonical(doc)
	if err != nil || !admission.Verify(s.key.Public(), analysis.Admission) {
		t.Fatal("fixture admission", err)
	}
	// The analysis body is not part of this DTO fixture; normalize its clock-bound digest.
	rec.AnalysisSHA256 = strings.Repeat("2", 64)
	rec.Signature, err = s.key.SignCanonical(unsigned(*rec))
	if err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"local-skill-import-create.v1": req, "local-skill-import.v1": rec, "local-skill-import-result.v1": NewResult(rec, analysis, false)} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/" + name + ".sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err = os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(expected, raw) {
			t.Fatal("contract differs", name, err)
		}
	}
}

func TestImportWaitingWriterRespondsToCancellation(t *testing.T) {
	s, req := storeFixture(t)
	writeSlot <- struct{}{}
	defer func() { <-writeSlot }()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { _, _, _, err := s.Create(ctx, req); done <- err }()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("canceled import stuck behind writer")
	}
}
func TestImportPublicationFailureRemovesOnlyOwnedCandidate(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX permission rejection fixture")
	}
	s, req := storeFixture(t)
	// Existing directory with unsafe permissions passes the early existence probe;
	// final publication must fail after payload and analysis were prepared.
	if err := os.Chmod(filepath.Join(s.dir, "records"), 0755); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := s.Create(context.Background(), req); err == nil {
		t.Fatal("published into unsafe audit directory")
	}
	if _, err := os.Lstat(s.blob(req.ImportID)); !os.IsNotExist(err) {
		t.Fatal("failed candidate retained", err)
	}
	raw, err := os.ReadFile(filepath.Join(req.Path, "SKILL.md"))
	if err != nil || string(raw) != skillText {
		t.Fatal("source changed", err)
	}
}
func TestImportLocalSymlinksAndWrongSigningKey(t *testing.T) {
	for _, directory := range []bool{false, true} {
		t.Run(fmt.Sprint(directory), func(t *testing.T) {
			s, req := storeFixture(t)
			target := t.TempDir()
			if !directory {
				target = filepath.Join(target, "outside")
				put(t, target, []byte("outside secret"), 0600)
			}
			if err := os.Symlink(target, filepath.Join(req.Path, "linked")); err != nil {
				t.Fatal(err)
			}
			if _, _, _, err := s.Create(context.Background(), req); err == nil {
				t.Fatal("source link imported")
			}
			if _, _, err := s.Load(context.Background(), req.ImportID); !errors.Is(err, ErrNotFound) {
				t.Fatal(err)
			}
		})
	}
	s, req := storeFixture(t)
	if _, _, _, err := s.Create(context.Background(), req); err != nil {
		t.Fatal(err)
	}
	other, err := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
	if err != nil {
		t.Fatal(err)
	}
	s.key = other
	if _, _, err := s.Load(context.Background(), req.ImportID); !errors.Is(err, ErrChanged) {
		t.Fatal("accepted other signer", err)
	}
}

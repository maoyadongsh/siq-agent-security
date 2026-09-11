package skillimport

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func remoteRequest() RemoteCreateRequest {
	return RemoteCreateRequest{SchemaVersion: "local-skill-import-remote-create/v1", ImportID: "si-" + strings.Repeat("b", 32), URL: "https://download.example.com/repo.zip?token=private-query", ArchivePath: "repo/skills/report", ActorID: "fixture-human"}
}
func remoteArchive(t *testing.T) []byte {
	return zipBytes(t, []zipMember{{"repo/skills/report/SKILL.md", []byte(skillText), 0600}, {"repo/skills/report/run.sh", []byte("#!/bin/sh\nexit 9\n"), 0700}, {"repo/.git/config", []byte("ignored"), 0600}, {"repo/other.txt", []byte("not selected"), 0600}})
}
func TestRemoteImportTLSSelectedSnapshotRetryAndPrivacy(t *testing.T) {
	s, local := storeFixture(t)
	if _, _, _, err := s.Create(nil, local); err != nil {
		t.Fatal(err)
	}
	req := remoteRequest()
	raw := remoteArchive(t)
	req.ExpectedSHA256 = sum(raw)
	f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write(raw) })
	s.download = f.fetch
	rec, analysis, reused, err := s.CreateRemote(nil, req)
	if err != nil || reused {
		t.Fatal(rec, err)
	}
	if rec.SchemaVersion != "local-skill-import/v2" || rec.SourceKind != "https_zip" || len(rec.Files) != 2 || !rec.ExcludedGitMetadata || rec.Remote.ArchiveSHA256 != sum(raw) || rec.Remote.ArchiveBytes != int64(len(raw)) || rec.Remote.ArchivePath != req.ArchivePath || !signing.VerifyCanonical(s.key.Public(), unsigned(*rec), rec.Signature) || !admission.Verify(s.key.Public(), analysis.Admission) {
		t.Fatal("incomplete signed download")
	}
	if rec.Remote.FinalLocatorDigest != sum([]byte(req.URL)) {
		t.Fatal("final URL not bound")
	}
	entries, err := os.ReadDir(s.blob(req.ImportID))
	if err != nil || len(entries) != 2 {
		t.Fatal("unselected archive retained", entries, err)
	}
	for _, file := range []string{s.record(req.ImportID), filepath.Join(s.blob(req.ImportID), "analysis.json")} {
		data, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		for _, secret := range []string{req.URL, "private-query", "download.example.com"} {
			if bytes.Contains(data, []byte(secret)) {
				t.Fatal("source URL persisted")
			}
		}
	}
	s.download = func(context.Context, string) (downloadedArchive, error) {
		t.Error("retry accessed network")
		return downloadedArchive{}, ErrDownloadFailed
	}
	again, _, reused, err := s.CreateRemote(nil, req)
	if err != nil || !reused || again.Signature != rec.Signature {
		t.Fatal("retry changed fixed snapshot", err)
	}
	for _, field := range []string{"url", "path", "pin", "actor"} {
		changed := req
		switch field {
		case "url":
			changed.URL += "&version=2"
		case "path":
			changed.ArchivePath = "repo/other"
		case "pin":
			changed.ExpectedSHA256 = ""
		case "actor":
			changed.ActorID = "other"
		}
		if _, _, _, err := s.CreateRemote(nil, changed); !errors.Is(err, ErrConflict) {
			t.Fatal(field, err)
		}
	}
	collision := req
	collision.ImportID = local.ImportID
	if _, _, _, err := s.CreateRemote(nil, collision); !errors.Is(err, ErrConflict) {
		t.Fatal("local collision", err)
	}
	list, err := s.List(nil)
	if err != nil || list.SchemaVersion != "local-skill-import-list/v2" || len(list.Items) != 2 {
		t.Fatal(list, err)
	}
	old, _, err := s.Load(nil, local.ImportID)
	if err != nil || old.SchemaVersion != "local-skill-import/v1" || old.Remote != nil {
		t.Fatal("legacy read changed", err)
	}
	put(t, filepath.Join(s.blob(req.ImportID), "payload", "SKILL.md"), []byte("changed"), 0600)
	if _, _, _, err := s.CreateRemote(nil, req); !errors.Is(err, ErrChanged) {
		t.Fatal("retry accepted changed snapshot", err)
	}
}

func TestRemoteImportFailureCleanup(t *testing.T) {
	for _, mode := range []string{"pin", "download", "cancel", "unsafe_outside_selection", "missing_selection", "missing_skill", "invalid_path", "invalid_pin", "root"} {
		t.Run(mode, func(t *testing.T) {
			s, _ := storeFixture(t)
			req := remoteRequest()
			raw := remoteArchive(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "pin" {
				req.ExpectedSHA256 = strings.Repeat("0", 64)
			}
			if mode == "unsafe_outside_selection" {
				raw = zipBytes(t, []zipMember{{"repo/skills/report/SKILL.md", []byte(skillText), 0600}, {"unselected/../../escape", []byte("bad"), 0600}})
			}
			if mode == "missing_selection" {
				req.ArchivePath = "not-there"
			}
			if mode == "missing_skill" {
				req.ArchivePath = "repo"
			}
			if mode == "invalid_path" {
				req.ArchivePath = "../repo"
			}
			if mode == "invalid_pin" {
				req.ExpectedSHA256 = "bad"
			}
			if mode == "root" {
				req.ArchivePath = ""
				raw = zipBytes(t, []zipMember{{"SKILL.md", []byte(skillText), 0600}})
			}
			s.download = func(context.Context, string) (downloadedArchive, error) {
				if mode == "invalid_path" || mode == "invalid_pin" {
					t.Error("invalid request downloaded")
				}
				if mode == "download" {
					return downloadedArchive{}, ErrDownloadFailed
				}
				if mode == "cancel" {
					cancel()
					return downloadedArchive{}, context.Canceled
				}
				return downloadedArchive{raw, req.URL}, nil
			}
			rec, _, _, err := s.CreateRemote(ctx, req)
			if mode == "root" {
				if err != nil || len(rec.Files) != 1 {
					t.Fatal(rec, err)
				}
				return
			}
			if err == nil {
				t.Fatal("failed input published")
			}
			if mode == "pin" && !errors.Is(err, ErrArchiveMismatch) {
				t.Fatal(err)
			}
			if _, err := os.Stat(s.record(req.ImportID)); !os.IsNotExist(err) {
				t.Fatal("failure record exists", err)
			}
			if _, err := os.Stat(s.blob(req.ImportID)); !os.IsNotExist(err) {
				t.Fatal("failed blob retained", err)
			}
		})
	}
}
func TestRemoteImportMetadataCannotDowngrade(t *testing.T) {
	for _, mode := range []string{"remote_null", "version", "kind", "digest", "pin", "bytes", "path"} {
		t.Run(mode, func(t *testing.T) {
			s, _ := storeFixture(t)
			req := remoteRequest()
			raw := remoteArchive(t)
			s.download = func(context.Context, string) (downloadedArchive, error) { return downloadedArchive{raw, req.URL}, nil }
			rec, _, _, err := s.CreateRemote(nil, req)
			if err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "remote_null":
				rec.Remote = nil
			case "version":
				rec.SchemaVersion = "local-skill-import/v1"
			case "kind":
				rec.SourceKind = "local_zip"
			case "digest":
				rec.Remote.ArchiveSHA256 = "bad"
			case "pin":
				rec.Remote.ExpectedSHA256 = strings.Repeat("0", 64)
			case "bytes":
				rec.Remote.ArchiveBytes = maxArchiveBytes + 1
			case "path":
				rec.Remote.ArchivePath = "../escape"
			}
			// Even a valid signature must not make an invalid version/metadata shape usable.
			rec.Signature, err = s.key.SignCanonical(unsigned(*rec))
			if err != nil {
				t.Fatal(err)
			}
			data, _ := json.Marshal(rec)
			put(t, s.record(req.ImportID), data, 0600)
			if _, _, err := s.Load(nil, req.ImportID); !errors.Is(err, ErrChanged) {
				t.Fatal("invalid signed metadata accepted", err)
			}
		})
	}
}

func TestRemoteImportContractSamples(t *testing.T) {
	s, local := storeFixture(t)
	if _, _, _, err := s.Create(nil, local); err != nil {
		t.Fatal(err)
	}
	req := remoteRequest()
	req.URL = "https://download.example.com/repo.zip"
	archive := remoteArchive(t)
	req.ExpectedSHA256 = sum(archive)
	s.download = func(context.Context, string) (downloadedArchive, error) {
		return downloadedArchive{archive, req.URL}, nil
	}
	rec, analysis, _, err := s.CreateRemote(nil, req)
	if err != nil {
		t.Fatal(err)
	}
	list, err := s.List(nil)
	if err != nil {
		t.Fatal(err)
	}
	// Stable DTO fixtures normalize clocks and the separately stored analysis digest.
	rec.CreatedAt = "2026-09-11T01:00:00Z"
	rec.AnalysisSHA256 = strings.Repeat("2", 64)
	analysis.Admission.DecidedAt = rec.CreatedAt
	raw, _ := json.Marshal(analysis.Admission)
	v, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	doc := v.(map[string]any)
	delete(doc, "signature")
	analysis.Admission.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	rec.Signature, err = s.key.SignCanonical(unsigned(*rec))
	if err != nil {
		t.Fatal(err)
	}
	for i := range list.Items {
		list.Items[i].Summary.CreatedAt = rec.CreatedAt
	}
	for name, value := range map[string]any{"local-skill-import-remote-create.v1": req, "local-skill-import.v2": rec, "local-skill-import-result.v2": NewResult(rec, analysis, false), "local-skill-import-list.v2": list} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/" + name + ".sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("remote sample differs", name, err)
		}
	}
}

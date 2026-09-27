package skillimport

import (
	"bytes"
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// gitFixtureRepo builds a real local repository with SKILL.md at the root, a
// skill/ subdirectory, an executable script and a malicious post-checkout hook
// that would create a marker file in the fixture root if any hook ran during
// clone or checkout.
func gitFixtureRepo(t *testing.T) (repoURL, commit, root string) {
	t.Helper()
	root = t.TempDir()
	repo := filepath.Join(root, "repo")
	run := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = repo
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %s: %v: %s", strings.Join(args, " "), err, out)
		}
		return string(out)
	}
	if err := os.MkdirAll(repo, 0700); err != nil {
		t.Fatal(err)
	}
	run("init", "-q", "-b", "main", repo)
	write := func(rel, body string, mode os.FileMode) {
		t.Helper()
		path := filepath.Join(repo, rel)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(body), mode); err != nil {
			t.Fatal(err)
		}
	}
	write("SKILL.md", "---\nname: git-import\ndescription: Import from a git source.\n---\nRead only.\n", 0600)
	write("install.sh", "#!/bin/sh\necho never-executed-by-import\n", 0700)
	write("docs/note.md", "notes\n", 0600)
	write("skill/SKILL.md", "---\nname: nested-skill\ndescription: Nested skill copy.\n---\nNested.\n", 0600)
	write("skill/helper.md", "helper\n", 0600)
	write(".git/hooks/post-checkout", "#!/bin/sh\necho ran > "+filepath.Join(root, "hook-ran")+"\n", 0700)
	run("add", "-A")
	run("-c", "user.email=fixture@example.com", "-c", "user.name=fixture", "commit", "-q", "-m", "fixture")
	commit = strings.TrimSpace(run("rev-parse", "HEAD"))
	if !commitPattern.MatchString(commit) {
		t.Fatal("fixture commit not resolved")
	}
	return "file://" + repo, commit, root
}

func gitTestStore(t *testing.T, fixtureURL string) (*Store, *GitCreateRequest) {
	t.Helper()
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	// Git for Windows bounds its internal $GIT_DIR even when core.longpaths
	// is enabled. Avoid adding the full test name to the nested clone path.
	tempState, err := os.MkdirTemp("", "siq-git-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(tempState); err != nil {
			t.Error(err)
		}
	})
	store, err := Open(tempState, key, pack, "fixture")
	if err != nil {
		t.Fatal(err)
	}
	// Tests drive cloneGit over a file:// transport with
	// protocol.file.allow=user; production git imports use the controlled
	// hosted-source fetch (ADR-0051) and never clone.
	store.gitFetch = func(ctx context.Context, url, ref, dst string) (string, error) {
		return cloneGit(ctx, fixtureURL, ref, dst, "user")
	}
	req := &GitCreateRequest{
		SchemaVersion: "local-skill-import-git-create/v1",
		ImportID:      "si-" + strings.Repeat("b", 32),
		URL:           "https://git.example.com/org/skill.git",
		ActorID:       "fixture-reviewer",
	}
	return store, req
}

func TestGitImportClonesFixedCopyWithoutHooks(t *testing.T) {
	fixtureURL, commit, fixtureRoot := gitFixtureRepo(t)
	s, req := gitTestStore(t, fixtureURL)
	record, analysis, reused, err := s.CreateGit(context.Background(), *req)
	if err != nil || reused {
		t.Fatal(err, reused)
	}
	if record.SchemaVersion != "local-skill-import/v2" || record.SourceKind != "git" || record.Git == nil {
		t.Fatal(record.SchemaVersion, record.SourceKind, record.Git)
	}
	if record.Git.CommitSHA != commit || record.Git.URL != req.URL || record.Git.Ref != "" {
		t.Fatal(record.Git)
	}
	if !record.ExcludedGitMetadata {
		t.Fatal("git metadata not excluded")
	}
	// The local clone seam snapshots filesystem modes. Windows does not
	// represent POSIX execute bits on ordinary .sh files.
	wantExecutable := runtime.GOOS != "windows"
	scriptInfo, err := os.Stat(filepath.Join(fixtureRoot, "repo", "install.sh"))
	if err != nil || (scriptInfo.Mode().Perm()&0111 != 0) != wantExecutable {
		t.Fatalf("unexpected fixture script mode: %v, %v", scriptInfo, err)
	}
	var scriptFound bool
	for _, file := range record.Files {
		if strings.Contains(file.Path, ".git") {
			t.Fatal("git metadata leaked into payload", file.Path)
		}
		if file.Path == "install.sh" {
			scriptFound = true
			if file.Executable != wantExecutable {
				t.Fatalf("script executable = %v, want %v", file.Executable, wantExecutable)
			}
		}
	}
	if !scriptFound {
		t.Fatal("script missing from snapshot")
	}
	if !admission.Verify(s.key.Public(), analysis.Admission) {
		t.Fatal("unverified admission")
	}
	if _, err := os.Stat(filepath.Join(fixtureRoot, "hook-ran")); err == nil {
		t.Fatal("repository hook executed during import")
	}
	// Payload readback and re-scan: Load verifies the fixed copy end to end.
	if _, _, err := s.Load(context.Background(), req.ImportID); err != nil {
		t.Fatal(err)
	}
	// Identical request reuses the published candidate.
	again, _, reusedAgain, err := s.CreateGit(context.Background(), *req)
	if err != nil || !reusedAgain || again.Git.CommitSHA != commit {
		t.Fatal(err, reusedAgain)
	}
	// The same ID with a different pin conflicts with the published record.
	pinned := *req
	pinned.ExpectedCommit = strings.Repeat("a", 40)
	if _, _, _, err = s.CreateGit(context.Background(), pinned); !errors.Is(err, ErrConflict) {
		t.Fatal("different locator reused ID", err)
	}
	// A wrong commit pin on a fresh ID is rejected after the clone.
	mispin := *req
	mispin.ImportID = "si-" + strings.Repeat("c", 32)
	mispin.ExpectedCommit = strings.Repeat("a", 40)
	if _, _, _, err = s.CreateGit(context.Background(), mispin); !errors.Is(err, ErrArchiveMismatch) {
		t.Fatal("wrong pin accepted", err)
	}
	// A missing subdirectory is rejected.
	sub := *req
	sub.ImportID = "si-" + strings.Repeat("d", 32)
	sub.SubDir = "absent"
	if _, _, _, err = s.CreateGit(context.Background(), sub); !errors.Is(err, ErrInvalid) {
		t.Fatal("missing subdir accepted", err)
	}
}

func TestGitImportSubDirectorySelectsSubtree(t *testing.T) {
	fixtureURL, commit, _ := gitFixtureRepo(t)
	s, req := gitTestStore(t, fixtureURL)
	req.SubDir = "skill"
	record, _, _, err := s.CreateGit(context.Background(), *req)
	if err != nil {
		t.Fatal(err)
	}
	if record.Git.SubDir != "skill" || record.Git.CommitSHA != commit {
		t.Fatal(record.Git)
	}
	if len(record.Files) != 2 {
		t.Fatal(record.Files)
	}
	for _, file := range record.Files {
		// Paths are relative to the selected subtree: parent files such as
		// SKILL.md or install.sh must not appear, and neither may docs/.
		if file.Path != "SKILL.md" && file.Path != "helper.md" {
			t.Fatal("subdir selection leaked parent files", file.Path)
		}
	}
}

func TestGitImportValidation(t *testing.T) {
	fixtureURL, _, _ := gitFixtureRepo(t)
	s, base := gitTestStore(t, fixtureURL)
	cases := map[string]func(*GitCreateRequest){
		"schema":      func(r *GitCreateRequest) { r.SchemaVersion = "local-skill-import-remote-create/v1" },
		"import_id":   func(r *GitCreateRequest) { r.ImportID = "si-short" },
		"actor":       func(r *GitCreateRequest) { r.ActorID = " spaced " },
		"ref_parent":  func(r *GitCreateRequest) { r.Ref = "../evil" },
		"ref_dash":    func(r *GitCreateRequest) { r.Ref = "-u" },
		"ref_space":   func(r *GitCreateRequest) { r.Ref = "main x" },
		"ref_dots":    func(r *GitCreateRequest) { r.Ref = "a..b" },
		"ref_commit":  func(r *GitCreateRequest) { r.Ref = strings.Repeat("a", 40) },
		"ref_lock":    func(r *GitCreateRequest) { r.Ref = "main.lock" },
		"ref_slash":   func(r *GitCreateRequest) { r.Ref = "main/" },
		"ref_dot":     func(r *GitCreateRequest) { r.Ref = "refs/heads/x." },
		"ref_hidden":  func(r *GitCreateRequest) { r.Ref = "refs/.hidden" },
		"pin_hex":     func(r *GitCreateRequest) { r.ExpectedCommit = "nothex" },
		"pin_sha256":  func(r *GitCreateRequest) { r.ExpectedCommit = strings.Repeat("a", 64) },
		"sub_parent":  func(r *GitCreateRequest) { r.SubDir = "../out" },
		"sub_git":     func(r *GitCreateRequest) { r.SubDir = ".git" },
		"sub_nested":  func(r *GitCreateRequest) { r.SubDir = "a/.git/x" },
		"url_http":    func(r *GitCreateRequest) { r.URL = "http://git.example.com/org/skill.git" },
		"url_private": func(r *GitCreateRequest) { r.URL = "https://127.0.0.1/org/skill.git" },
		"url_user":    func(r *GitCreateRequest) { r.URL = "https://user:pass@git.example.com/org/skill.git" },
		"url_frag":    func(r *GitCreateRequest) { r.URL = "https://git.example.com/org/skill.git#main" },
		"url_path":    func(r *GitCreateRequest) { r.URL = "/some/local/path" },
	}
	for name, mutate := range cases {
		req := *base
		mutate(&req)
		_, _, _, err := s.CreateGit(context.Background(), req)
		if errors.Is(err, ErrURLBlocked) {
			continue
		}
		if err == nil || !errors.Is(err, ErrInvalid) {
			t.Fatalf("%s accepted: %v", name, err)
		}
	}
}

func TestGitRefValid(t *testing.T) {
	for _, ref := range []string{"main", "v1.2.3", "refs/heads/feature-x", "release-1.0"} {
		if !gitRefValid(ref) {
			t.Fatal("valid ref rejected", ref)
		}
	}
	for _, ref := range []string{"", "-x", "a..b", "a b", "x/", "x.lock", "refs/.hidden", strings.Repeat("a", 40), strings.Repeat("a", 129), "main\t"} {
		if gitRefValid(ref) {
			t.Fatal("invalid ref accepted", ref)
		}
	}
}

func TestGitRecordValidation(t *testing.T) {
	metadata := &GitMetadata{URL: "https://git.example.com/org/skill.git", Ref: "main", SubDir: "", ExpectedCommit: strings.Repeat("a", 40), CommitSHA: strings.Repeat("a", 40)}
	if !gitValid(metadata) {
		t.Fatal("valid git metadata rejected")
	}
	bad := []GitMetadata{
		{URL: "http://git.example.com/s.git", CommitSHA: strings.Repeat("a", 40)},
		{URL: "https://git.example.com/s.git", CommitSHA: "deadbeef"},
		{URL: "https://127.0.0.1/s.git", CommitSHA: strings.Repeat("a", 40)},
		{URL: "https://git.example.com/s.git", CommitSHA: strings.Repeat("a", 40), Ref: "../x"},
		{URL: "https://git.example.com/s.git", CommitSHA: strings.Repeat("a", 40), SubDir: ".git"},
		{URL: "https://git.example.com/s.git", CommitSHA: strings.Repeat("a", 40), ExpectedCommit: strings.Repeat("b", 40)},
	}
	for i := range bad {
		if gitValid(&bad[i]) {
			t.Fatalf("bad git metadata %d accepted", i)
		}
	}
	if gitValid(nil) {
		t.Fatal("nil git metadata accepted")
	}
	record := Record{SchemaVersion: "local-skill-import/v2", SourceKind: "git", Git: metadata}
	if !recordVersionValid(record) {
		t.Fatal("valid git record rejected")
	}
	invalid := []Record{
		{SchemaVersion: "local-skill-import/v1", SourceKind: "local_dir", Git: metadata},
		{SchemaVersion: "local-skill-import/v2", SourceKind: "https_zip", Git: metadata},
		{SchemaVersion: "local-skill-import/v2", SourceKind: "git"},
		{SchemaVersion: "local-skill-import/v2", SourceKind: "git", Remote: &RemoteMetadata{}},
	}
	for i := range invalid {
		if recordVersionValid(invalid[i]) {
			t.Fatalf("invalid record %d accepted", i)
		}
	}
}

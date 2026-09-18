package skillinstall

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

// The git update loop drives a full lifecycle against a real local
// repository: install from a branch head, detect a branch advance with a
// read-only check, bind an explicitly imported candidate pinned at the new
// commit, and reject a stale candidate. The hosted fetch itself is covered
// by the skillimport package; here the store's upstream seam stands in for
// it by snapshotting the repository worktree, so the record binding,
// comparison and confirmation logic run against real git state.

const gitLoopURL = "https://git.example.com/org/skill.git"

type gitLoop struct {
	f      fixture
	op     *Operation
	repo   gitRepo
	commit string
}

func gitRepoRun(t *testing.T, repo string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s: %v: %s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

type gitRepo struct {
	root string
}

func newGitRepo(t *testing.T) gitRepo {
	t.Helper()
	root := t.TempDir()
	gitRepoRun(t, root, "init", "-q", "-b", "main", root)
	repo := gitRepo{root: root}
	repo.commit(t, map[string]string{
		"SKILL.md": "---\nname: example\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\nRead a synthetic report.\n",
	})
	return repo
}

// commit writes files, commits, and returns the new head commit.
func (r gitRepo) commit(t *testing.T, files map[string]string) string {
	t.Helper()
	for rel, body := range files {
		path := filepath.Join(r.root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
	}
	gitRepoRun(t, r.root, "add", "-A")
	gitRepoRun(t, r.root, "-c", "user.email=fixture@example.com", "-c", "user.name=fixture", "commit", "-q", "-m", "fixture-advance")
	return gitRepoRun(t, r.root, "rev-parse", "HEAD")
}

func (r gitRepo) head(t *testing.T) string {
	t.Helper()
	return gitRepoRun(t, r.root, "rev-parse", "HEAD")
}

// copyWorktree materializes the checked-out tree into dst the way a fetch
// does: no .git metadata, private permissions, executable bits preserved.
func (r gitRepo) copyWorktree(t *testing.T, dst string) {
	t.Helper()
	err := filepath.WalkDir(r.root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(r.root, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		if rel == ".git" {
			return filepath.SkipDir
		}
		target := filepath.Join(dst, filepath.FromSlash(rel))
		if entry.IsDir() {
			return os.MkdirAll(target, 0700)
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		mode := os.FileMode(0600)
		if info.Mode().Perm()&0100 != 0 {
			mode = 0700
		}
		return os.WriteFile(target, raw, mode)
	})
	if err != nil {
		t.Fatal(err)
	}
}

// snapshot reports the worktree the way an upstream check sees it: the
// sorted tree plus the current head commit, never asserting the pinned one.
func (r gitRepo) snapshot(t *testing.T) *skillimport.UpstreamSnapshot {
	t.Helper()
	out := &skillimport.UpstreamSnapshot{SourceKind: "git", URL: gitLoopURL, Directories: []string{}, Files: []skillimport.File{}}
	err := filepath.WalkDir(r.root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(r.root, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		if rel == ".git" {
			return filepath.SkipDir
		}
		slash := filepath.ToSlash(rel)
		if entry.IsDir() {
			out.Directories = append(out.Directories, slash)
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		digest := sha256.Sum256(raw)
		out.Files = append(out.Files, skillimport.File{Path: slash, SHA256: hex.EncodeToString(digest[:]), Bytes: int64(len(raw)), Executable: info.Mode().Perm()&0100 != 0})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	out.CommitSHA = r.head(t)
	return out
}

func gitLoopWriteSource(t *testing.T, f fixture, repo gitRepo, id string) string {
	t.Helper()
	// The import materializes a real copy of the worktree and signs the
	// usual digests; the record is then pinned to the git identity so the
	// whole update loop treats it as a git import.
	source := t.TempDir()
	repo.copyWorktree(t, source)
	if _, _, _, err := f.store.imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	commit := repo.head(t)
	gitLoopPinRecord(t, f, id, commit)
	return commit
}

// gitLoopPinRecord rewrites an import record on disk into the git shape and
// re-signs it with the fixture key, keeping the artifact binding intact.
func gitLoopPinRecord(t *testing.T, f fixture, id, commit string) {
	t.Helper()
	path := filepath.Join(filepath.Dir(f.store.dir), "skill-imports", "records", id+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	value, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	doc, ok := value.(map[string]any)
	if !ok {
		t.Fatal("record is not an object")
	}
	doc["schema_version"] = "local-skill-import/v2"
	doc["source_kind"] = "git"
	delete(doc, "remote")
	doc["git"] = map[string]any{"url": gitLoopURL, "ref": "", "sub_dir": "", "expected_commit": "", "commit_sha": commit}
	doc["excluded_git_metadata"] = true
	canonical, err := canon.Marshal(map[string]any{"url": gitLoopURL, "ref": "", "sub_dir": "", "expected_commit": ""})
	if err != nil {
		t.Fatal(err)
	}
	doc["source_locator_digest"] = hash(canonical)
	delete(doc, "signature")
	signature, err := f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	doc["signature"] = signature
	signed, err := canon.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, signed, 0600); err != nil {
		t.Fatal(err)
	}
}

func gitLoopFixture(t *testing.T) gitLoop {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	imports, err := skillimport.Open(st.Dir, key, pack, "fixture")
	if err != nil {
		t.Fatal(err)
	}
	repo := newGitRepo(t)
	id := "si-" + strings.Repeat("a", 32)
	source := t.TempDir()
	repo.copyWorktree(t, source)
	if _, _, _, err := imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	commit := repo.head(t)
	_, derived, err := imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	instance := "hi-" + strings.Repeat("b", 32)
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: "hri-" + strings.Repeat("b", 32)}}, "human", "ip-"+strings.Repeat("c", 32))
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err := st.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: -1, DesiredPolicy: built.DesiredPolicy, Audit: &state.AuditEvent{Event: "fixture_approve", Target: approved.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	s, err := Open(st, key, imports, func(context.Context, string) (Target, error) {
		return Target{InstanceID: instance, Platform: "hermes", Root: root, Display: "Hermes work"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	f := fixture{s, Request{SchemaVersion: "local-skill-install-stage-create/v1", RequestID: "is-" + strings.Repeat("d", 32), GrantID: approved.GrantID, ExpectedRevision: rev, InstanceID: instance, DirectoryName: "example", ActorID: "human"}, source, root, id}
	// Pin the installed record to git after the install flow is complete;
	// from here on the upstream seam answers checks from the live repo.
	gitLoopPinRecord(t, f, id, commit)
	s.upstream = func(ctx context.Context, record *skillimport.Record, remoteURL string) (*skillimport.UpstreamSnapshot, error) {
		if record.SourceKind != "git" || record.Git == nil || record.Git.URL != gitLoopURL || remoteURL != "" {
			return nil, errors.New("fixture: unexpected upstream fetch")
		}
		return repo.snapshot(t), nil
	}
	p, reused, err := s.Stage(nil, f.request)
	if err != nil || reused {
		t.Fatal(p, reused, err)
	}
	op, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	return gitLoop{f: f, op: op, repo: repo, commit: commit}
}

var gitLoopAdvanced = map[string]string{
	"SKILL.md":  "---\nname: example\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\nRead version two.\n",
	"CHANGE.md": "advanced\n",
}

// gitLoopCandidate imports and approves a candidate pinned at the repo's
// current head, mirroring the explicit user-driven update flow.
func gitLoopCandidate(t *testing.T, gl gitLoop) (UpdateStageRequest, string) {
	t.Helper()
	f := gl.f
	id := "si-" + strings.Repeat("e", 32)
	commit := gitLoopWriteSource(t, f, gl.repo, id)
	_, derived, err := f.store.imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.store.authority.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: f.store.key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: "hri-" + strings.Repeat("b", 32)}}, "human", "ip-"+strings.Repeat("f", 32))
	if err != nil {
		t.Fatal(err)
	}
	rev, err := f.store.authority.CommitGrant(state.GrantCommit{Grant: built.Grant, ExpectedRevision: -1, DesiredPolicy: built.DesiredPolicy, Audit: &state.AuditEvent{Event: "fixture_candidate", Target: built.Grant.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, f.store.key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err = f.store.authority.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "fixture_approve_update", Target: built.Grant.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	req := UpdateStageRequest{"local-skill-update-stage-create/v1", "up-" + strings.Repeat("a", 32), gl.op.Signature, built.Grant.GrantID, rev, f.request.ExpectedRevision, "", "human"}
	return req, commit
}

func TestUpdateGitLoopDetectsBranchAdvance(t *testing.T) {
	gl := gitLoopFixture(t)
	s := gl.f.store
	check := UpdateCheckRequest{SchemaVersion: "local-skill-update-check/v1", ActorID: "human"}
	first, err := s.CheckUpdate(context.Background(), gl.op.InstallID, check)
	if err != nil {
		t.Fatal(err)
	}
	if first.Status != "up_to_date" || first.SourceKind != "git" || first.UpstreamCommitSHA != gl.commit || first.RequiresConfirmation || first.ContentChangesTotal != 0 {
		t.Fatal(first)
	}
	// The signed record carries the URL; a caller-supplied one is refused.
	if _, err := s.CheckUpdate(context.Background(), gl.op.InstallID, UpdateCheckRequest{SchemaVersion: "local-skill-update-check/v1", RemoteURL: "https://git.example.com/org/other.git", ActorID: "human"}); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	next := gl.repo.commit(t, gitLoopAdvanced)
	second, err := s.CheckUpdate(context.Background(), gl.op.InstallID, check)
	if err != nil {
		t.Fatal(err)
	}
	if second.Status != "new_version" || !second.RequiresConfirmation || second.UpstreamCommitSHA != next || second.ContentChangesTotal != 2 || len(second.ContentChanges) != 2 {
		t.Fatal(second)
	}
	seen := map[string]bool{}
	for _, change := range second.ContentChanges {
		seen[change.PathDisplay] = true
		if change.Before == nil && change.After == nil {
			t.Fatal(change)
		}
	}
	if !seen["SKILL.md"] || !seen["CHANGE.md"] {
		t.Fatal(seen)
	}
	// The check is read-only: the installed target still runs the old copy.
	if raw, err := os.ReadFile(filepath.Join(gl.f.root, "skills", "example", "SKILL.md")); err != nil || !strings.Contains(string(raw), "Read a synthetic report.") {
		t.Fatal("check applied upstream content", err)
	}
}

func TestUpdateGitLoopConfirmBindsAdvancedCandidate(t *testing.T) {
	gl := gitLoopFixture(t)
	s := gl.f.store
	gl.repo.commit(t, gitLoopAdvanced)
	req, candidateCommit := gitLoopCandidate(t, gl)
	p, reused, err := s.StageUpdate(nil, gl.op.InstallID, req)
	if err != nil || reused {
		t.Fatal(p, reused, err)
	}
	// The plan binds the candidate import, which is pinned at the advanced commit.
	if p.CandidateSource.ImportID != "si-"+strings.Repeat("e", 32) || !p.RequiresConfirmation || p.PlatformChanges || p.RuntimeVerified {
		t.Fatal(p)
	}
	candidate, err := s.imports.ReadRecord(nil, p.CandidateSource.ImportID)
	if err != nil || candidate.Git == nil || candidate.Git.CommitSHA != candidateCommit {
		t.Fatal(candidate, err)
	}
	target := filepath.Join(gl.f.root, "skills", "example", "SKILL.md")
	old, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	view, err := s.CommitUpdate(nil, UpdateCommitRequest{"local-skill-update-commit/v1", p.UpdateID, p.Signature, "human", true})
	if err != nil || view.Result == nil || view.Result.Status != "updated_unverified" {
		t.Fatal(view, err)
	}
	updated, err := os.ReadFile(target)
	if err != nil || !strings.Contains(string(updated), "version two") || string(updated) == string(old) {
		t.Fatal("confirm did not install the candidate", err)
	}
	if _, err := os.Stat(filepath.Join(gl.f.root, "skills", "example", "CHANGE.md")); err != nil {
		t.Fatal("candidate file missing after confirm", err)
	}
	if g, _, err := s.authority.GetGrantWithSeq(gl.f.request.GrantID); err != nil || g.Status != "revoked" {
		t.Fatal("previous grant not revoked", err)
	}
}

func TestUpdateGitLoopRejectsStaleCandidate(t *testing.T) {
	gl := gitLoopFixture(t)
	s := gl.f.store
	gl.repo.commit(t, gitLoopAdvanced)
	req, _ := gitLoopCandidate(t, gl)
	p, reused, err := s.StageUpdate(nil, gl.op.InstallID, req)
	if err != nil || reused {
		t.Fatal(p, reused, err)
	}
	// A staged candidate whose authority moved afterwards is stale: the
	// confirmation must refuse and the installed copy must stay intact.
	g, rev, err := s.authority.GetGrantWithSeq(req.CandidateGrantID)
	if err != nil {
		t.Fatal(err)
	}
	revoked, err := grant.Revoke(*g, s.key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.authority.CommitGrant(state.GrantCommit{Grant: revoked, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "fixture_revoke_candidate", Target: g.GrantID}}); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(gl.f.root, "skills", "example", "SKILL.md")
	old, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.CommitUpdate(nil, UpdateCommitRequest{"local-skill-update-commit/v1", p.UpdateID, p.Signature, "human", true}); !errors.Is(err, ErrChanged) {
		t.Fatal("stale candidate accepted", err)
	}
	updated, err := os.ReadFile(target)
	if err != nil || string(updated) != string(old) {
		t.Fatal("stale confirm touched the target", err)
	}
}

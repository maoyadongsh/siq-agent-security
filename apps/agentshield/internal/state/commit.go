package state

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"

	"siq-agent-security/apps/agentshield/internal/grant"
)

// GrantCommit contains already authorized documents. Recovery never signs,
// approves, or invokes an enforcement backend.
type GrantCommit struct {
	Grant            grant.Grant         `json:"grant"`
	ExpectedRevision int                 `json:"expected_revision"`
	DesiredPolicy    grant.DesiredPolicy `json:"desired_policy,omitempty"`
	Audit            *AuditEvent         `json:"audit,omitempty"`
}

type grantJournal struct {
	Schema string      `json:"schema"`
	Commit GrantCommit `json:"commit"`
}

type IncompleteCommitError struct {
	GrantID string
	Seq     int
	Phase   string
	Err     error
}

func (e *IncompleteCommitError) Error() string {
	return fmt.Sprintf("state: incomplete commit grant=%s seq=%d phase=%s", e.GrantID, e.Seq, e.Phase)
}
func (e *IncompleteCommitError) Unwrap() error { return e.Err }

var ErrIncompleteCommit = errors.New("state: incomplete commit")

func (e *IncompleteCommitError) Is(target error) bool { return target == ErrIncompleteCommit }

// Serialize the compound protocol within a daemon. Cross-process callers must
// hold AcquireWriter, as serve, offline grant and recovery do.
var commitMu sync.Mutex

// Set only by the isolated subprocess fault-injection test, never via runtime input.
var commitBoundary = func(string) {}

const maxCommitBytes = 8 << 20

func commitID(c GrantCommit) string {
	return fmt.Sprintf("%s.%d", c.Grant.GrantID, c.ExpectedRevision+1)
}
func (s *Store) commitPath(id, suffix string) string {
	return filepath.Join(s.Dir, "commits", id+suffix)
}

func validateCommit(c GrantCommit) error {
	if !safeID(c.Grant.GrantID) || c.ExpectedRevision < -1 {
		return errors.New("state: invalid commit identity or revision")
	}
	if c.DesiredPolicy != nil {
		id, _ := c.DesiredPolicy["policy_id"].(string)
		if !safeID(id) {
			return errors.New("state: invalid policy id")
		}
	}
	if c.Audit != nil && c.Audit.Target != c.Grant.GrantID {
		return errors.New("state: commit audit target mismatch")
	}
	return nil
}

// CommitGrant durably prepares all materials before publishing any grant. The
// final marker binds their bytes and is the visibility boundary for readers.
func (s *Store) CommitGrant(c GrantCommit) (int, error) {
	commitMu.Lock()
	defer commitMu.Unlock()
	if err := validateCommit(c); err != nil {
		return -1, err
	}
	raw, err := json.Marshal(grantJournal{Schema: "grant_commit/v1", Commit: c})
	if err != nil {
		return -1, err
	}
	if len(raw) > maxCommitBytes {
		return -1, errors.New("state: commit budget exceeded")
	}
	id := commitID(c)
	old, err := readCommitFile(s.commitPath(id, ".prepare.json"))
	if err == nil {
		if !bytes.Equal(old, raw) {
			return -1, ErrRevisionConflict
		}
		return s.replayCommit(c, raw)
	}
	if !errors.Is(err, os.ErrNotExist) {
		return -1, err
	}
	actual, _, err := s.LatestSeq("grants", c.Grant.GrantID)
	if err != nil {
		return -1, err
	}
	if actual != c.ExpectedRevision {
		return actual, &RevisionConflictError{Expected: c.ExpectedRevision, Actual: actual}
	}
	if err := s.checkGrantCommit(c.Grant.GrantID, actual); err != nil {
		return -1, err
	}
	if err := publishCommitFile(s.commitPath(id, ".prepare.json"), raw); err != nil {
		return -1, err
	}
	commitBoundary("prepared")
	return s.replayCommit(c, raw)
}

func (s *Store) replayCommit(c GrantCommit, raw []byte) (int, error) {
	seq := c.ExpectedRevision + 1
	id := commitID(c)
	fail := func(phase string, err error) (int, error) {
		return seq, &IncompleteCommitError{GrantID: c.Grant.GrantID, Seq: seq, Phase: phase, Err: err}
	}
	done, err := s.commitDone(id, raw)
	if err != nil {
		return fail("marker", err)
	}
	if done {
		return seq, nil
	}
	actual, current, err := s.LatestSeq("grants", c.Grant.GrantID)
	if err != nil {
		return fail("revision", err)
	}
	grantRaw, err := json.MarshalIndent(c.Grant, "", "  ")
	if err != nil {
		return fail("grant", err)
	}
	if actual != c.ExpectedRevision && (actual != seq || !bytes.Equal(current, grantRaw)) {
		return fail("revision", ErrRevisionConflict)
	}
	if c.DesiredPolicy != nil {
		if err := s.PutDesiredPolicy(c.DesiredPolicy); err != nil {
			return fail("desired_policy", err)
		}
	}
	commitBoundary("policy")
	if c.Audit != nil {
		auditRaw, err := json.Marshal(c.Audit)
		if err != nil {
			return fail("audit", err)
		}
		if err := publishCommitFile(filepath.Join(s.Dir, "commit-audit", id+".json"), auditRaw); err != nil {
			return fail("audit", err)
		}
	}
	commitBoundary("audit")
	if err := publishCommitFile(filepath.Join(s.Dir, "grants", id+".json"), grantRaw); err != nil {
		return fail("grant", err)
	}
	commitBoundary("grant")
	sum := sha256.Sum256(raw)
	if err := publishCommitFile(s.commitPath(id, ".done.json"), []byte(hex.EncodeToString(sum[:])+"\n")); err != nil {
		return fail("marker", err)
	}
	commitBoundary("done")
	return seq, nil
}

func (s *Store) commitDone(id string, raw []byte) (bool, error) {
	done, err := readCommitFile(s.commitPath(id, ".done.json"))
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	sum := sha256.Sum256(raw)
	if string(done) != hex.EncodeToString(sum[:])+"\n" {
		return false, errors.New("state: commit digest mismatch")
	}
	return true, nil
}

// Refuse both an incomplete current version and an interrupted update of an
// existing grant. Continuing to use the old grant could undo a pending revoke.
func (s *Store) checkGrantCommit(id string, seq int) error {
	for _, n := range []int{seq, seq + 1} {
		if n < 0 {
			continue
		}
		stem := fmt.Sprintf("%s.%d", id, n)
		if _, err := os.Lstat(s.commitPath(stem, ".incomplete.json")); err == nil {
			return ErrIncompleteCommit
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		raw, err := readCommitFile(s.commitPath(stem, ".prepare.json"))
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return err
		}
		if _, err := decodeCommit(stem, raw); err != nil {
			return err
		}
		done, err := s.commitDone(stem, raw)
		if err != nil {
			return err
		}
		if !done {
			return ErrIncompleteCommit
		}
	}
	return nil
}

func decodeCommit(id string, raw []byte) (GrantCommit, error) {
	var j grantJournal
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&j); err != nil {
		return j.Commit, errors.New("state: malformed commit")
	}
	if err := dec.Decode(new(any)); err != io.EOF {
		return j.Commit, errors.New("state: trailing commit data")
	}
	if j.Schema != "grant_commit/v1" || commitID(j.Commit) != id {
		return j.Commit, errors.New("state: commit identity/schema mismatch")
	}
	return j.Commit, validateCommit(j.Commit)
}

// Read-only, secret-free diagnostic output. Legacy markers have no replay data.
type IncompleteCommit struct {
	GrantID     string `json:"grant_id"`
	Seq         int    `json:"seq"`
	Phase       string `json:"phase"`
	Recoverable bool   `json:"recoverable"`
}

func (s *Store) HasIncompleteCommit(id string, seq int) bool {
	return s.checkGrantCommit(id, seq) != nil
}
func (s *Store) ListIncompleteCommits() ([]IncompleteCommit, error) {
	out := []IncompleteCommit{}
	entries, err := os.ReadDir(s.commitPath("", ""))
	if errors.Is(err, os.ErrNotExist) {
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	for _, e := range entries {
		name := e.Name()
		if strings.HasSuffix(name, ".prepare.json") {
			id := strings.TrimSuffix(name, ".prepare.json")
			raw, err := readCommitFile(s.commitPath(id, ".prepare.json"))
			if err != nil {
				return nil, err
			}
			c, err := decodeCommit(id, raw)
			if err != nil {
				return nil, err
			}
			done, err := s.commitDone(id, raw)
			if err != nil {
				return nil, err
			}
			if done {
				continue
			}
			out = append(out, IncompleteCommit{GrantID: c.Grant.GrantID, Seq: c.ExpectedRevision + 1, Phase: "prepared", Recoverable: true})
		} else if strings.HasSuffix(name, ".incomplete.json") {
			raw, err := readCommitFile(filepath.Join(s.Dir, "commits", name))
			if err != nil {
				return nil, err
			}
			var old struct {
				GrantID string `json:"grant_id"`
				Seq     *int   `json:"seq"`
				Phase   string `json:"phase"`
				Status  string `json:"status"`
			}
			if json.Unmarshal(raw, &old) != nil || !safeID(old.GrantID) || old.Seq == nil || *old.Seq < 0 || old.Status != "incomplete" || (old.Phase != "audit" && old.Phase != "desired_policy") || name != fmt.Sprintf("%s.%d.incomplete.json", old.GrantID, *old.Seq) {
				return nil, errors.New("state: invalid legacy commit marker")
			}
			out = append(out, IncompleteCommit{GrantID: old.GrantID, Seq: *old.Seq, Phase: "legacy_manual_recovery"})
		}
	}
	return out, nil
}

// RecoverGrantCommits requires real ownership, including nonce, not just a PID.
func (s *Store) RecoverGrantCommits(w *Writer) (int, error) {
	if w == nil || filepath.Clean(w.Dir) != filepath.Clean(s.Dir) {
		return 0, ErrWriterBusy
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil || pid != os.Getpid() || pid != w.pid || owner != w.owner {
		return 0, ErrWriterBusy
	}
	commitMu.Lock()
	defer commitMu.Unlock()
	pending, err := s.ListIncompleteCommits()
	if err != nil {
		return 0, err
	}
	count := 0
	for _, p := range pending {
		if !p.Recoverable {
			return count, errors.New("state: legacy incomplete commit requires manual recovery")
		}
		id := fmt.Sprintf("%s.%d", p.GrantID, p.Seq)
		raw, err := readCommitFile(s.commitPath(id, ".prepare.json"))
		if err != nil {
			return count, err
		}
		c, err := decodeCommit(id, raw)
		if err != nil {
			return count, err
		}
		if _, err := s.replayCommit(c, raw); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

// committedAudit projects one event per committed journal; replay cannot append
// duplicates. Original audit.jsonl remains readable and is never rewritten.
func (s *Store) committedAudit() ([]AuditEvent, error) {
	entries, err := os.ReadDir(filepath.Join(s.Dir, "commit-audit"))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []AuditEvent
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		id := strings.TrimSuffix(e.Name(), ".json")
		raw, err := readCommitFile(s.commitPath(id, ".prepare.json"))
		if err != nil {
			return nil, err
		}
		c, err := decodeCommit(id, raw)
		if err != nil {
			return nil, err
		}
		done, err := s.commitDone(id, raw)
		if err != nil {
			return nil, err
		}
		if !done {
			continue
		}
		a, err := readCommitFile(filepath.Join(s.Dir, "commit-audit", e.Name()))
		if err != nil {
			return nil, err
		}
		expected, _ := json.Marshal(c.Audit)
		if c.Audit == nil || !bytes.Equal(a, expected) {
			return nil, errors.New("state: audit material mismatch")
		}
		out = append(out, *c.Audit)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].At < out[j].At })
	return out, nil
}

func readCommitFile(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxCommitBytes {
		return nil, errors.New("state: invalid commit file type/budget")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	actual, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !os.SameFile(info, actual) {
		return nil, errors.New("state: commit file replaced")
	}
	raw, err := io.ReadAll(io.LimitReader(f, maxCommitBytes+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > maxCommitBytes {
		return nil, errors.New("state: commit budget exceeded")
	}
	return raw, nil
}

// Same-directory immutable publication; a half-written final path is never
// visible. Existing identical bytes are replay success, other bytes conflict.
func publishCommitFile(path string, raw []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".pending-commit-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err := f.Write(raw); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Link(f.Name(), path); err != nil {
		if !errors.Is(err, os.ErrExist) {
			return err
		}
		previous, err := readCommitFile(path)
		if err != nil {
			return err
		}
		if !bytes.Equal(previous, raw) {
			return ErrConflict
		}
	}
	if runtime.GOOS != "windows" {
		d, err := os.Open(dir)
		if err != nil {
			return err
		}
		defer d.Close()
		return d.Sync()
	}
	return nil
}

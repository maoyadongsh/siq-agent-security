package state

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
)

// FileID maps an arbitrary key (candidate_id, finding_id) onto a safeID filename stem.
func FileID(prefix, key string) string {
	sum := sha256.Sum256([]byte(key))
	return prefix + hex.EncodeToString(sum[:8])
}

// RevisionConflictError is returned when PutVersionedCAS sees a different head.
type RevisionConflictError struct {
	Expected int
	Actual   int
}

func (e *RevisionConflictError) Error() string {
	return fmt.Sprintf("state: revision conflict: expected %d actual %d", e.Expected, e.Actual)
}

func (e *RevisionConflictError) Is(target error) bool {
	return target == ErrRevisionConflict
}

// ErrRevisionConflict marks compare-and-swap failures on versioned documents.
var ErrRevisionConflict = errors.New("state: revision conflict")

// LatestSeq returns the highest published version number for fileID, or -1 when
// no version exists. The raw bytes of that version are returned when present.
func (s *Store) LatestSeq(subdir, fileID string) (int, []byte, error) {
	if !safeID(fileID) {
		return -1, nil, errors.New("state: invalid file id")
	}
	dir := filepath.Join(s.Dir, subdir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return -1, nil, nil
		}
		return -1, nil, err
	}
	best := -1
	var bestPath string
	prefix := fileID + "."
	for _, e := range entries {
		name := e.Name()
		if !strings.HasPrefix(name, prefix) || !strings.HasSuffix(name, ".json") {
			continue
		}
		stem := strings.TrimSuffix(name, ".json")
		n, err := strconv.Atoi(stem[len(prefix):])
		if err != nil {
			continue
		}
		if n > best {
			best = n
			bestPath = filepath.Join(dir, name)
		}
	}
	if best < 0 {
		return -1, nil, nil
	}
	raw, err := os.ReadFile(bestPath)
	if err != nil {
		return -1, nil, err
	}
	return best, raw, nil
}

// PutVersioned exclusively publishes a complete <fileID>.<n>.json (ADR-012).
// Existing versions are never overwritten; only name collisions are retried.
// Prefer PutVersionedCAS for read-modify-write state transitions.
func (s *Store) PutVersioned(subdir, fileID string, doc any) error {
	tmp, cleanup, err := s.stageVersion(subdir, fileID, doc)
	if err != nil {
		return err
	}
	defer cleanup()
	dir := filepath.Join(s.Dir, subdir)
	for n := 0; n <= 10000; n++ {
		p := filepath.Join(dir, fmt.Sprintf("%s.%d.json", fileID, n))
		if err := os.Link(tmp, p); err == nil {
			return nil
		} else if !errors.Is(err, os.ErrExist) {
			return fmt.Errorf("state: exclusive version publication failed: %w", err)
		}
	}
	return errors.New("state: too many versions")
}

// PutVersionedCAS publishes expected+1 only when the current head equals expected
// (-1 means no version yet). On conflict it does not skip ahead to a later n.
func (s *Store) PutVersionedCAS(subdir, fileID string, expected int, doc any) (int, error) {
	if expected < -1 {
		return -1, errors.New("state: invalid expected revision")
	}
	tmp, cleanup, err := s.stageVersion(subdir, fileID, doc)
	if err != nil {
		return -1, err
	}
	defer cleanup()
	actual, _, err := s.LatestSeq(subdir, fileID)
	if err != nil {
		return -1, err
	}
	if actual != expected {
		return actual, &RevisionConflictError{Expected: expected, Actual: actual}
	}
	next := expected + 1
	p := filepath.Join(s.Dir, subdir, fmt.Sprintf("%s.%d.json", fileID, next))
	if err := os.Link(tmp, p); err != nil {
		if errors.Is(err, os.ErrExist) {
			head, _, _ := s.LatestSeq(subdir, fileID)
			return head, &RevisionConflictError{Expected: expected, Actual: head}
		}
		return -1, fmt.Errorf("state: exclusive version publication failed: %w", err)
	}
	return next, nil
}

func (s *Store) stageVersion(subdir, fileID string, doc any) (tmp string, cleanup func(), err error) {
	if !safeID(fileID) {
		return "", nil, errors.New("state: invalid file id")
	}
	dir := filepath.Join(s.Dir, subdir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", nil, err
	}
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return "", nil, err
	}
	f, err := os.CreateTemp(dir, ".pending-*")
	if err != nil {
		return "", nil, err
	}
	if err := f.Chmod(0o600); err != nil {
		_ = f.Close()
		_ = os.Remove(f.Name())
		if runtime.GOOS != "windows" {
			return "", nil, err
		}
	}
	tmp = f.Name()
	cleanup = func() { _ = os.Remove(tmp) }
	if _, err := f.Write(raw); err != nil {
		_ = f.Close()
		cleanup()
		return "", nil, err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		cleanup()
		return "", nil, err
	}
	if err := f.Close(); err != nil {
		cleanup()
		return "", nil, err
	}
	return tmp, cleanup, nil
}

// LatestVersioned returns the newest JSON document per fileID in subdir.
func (s *Store) LatestVersioned(subdir string) ([][]byte, error) {
	dir := filepath.Join(s.Dir, subdir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, err
	}
	latest := map[string]int{}
	files := map[string]string{}
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".json") {
			continue
		}
		stem := strings.TrimSuffix(name, ".json")
		dot := strings.LastIndex(stem, ".")
		if dot < 0 {
			continue
		}
		n, err := strconv.Atoi(stem[dot+1:])
		if err != nil {
			continue
		}
		id := stem[:dot]
		if cur, ok := latest[id]; !ok || n > cur {
			latest[id] = n
			files[id] = filepath.Join(dir, name)
		}
	}
	var out [][]byte
	for _, p := range files {
		raw, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		out = append(out, raw)
	}
	return out, nil
}

// AuditEvent is one append-only audit.jsonl line (no secrets, no params).
type AuditEvent struct {
	At      string `json:"at"`
	Event   string `json:"event"`
	ActorID string `json:"actor_id,omitempty"`
	Target  string `json:"target,omitempty"`
	Note    string `json:"note,omitempty"`
}

// AppendAudit appends one JSON line to audit.jsonl.
func (s *Store) AppendAudit(ev AuditEvent) error {
	raw, err := json.Marshal(ev)
	if err != nil {
		return err
	}
	p := filepath.Join(s.Dir, "audit.jsonl")
	f, err := os.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(raw, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

// TailAudit returns the last n events (n<=0 → 200).
func (s *Store) tailLegacyAudit(n int) ([]AuditEvent, error) {
	if n <= 0 {
		n = 200
	}
	p := filepath.Join(s.Dir, "audit.jsonl")
	f, err := os.Open(p)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()
	var lines []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
	for sc.Scan() {
		line := sc.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		lines = append(lines, line)
		if len(lines) > n {
			lines = lines[1:]
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	out := make([]AuditEvent, 0, len(lines))
	for _, line := range lines {
		var ev AuditEvent
		if json.Unmarshal([]byte(line), &ev) == nil {
			out = append(out, ev)
		}
	}
	return out, nil
}

// TailAudit merges immutable transaction audit with the legacy append stream.
func (s *Store) TailAudit(n int) ([]AuditEvent, error) {
	if n <= 0 {
		n = 200
	}
	old, err := s.tailLegacyAudit(n)
	if err != nil {
		return nil, err
	}
	added, err := s.committedAudit()
	if err != nil {
		return nil, err
	}
	out := append(old, added...)
	sort.SliceStable(out, func(i, j int) bool { return out[i].At < out[j].At })
	if len(out) > n {
		out = out[len(out)-n:]
	}
	return out, nil
}

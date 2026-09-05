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
	"strconv"
	"strings"
)

// FileID maps an arbitrary key (candidate_id, finding_id) onto a safeID filename stem.
func FileID(prefix, key string) string {
	sum := sha256.Sum256([]byte(key))
	return prefix + hex.EncodeToString(sum[:8])
}

// PutVersioned writes <subdir>/<fileID>.<n>.json (0600, O_EXCL). fileID must pass safeID.
func (s *Store) PutVersioned(subdir, fileID string, doc any) error {
	if !safeID(fileID) {
		return errors.New("state: invalid file id")
	}
	dir := filepath.Join(s.Dir, subdir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	n := 0
	for {
		p := filepath.Join(dir, fmt.Sprintf("%s.%d.json", fileID, n))
		if _, err := os.Stat(p); errors.Is(err, os.ErrNotExist) {
			return writeNew(p, raw)
		}
		n++
		if n > 10000 {
			return errors.New("state: too many versions")
		}
	}
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
	return f.Close()
}

// TailAudit returns the last n events (n<=0 → 200).
func (s *Store) TailAudit(n int) ([]AuditEvent, error) {
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

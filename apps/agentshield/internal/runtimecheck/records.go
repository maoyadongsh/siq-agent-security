package runtimecheck

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func (m *Manager) dir() string { return filepath.Join(m.o.Store.Dir, "runtime-checks") }
func (m *Manager) materials(id string) string {
	return filepath.Join(m.o.Store.Dir, "runtime-check-materials", id)
}
func recordMap(r record) map[string]any {
	raw, _ := json.Marshal(r)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	delete(out, "signature")
	return out
}
func (m *Manager) persist(r *record) error {
	next := *r
	next.Revision++
	var err error
	next.Signature, err = m.o.Key.SignCanonical(recordMap(next))
	if err != nil {
		return errors.New("runtime_check_record_failed")
	}
	raw, err := json.Marshal(next)
	if err != nil || len(raw) > 64<<10 || !idPattern.MatchString(next.Result.ID) {
		return errors.New("runtime_check_record_failed")
	}
	tmp, err := os.CreateTemp(m.dir(), ".pending-*")
	if err != nil {
		return errors.New("runtime_check_record_failed")
	}
	defer os.Remove(tmp.Name())
	if _, err = tmp.Write(raw); err == nil {
		err = tmp.Sync()
	}
	closeErr := tmp.Close()
	if err != nil || closeErr != nil {
		return errors.New("runtime_check_record_failed")
	}
	path := filepath.Join(m.dir(), fmt.Sprintf("%s.%06d.json", next.Result.ID, next.Revision))
	if err = os.Link(tmp.Name(), path); err != nil {
		return errors.New("runtime_check_record_failed")
	}
	*r = next
	return nil
}
func (m *Manager) records() (map[string]record, error) {
	entries, err := os.ReadDir(m.dir())
	if err != nil || len(entries) > 2048 {
		return nil, errors.New("runtime_check_history_unavailable")
	}
	out := map[string]record{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".pending-") {
			continue
		}
		path := filepath.Join(m.dir(), entry.Name())
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() || info.Size() > 64<<10 {
			return nil, errors.New("runtime_check_record_invalid")
		}
		f, err := os.Open(path)
		if err != nil {
			return nil, errors.New("runtime_check_record_invalid")
		}
		raw, err := io.ReadAll(io.LimitReader(f, (64<<10)+1))
		_ = f.Close()
		var r record
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.DisallowUnknownFields()
		var extra any
		if err != nil || len(raw) > 64<<10 || decoder.Decode(&r) != nil || decoder.Decode(&extra) != io.EOF || !idPattern.MatchString(r.Result.ID) || r.Revision < 0 || !signing.VerifyCanonical(m.o.Key.Public(), recordMap(r), r.Signature) || entry.Name() != fmt.Sprintf("%s.%06d.json", r.Result.ID, r.Revision) {
			return nil, errors.New("runtime_check_record_invalid")
		}
		if old, ok := out[r.Result.ID]; !ok || old.Revision < r.Revision {
			out[r.Result.ID] = r
		}
	}
	return out, nil
}

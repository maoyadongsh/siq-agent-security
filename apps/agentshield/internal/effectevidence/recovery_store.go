package effectevidence

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func (s *Store) recoveryDir(id string) (string, error) {
	if !idPattern.MatchString(id) {
		return "", ErrInvalid
	}
	root, err := s.pendingDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(root, id+".recoveries")
	if os.Mkdir(dir, 0700) != nil {
		info, err := os.Lstat(dir)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return "", ErrState
		}
	}
	return dir, nil
}
func (s *Store) recoveryHistory(p PendingFile, now time.Time) ([]FileRecovery, []string, error) {
	dir, err := s.recoveryDir(p.ID)
	if err != nil {
		return nil, nil, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return nil, nil, ErrState
	}
	entries, err := f.ReadDir(MaxRecoveries + 65)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return nil, nil, ErrState
	}
	if len(entries) > MaxRecoveries+64 {
		return nil, nil, ErrCapacity
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
	history := []FileRecovery{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".recovery-") {
			continue
		}
		if entry.Name() != fmt.Sprintf("%06d.json", len(history)+1) {
			return nil, nil, ErrState
		}
		path := filepath.Join(dir, entry.Name())
		info, e := os.Lstat(path)
		if e != nil || !info.Mode().IsRegular() || info.Size() > 4096 {
			return nil, nil, ErrState
		}
		raw, e := os.ReadFile(path)
		if e != nil {
			return nil, nil, ErrState
		}
		d := json.NewDecoder(bytes.NewReader(raw))
		d.DisallowUnknownFields()
		var r FileRecovery
		var extra any
		if d.Decode(&r) != nil || d.Decode(&extra) != io.EOF {
			return nil, nil, ErrState
		}
		history = append(history, r)
	}
	owners, err := RecoveryOwners(p, history, s.key.Public(), now)
	return history, owners, err
}
func (s *Store) activeRecovery(p PendingFile, now time.Time) ([]FileRecovery, []string, error) {
	history, owners, err := s.recoveryHistory(p, now)
	if err != nil {
		return nil, nil, err
	}
	expiry, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	captured, _ := time.Parse(time.RFC3339Nano, p.Before.CapturedAt)
	if !now.Before(expiry) || now.Before(captured) {
		return nil, nil, ErrConflict
	}
	for _, owner := range owners {
		_, err := s.getObserverRevocation(owner)
		if err == nil {
			return nil, nil, ErrConflict
		}
		if !errors.Is(err, ErrNotFound) {
			return nil, nil, err
		}
	}
	return history, owners, nil
}

// PendingFileOwner validates the original deadline and every historical owner.
func (s *Store) PendingFileOwner(id string, now time.Time) (string, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	p, err := s.getPending(id)
	if err != nil {
		return "", err
	}
	_, owners, err := s.activeRecovery(p, now)
	if err != nil {
		return "", err
	}
	return owners[len(owners)-1], nil
}

// RecoverPendingFile must only be called after admin authorization, source/scope
// validation and action revalidation. It durably compares and changes ownership.
func (s *Store) RecoverPendingFile(id, expectedOwner, owner string, now time.Time) (FileRecovery, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if !digestPattern.MatchString(expectedOwner) || !digestPattern.MatchString(owner) {
		return FileRecovery{}, ErrInvalid
	}
	p, err := s.getPending(id)
	if err != nil {
		return FileRecovery{}, err
	}
	history, owners, err := s.activeRecovery(p, now)
	if err != nil {
		return FileRecovery{}, err
	}
	current := owners[len(owners)-1]
	if current == owner && len(history) > 0 {
		return history[len(history)-1], nil
	}
	if current != expectedOwner {
		return FileRecovery{}, ErrConflict
	}
	if _, err := s.getObserverRevocation(owner); !errors.Is(err, ErrNotFound) {
		if err == nil {
			err = ErrConflict
		}
		return FileRecovery{}, err
	}
	r, err := newRecovery(p, history, owner, s.key, now)
	if err != nil {
		return FileRecovery{}, err
	}
	dir, err := s.recoveryDir(id)
	if err != nil {
		return FileRecovery{}, err
	}
	raw, err := json.Marshal(r)
	if err != nil {
		return FileRecovery{}, ErrState
	}
	tmp, err := os.CreateTemp(dir, ".recovery-*")
	if err != nil {
		return FileRecovery{}, ErrState
	}
	name := tmp.Name()
	defer os.Remove(name)
	_, we := tmp.Write(raw)
	se := tmp.Sync()
	ce := tmp.Close()
	if we != nil || se != nil || ce != nil {
		return FileRecovery{}, ErrState
	}
	if os.Link(name, filepath.Join(dir, fmt.Sprintf("%06d.json", r.Sequence))) != nil {
		return FileRecovery{}, ErrState
	}
	return r, nil
}

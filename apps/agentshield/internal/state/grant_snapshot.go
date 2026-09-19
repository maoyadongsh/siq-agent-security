package state

import (
	"errors"
	"path/filepath"
	"runtime"
	"strings"
	"sync"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// ErrGrantsBusy means a cooperating writer currently owns or is waiting for
// this state directory's Grant publication gate. An orphan prepare file is
// never sufficient evidence of an active writer.
var ErrGrantsBusy = errors.New("state: grant publication in progress")

type grantGate struct {
	mu   sync.RWMutex
	refs int
}

var grantGates = struct {
	sync.Mutex
	byDir map[string]*grantGate
}{byDir: map[string]*grantGate{}}

// Keep only gates with users, including callers waiting for a lock. Sharing by
// state root rather than Store pointer covers independently opened Stores.
func retainGrantGate(dir string) (*grantGate, func(), error) {
	if err := stateformat.ValidatePath(dir); err != nil {
		return nil, nil, err
	}
	key, err := filepath.Abs(dir)
	if err != nil {
		return nil, nil, err
	}
	if runtime.GOOS == "windows" {
		key = strings.ToLower(key)
	}
	grantGates.Lock()
	g := grantGates.byDir[key]
	if g == nil {
		g = &grantGate{}
		grantGates.byDir[key] = g
	}
	g.refs++
	grantGates.Unlock()
	return g, func() {
		grantGates.Lock()
		g.refs--
		if g.refs == 0 {
			delete(grantGates.byDir, key)
		}
		grantGates.Unlock()
	}, nil
}

func (s *Store) lockGrantPublication() (func(), error) {
	g, release, err := retainGrantGate(s.Dir)
	if err != nil {
		return nil, err
	}
	g.mu.Lock()
	return func() { g.mu.Unlock(); release() }, nil
}

func isGrantNamespace(subdir string) bool {
	namespace := filepath.Clean(subdir)
	return namespace == "grants" || runtime.GOOS == "windows" && strings.EqualFold(namespace, "grants")
}

// ListGrantsWithRevisions reads content and revision in one publication-free
// interval. It never waits for an active writer or recovers a torn commit.
// Cross-process exclusion remains the owning daemon's AcquireWriter contract.
func (s *Store) ListGrantsWithRevisions() ([]grant.Grant, map[string]int, error) {
	g, release, err := retainGrantGate(s.Dir)
	if err != nil {
		return nil, nil, err
	}
	defer release()
	if !g.mu.TryRLock() {
		return nil, nil, ErrGrantsBusy
	}
	defer g.mu.RUnlock()
	// Also catch an interrupted initial commit with no Grant file yet. No live
	// writer can be publishing here, so incomplete means recovery is required.
	pending, err := s.ListIncompleteCommits()
	if err != nil {
		return nil, nil, err
	}
	if len(pending) != 0 {
		return nil, nil, ErrIncompleteCommit
	}
	return s.listGrantsWithRevisions()
}

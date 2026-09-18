//go:build !windows

package privatefs

import "path/filepath"

// The stateformat caller keeps its existing POSIX ReadRegular implementation.
type ReadSnapshot struct {
	root   string
	closed bool
}

func OpenReadSnapshot(root string) (*ReadSnapshot, error) { return &ReadSnapshot{root: root}, nil }
func (s *ReadSnapshot) ReadFile(name string, limit int64) ([]byte, error) {
	if s == nil || s.closed || !filepath.IsLocal(name) {
		return nil, ErrPrivate
	}
	return ReadFile(filepath.Join(s.root, name), limit)
}
func (s *ReadSnapshot) Verify() error {
	if s == nil || s.closed {
		return ErrPrivate
	}
	return nil
}
func (s *ReadSnapshot) Close() error {
	if s != nil {
		s.closed = true
	}
	return nil
}

package privatefs

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// ReadSnapshot owns only one synchronous metadata check. No handle, bytes or
// successful permission result may be reused after Close or across calls.
type ReadSnapshot struct {
	root    string
	dirs    map[string]*os.File
	files   map[string]*os.File
	ambient []*os.File
	closed  bool
}

func snapshotShape(f *os.File, directory bool) error {
	var info syscall.ByHandleFileInformation
	if f == nil || syscall.GetFileInformationByHandle(syscall.Handle(f.Fd()), &info) != nil || info.FileAttributes&syscall.FILE_ATTRIBUTE_REPARSE_POINT != 0 || (info.FileAttributes&syscall.FILE_ATTRIBUTE_DIRECTORY != 0) != directory {
		return ErrPrivate
	}
	return nil
}

func snapshotOpen(path string, directory, private bool) (*os.File, error) {
	native, err := nativePath(path)
	if err != nil {
		return nil, err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return nil, ErrPrivate
	}
	access, flags, share := uint32(syscall.GENERIC_READ), uint32(syscall.FILE_FLAG_OPEN_REPARSE_POINT), uint32(syscall.FILE_SHARE_READ)
	if directory {
		// Include FILE_LIST_DIRECTORY: metadata-only handles do not establish
		// a write-sharing exclusion on Windows.
		access, flags = 0x81, flags|syscall.FILE_FLAG_BACKUP_SEMANTICS
		if private {
			access |= 0x20000
		}
	}
	// No DELETE sharing pins each ancestor. No WRITE sharing excludes both
	// metadata writers and directory reparse mutation during this check.
	h, err := syscall.CreateFile(name, access, share, nil, syscall.OPEN_EXISTING, flags, 0)
	if err != nil {
		return nil, privateError(err)
	}
	f := os.NewFile(uintptr(h), path)
	if private {
		err = checkFile(f, directory)
	} else {
		err = snapshotShape(f, directory)
	}
	if err != nil {
		_ = f.Close()
		return nil, err
	}
	return f, nil
}

// OpenReadSnapshot pins the complete ancestor chain before opening private
// descendants. Ambient ancestors retain their existing shape-only policy.
func OpenReadSnapshot(root string) (*ReadSnapshot, error) {
	if _, err := nativePath(root); err != nil {
		return nil, err
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, ErrPrivate
	}
	s := &ReadSnapshot{root: abs, dirs: map[string]*os.File{}, files: map[string]*os.File{}}
	var paths []string
	for p := abs; ; p = filepath.Dir(p) {
		paths = append(paths, p)
		if p == filepath.Dir(p) {
			break
		}
	}
	for i := len(paths) - 1; i >= 0; i-- {
		p := paths[i]
		f, err := snapshotOpen(p, true, p == abs)
		if err != nil {
			_ = s.Close()
			return nil, err
		}
		if p == abs {
			s.dirs[p] = f
		} else {
			s.ambient = append(s.ambient, f)
		}
	}
	return s, nil
}

func (s *ReadSnapshot) privateParent(name string) (string, error) {
	if s == nil || s.closed || name == "" || !filepath.IsLocal(name) || filepath.Clean(name) != name {
		return "", ErrPrivate
	}
	for _, part := range strings.FieldsFunc(name, func(r rune) bool { return r == '/' || r == '\\' }) {
		if part == "." || part == ".." {
			return "", ErrPrivate
		}
	}
	path := filepath.Join(s.root, name)
	if err := s.PinDirectory(filepath.Dir(name)); err != nil {
		return "", err
	}
	return path, nil
}

// PinDirectory distinguishes an absent record from an invalid/missing record
// directory. It does not create directories or repair their permissions.
func (s *ReadSnapshot) PinDirectory(name string) error {
	if s == nil || s.closed || name == "" || !filepath.IsLocal(name) || filepath.Clean(name) != name {
		return ErrPrivate
	}
	if name == "." {
		return nil // The private root is already pinned by OpenReadSnapshot.
	}
	current := s.root
	for _, part := range strings.Split(name, string(filepath.Separator)) {
		current = filepath.Join(current, part)
		if s.dirs[current] != nil {
			continue
		}
		f, err := snapshotOpen(current, true, true)
		if err != nil {
			return err
		}
		s.dirs[current] = f
	}
	return nil
}

func (s *ReadSnapshot) ReadFile(name string, limit int64) ([]byte, error) {
	if limit <= 0 {
		return nil, ErrPrivate
	}
	path, err := s.privateParent(name)
	if err != nil {
		return nil, err
	}
	f := s.files[path]
	if f == nil {
		f, err = snapshotOpen(path, false, true)
		if err != nil {
			return nil, err
		}
		s.files[path] = f
	}
	before, err := f.Stat()
	if err != nil || before.Size() > limit {
		return nil, ErrPrivate
	}
	if _, err = f.Seek(0, io.SeekStart); err != nil {
		return nil, ErrPrivate
	}
	raw, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, ErrPrivate
	}
	after, err := f.Stat()
	if err != nil || int64(len(raw)) > limit || !os.SameFile(before, after) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) || checkFile(f, false) != nil {
		return nil, ErrPrivate
	}
	return raw, nil
}

// Verify rereads live descriptor/shape facts; it never relies on the initial
// permission result, including for a directory that was reused by sibling reads.
func (s *ReadSnapshot) Verify() error {
	if s == nil || s.closed {
		return ErrPrivate
	}
	for _, f := range s.ambient {
		if snapshotShape(f, true) != nil {
			return ErrPrivate
		}
	}
	for _, f := range s.dirs {
		if checkFile(f, true) != nil {
			return ErrPrivate
		}
	}
	for _, f := range s.files {
		if checkFile(f, false) != nil {
			return ErrPrivate
		}
	}
	return nil
}

func (s *ReadSnapshot) Close() error {
	if s == nil || s.closed {
		return nil
	}
	s.closed = true
	var first error
	closeFile := func(f *os.File) {
		if err := f.Close(); err != nil && first == nil {
			first = err
		}
	}
	for _, f := range s.files {
		closeFile(f)
	}
	for _, f := range s.dirs {
		closeFile(f)
	}
	for i := len(s.ambient) - 1; i >= 0; i-- {
		closeFile(s.ambient[i])
	}
	return first
}

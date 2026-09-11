package skillimport

import (
	"context"
	"os"
	"path/filepath"
)

// InstallationSnapshot pins a fully validated import for bounded file reads.
// It is read-only: callers must separately authorize, publish and verify any
// installation, and must call Verify after reading the batch.
type InstallationSnapshot struct {
	store  *Store
	record Record
	files  map[string]File
}

func cloneRecord(record Record) Record {
	record.Files = append([]File{}, record.Files...)
	record.Directories = append([]string{}, record.Directories...)
	if record.Remote != nil {
		remote := *record.Remote
		record.Remote = &remote
	}
	return record
}

// OpenInstallationSnapshot verifies the entire candidate before pinning its
// signed manifest. Returned metadata cannot broaden the handle's read scope.
func (s *Store) OpenInstallationSnapshot(ctx context.Context, id string) (*InstallationSnapshot, error) {
	record, _, err := s.Load(ctx, id)
	if err != nil {
		return nil, err
	}
	snapshot := &InstallationSnapshot{store: s, record: cloneRecord(*record), files: make(map[string]File, len(record.Files))}
	for _, file := range record.Files {
		snapshot.files[file.Path] = file
	}
	return snapshot, nil
}
func (s *InstallationSnapshot) Metadata() Record { return cloneRecord(s.record) }

// ReadFile checks this exact manifest member, including its executable bit.
// It does not rescan unrelated files or revalidate the current Grant.
func (s *InstallationSnapshot) ReadFile(ctx context.Context, relative string) ([]byte, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	file, ok := s.files[relative]
	if !ok || !validPath(relative) {
		return nil, ErrInvalid
	}
	path := filepath.Join(s.store.blob(s.record.ImportID), "payload", filepath.FromSlash(relative))
	if err := checkDirs(filepath.Dir(path)); err != nil {
		return nil, err
	}
	raw, info, err := readRegular(ctx, path, maxFileBytes)
	if err != nil {
		return nil, err
	}
	current, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, current) || !current.Mode().IsRegular() || current.Mode() != info.Mode() || current.Size() != info.Size() || !current.ModTime().Equal(info.ModTime()) ||
		int64(len(raw)) != file.Bytes || sum(raw) != file.SHA256 || (info.Mode().Perm()&0111 != 0) != file.Executable {
		return nil, ErrChanged
	}
	return raw, nil
}

// Verify rechecks all candidate files, analysis and signed metadata. It must be
// used after a batch; successful individual reads are not whole-tree evidence.
func (s *InstallationSnapshot) Verify(ctx context.Context) error {
	record, _, err := s.store.Load(ctx, s.record.ImportID)
	if err != nil {
		return err
	}
	if record.Signature != s.record.Signature {
		return ErrChanged
	}
	return nil
}

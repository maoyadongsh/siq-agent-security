package skillimport

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var installStageID = regexp.MustCompile(`^sip-[a-f0-9]{64}$`)
var updateStageID = regexp.MustCompile(`^sup-[a-f0-9]{64}$`)

// Installation copies are confined to the private staging namespace. This API
// cannot publish into a platform directory or overwrite an existing snapshot.
func (s *Store) installationCopyPath(path string) bool {
	return s.privateCopyPath(path, "stages", installStageID)
}
func (s *Store) privateCopyPath(path, namespace string, pattern *regexp.Regexp) bool {
	base := filepath.Join(filepath.Dir(s.dir), "skill-installations", namespace)
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return false
	}
	rel, err := filepath.Rel(base, path)
	if err != nil {
		return false
	}
	parts := strings.Split(filepath.ToSlash(rel), "/")
	return len(parts) == 2 && pattern.MatchString(parts[0]) && parts[1] == "payload"
}
func (s *Store) CopyForInstallation(ctx context.Context, id, target string) (*Record, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !s.installationCopyPath(target) {
		return nil, ErrInvalid
	}
	return s.copyPrivate(ctx, id, target)
}

// CopyForUpdate prepares an independent candidate only in the private update namespace.
func (s *Store) CopyForUpdate(ctx context.Context, id, target string) (*Record, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !s.privateCopyPath(target, "update-stages", updateStageID) {
		return nil, ErrInvalid
	}
	return s.copyPrivate(ctx, id, target)
}
func (s *Store) copyPrivate(ctx context.Context, id, target string) (*Record, error) {
	if checkDirs(target) != nil {
		return nil, ErrInvalid
	}
	dir, err := os.Open(target)
	if err != nil {
		return nil, ErrInvalid
	}
	names, err := dir.Readdirnames(1)
	dir.Close()
	if len(names) != 0 {
		return nil, ErrConflict
	}
	// Readdirnames returns io.EOF for an empty directory; other errors are not emptiness.
	if err != nil && err != io.EOF {
		return nil, ErrUnavailable
	}
	record, _, err := s.Load(ctx, id)
	if err != nil {
		return nil, err
	}
	copied, _, err := directoryTree(ctx, filepath.Join(s.blob(id), "payload"), target, false)
	if err != nil {
		return nil, err
	}
	digest, err := copied.digest()
	if err != nil || digest != record.ArtifactDigest {
		return nil, ErrChanged
	}
	current, _, err := s.Load(ctx, id)
	if err != nil {
		return nil, err
	}
	if current.Signature != record.Signature {
		return nil, ErrChanged
	}
	if err := s.verifyPrivateCopy(ctx, id, target); err != nil {
		return nil, err
	}
	return record, nil
}
func (s *Store) VerifyInstallationCopy(ctx context.Context, id, target string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if !s.installationCopyPath(target) {
		return ErrInvalid
	}
	return s.verifyPrivateCopy(ctx, id, target)
}
func (s *Store) VerifyUpdateCopy(ctx context.Context, id, target string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if !s.privateCopyPath(target, "update-stages", updateStageID) {
		return ErrInvalid
	}
	return s.verifyPrivateCopy(ctx, id, target)
}
func (s *Store) verifyPrivateCopy(ctx context.Context, id, target string) error {
	record, _, err := s.Load(ctx, id)
	if err != nil {
		return err
	}
	actual, _, err := directoryTree(ctx, target, "", false)
	if err != nil {
		return err
	}
	digest, err := actual.digest()
	if err != nil || digest != record.ArtifactDigest {
		return ErrChanged
	}
	return nil
}

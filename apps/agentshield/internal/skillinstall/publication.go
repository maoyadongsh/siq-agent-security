package skillinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"sort"
	"strings"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
)

type contextRead struct {
	ctx    context.Context
	reader io.Reader
}

func (r contextRead) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}
func readBounded(ctx context.Context, path string, limit int64) ([]byte, os.FileInfo, error) {
	return readBoundedWith(ctx, path, limit, fileopen.Regular)
}

func readPrivateBounded(ctx context.Context, path string, limit int64) ([]byte, os.FileInfo, error) {
	return readBoundedWith(ctx, path, limit, openPrivateMetadata)
}

func readBoundedWith(ctx context.Context, path string, limit int64, open func(string) (*os.File, error)) ([]byte, os.FileInfo, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	if err := checkDirectories(filepath.Dir(path)); err != nil {
		return nil, nil, err
	}
	before, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil, nil, ErrNotFound
	}
	if err != nil || !before.Mode().IsRegular() {
		return nil, nil, ErrChanged
	}
	if before.Size() > limit {
		return nil, nil, ErrLimit
	}
	f, err := open(path)
	if err != nil {
		return nil, nil, ErrChanged
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(before, opened) {
		return nil, nil, ErrChanged
	}
	raw, err := io.ReadAll(io.LimitReader(contextRead{ctx, f}, limit+1))
	if err != nil {
		return nil, nil, err
	}
	after, err := os.Lstat(path)
	if err != nil || !os.SameFile(before, after) || int64(len(raw)) != before.Size() || after.Size() != before.Size() || after.Mode() != before.Mode() || !after.ModTime().Equal(before.ModTime()) {
		return nil, nil, ErrChanged
	}
	return raw, before, nil
}
func sameDocument(a, b any) bool {
	ad, e := document(a, true)
	if e != nil {
		return false
	}
	bd, e := document(b, true)
	if e != nil {
		return false
	}
	ar, e := canon.Marshal(ad)
	if e != nil {
		return false
	}
	br, e := canon.Marshal(bd)
	return e == nil && bytes.Equal(ar, br)
}
func (s *Store) readSigned(ctx context.Context, path string, out any) error {
	if err := s.checkPrivateMetadataRoot(); err != nil {
		return err
	}
	raw, _, err := readPrivateBounded(ctx, path, 4<<20)
	if err != nil {
		return err
	}
	return s.verifySignedMetadata(raw, out)
}

// Host-side owner markers can be linked to the operation pool. Their existing
// signature and ownership checks must not become private single-link reads.
func (s *Store) readTargetOwner(ctx context.Context, path string, out any) error {
	raw, _, err := readBounded(ctx, path, 4<<20)
	if err != nil {
		return err
	}
	return s.verifySignedMetadata(raw, out)
}

func (s *Store) verifySignedMetadata(raw []byte, out any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(out); err != nil {
		return ErrChanged
	}
	doc, err := document(out, true)
	if err != nil {
		return ErrChanged
	}
	canonical, err := canon.Marshal(doc)
	if err != nil || !bytes.Equal(raw, canonical) {
		return ErrChanged
	}
	sig, ok := doc["signature"].(string)
	if !ok || !signaturePattern.MatchString(sig) {
		return ErrChanged
	}
	delete(doc, "signature")
	if !signing.VerifyCanonical(s.key.Public(), doc, sig) {
		return ErrChanged
	}
	return nil
}
func publishDocument(path string, value any) error {
	if err := privateDirectory(filepath.Dir(path)); err != nil {
		return err
	}
	doc, err := document(value, true)
	if err != nil {
		return ErrUnavailable
	}
	raw, err := canon.Marshal(doc)
	if err != nil {
		return ErrUnavailable
	}
	return publishPrivateMetadata(path, raw, ".operation-*")
}
func relativeValid(path string) bool {
	if path == "" || len(path) > 512 || !utf8.ValidString(path) || strings.ContainsAny(path, "\\:\x00") || filepath.IsAbs(filepath.FromSlash(path)) {
		return false
	}
	parts := strings.Split(path, "/")
	if len(parts) > 16 {
		return false
	}
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || len(part) > 128 || strings.EqualFold(part, ownerName) {
			return false
		}
	}
	return true
}
func manifestValid(c Claim) bool {
	if len(c.Files) < 1 || len(c.Files) > 2000 || len(c.Directories) > 2000 || len(c.Files) != c.Plan.FileCount || !sort.StringsAreSorted(c.Directories) {
		return false
	}
	seen := map[string]bool{}
	dirs := map[string]bool{"": true}
	for _, dir := range c.Directories {
		if !relativeValid(dir) || seen[strings.ToLower(dir)] {
			return false
		}
		seen[strings.ToLower(dir)] = true
		dirs[dir] = true
	}
	var total int64
	previous := ""
	for _, file := range c.Files {
		if !relativeValid(file.Path) || file.Path <= previous || seen[strings.ToLower(file.Path)] || file.Bytes < 0 || file.Bytes > 8<<20 || !digestPattern.MatchString(file.SHA256) {
			return false
		}
		previous = file.Path
		seen[strings.ToLower(file.Path)] = true
		total += file.Bytes
		parent := filepath.ToSlash(filepath.Dir(filepath.FromSlash(file.Path)))
		if parent == "." {
			parent = ""
		}
		if !dirs[parent] {
			return false
		}
	}
	for _, dir := range c.Directories {
		parent := filepath.ToSlash(filepath.Dir(filepath.FromSlash(dir)))
		if parent == "." {
			parent = ""
		}
		if !dirs[parent] {
			return false
		}
	}
	if total > 64<<20 || total != c.Plan.TotalBytes {
		return false
	}
	doc, err := document(map[string]any{"directories": c.Directories, "files": c.Files}, true)
	if err != nil {
		return false
	}
	raw, err := canon.Marshal(doc)
	return err == nil && hash(raw) == c.Plan.Source.ArtifactDigest
}
func opaque(pool, kind string, index int) string {
	return filepath.Join(pool, fmt.Sprintf("%s-%04d", kind, index))
}
func writeOpaque(path string, raw []byte, executable bool) error {
	if err := checkDirectories(filepath.Dir(path)); err != nil {
		return err
	}
	mode := os.FileMode(0600)
	if executable {
		mode = 0700
	}
	f, err := statefs.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		if os.IsExist(err) {
			return ErrConflict
		}
		return ErrUnavailable
	}
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnavailable
	}
	return nil
}
func (s *Store) ownerBytes(c *Claim, relative string) ([]byte, error) {
	owner := Owner{SchemaVersion: "local-skill-install-owner/v1", InstallID: c.InstallID, ClaimSignature: c.Signature, RelativeDirectory: relative}
	doc, err := document(owner, false)
	if err != nil {
		return nil, err
	}
	owner.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, err
	}
	doc, err = document(owner, true)
	if err != nil {
		return nil, err
	}
	return canon.Marshal(doc)
}
func (s *Store) ownerMatches(ctx context.Context, c *Claim, destination, pool, relative string, index int) error {
	marker := filepath.Join(destination, filepath.FromSlash(relative), ownerName)
	var owner Owner
	if err := s.readTargetOwner(ctx, marker, &owner); err != nil {
		return err
	}
	if owner.SchemaVersion != "local-skill-install-owner/v1" || owner.InstallID != c.InstallID || owner.ClaimSignature != c.Signature || owner.RelativeDirectory != relative {
		return ErrChanged
	}
	a, err := os.Lstat(marker)
	if err != nil {
		return ErrChanged
	}
	if err := checkDirectories(pool); err != nil {
		return err
	}
	b, err := os.Lstat(opaque(pool, "d", index))
	if err != nil || !b.Mode().IsRegular() {
		return ErrChanged
	}
	if c.Plan.Platform == "openclaw" {
		targetRaw, _, targetErr := readBounded(ctx, marker, 1<<20)
		poolRaw, _, poolErr := readBounded(ctx, opaque(pool, "d", index), 1<<20)
		if targetErr != nil || poolErr != nil || !bytes.Equal(targetRaw, poolRaw) {
			return ErrChanged
		}
	} else if !os.SameFile(a, b) {
		return ErrChanged
	}
	return nil
}
func ownedFile(ctx context.Context, destination, pool string, file skillimport.File, index int, platform string) error {
	path := filepath.Join(destination, filepath.FromSlash(file.Path))
	raw, info, err := readBounded(ctx, path, 8<<20)
	if err != nil {
		return err
	}
	if int64(len(raw)) != file.Bytes || hash(raw) != file.SHA256 || (info.Mode().Perm()&0111 != 0) != file.Executable {
		return ErrChanged
	}
	if err := checkDirectories(pool); err != nil {
		return err
	}
	other, err := os.Lstat(opaque(pool, "f", index))
	if err != nil || !other.Mode().IsRegular() {
		return ErrChanged
	}
	if platform == "openclaw" {
		poolRaw, poolInfo, poolErr := readBounded(ctx, opaque(pool, "f", index), 8<<20)
		if poolErr != nil || int64(len(poolRaw)) != file.Bytes || hash(poolRaw) != file.SHA256 || (poolInfo.Mode().Perm()&0111 != 0) != file.Executable {
			return ErrChanged
		}
	} else if !os.SameFile(info, other) {
		return ErrChanged
	}
	return nil
}

func publishOpaque(ctx context.Context, source, destination string, executable, hardlink bool) error {
	if hardlink {
		if err := statefs.Link(source, destination); err != nil {
			if os.IsExist(err) {
				return ErrConflict
			}
			return ErrUnavailable
		}
		return nil
	}
	raw, _, err := readBounded(ctx, source, 8<<20)
	if err != nil {
		return err
	}
	return writeOpaque(destination, raw, executable)
}
func (s *Store) publishTarget(ctx context.Context, c *Claim, snapshot *skillimport.InstallationSnapshot) error {
	destination, pool, err := s.destination(ctx, c.Plan)
	if err != nil {
		return err
	}
	if err := privateDirectory(filepath.Dir(pool)); err != nil {
		return err
	}
	if err := statefs.Mkdir(pool, 0700); err != nil {
		if os.IsExist(err) {
			return ErrConflict
		}
		return ErrUnavailable
	}
	dirs := append([]string{""}, c.Directories...)
	// OpenClaw rejects Skill payloads with a link count greater than one. Its
	// target files therefore use exclusive independent publication and retain
	// ownership through the signed marker plus full content readback. Hermes
	// keeps the stronger inode-linked pool proof for backward compatibility.
	hardlinkTarget := c.Plan.Platform != "openclaw"
	for i, dir := range dirs {
		if err := ctx.Err(); err != nil {
			return err
		}
		raw, err := s.ownerBytes(c, dir)
		if err != nil {
			return ErrUnavailable
		}
		if err := writeOpaque(opaque(pool, "d", i), raw, false); err != nil {
			return err
		}
	}
	for i, file := range c.Files {
		raw, err := snapshot.ReadFile(ctx, file.Path)
		if err != nil {
			return sourceError(ctx, err)
		}
		if err := writeOpaque(opaque(pool, "f", i), raw, file.Executable); err != nil {
			return err
		}
	}
	if err := snapshot.Verify(ctx); err != nil {
		return sourceError(ctx, err)
	}
	if _, err := s.Load(ctx, c.Plan.PlanID); err != nil {
		return err
	}
	if err := s.boundary("spooled"); err != nil {
		return ErrUnavailable
	}
	if err := s.checkAuthority(ctx, c.Plan, true); err != nil {
		return err
	}
	if current, currentPool, err := s.destination(ctx, c.Plan); err != nil || current != destination || currentPool != pool {
		return ErrChanged
	}
	if _, err := targetPath(Target{Root: filepath.Dir(filepath.Dir(destination))}, c.Plan.DirectoryName); err != nil {
		return err
	}
	if err := statefs.Mkdir(filepath.Dir(destination), 0700); err != nil && !os.IsExist(err) {
		return ErrUnavailable
	}
	if err := checkDirectories(filepath.Dir(destination)); err != nil {
		return err
	}
	dirIndices := map[string]int{}
	for i, dir := range dirs {
		dirIndices[dir] = i
	}
	for i, dir := range dirs {
		if err := ctx.Err(); err != nil {
			return err
		}
		path := filepath.Join(destination, filepath.FromSlash(dir))
		if err := checkDirectories(filepath.Dir(path)); err != nil {
			return err
		}
		if i > 0 {
			parent := filepath.ToSlash(filepath.Dir(filepath.FromSlash(dir)))
			if parent == "." {
				parent = ""
			}
			if err := s.ownerMatches(ctx, c, destination, pool, parent, dirIndices[parent]); err != nil {
				return err
			}
		}
		if err := statefs.Mkdir(path, 0700); err != nil {
			if os.IsExist(err) {
				return ErrConflict
			}
			return ErrUnavailable
		}
		created, err := os.Lstat(path)
		if err != nil {
			return ErrUnavailable
		}
		// The current process can remove its unchanged empty directory when
		// marker publication fails. A process crash loses that evidence, so
		// restart recovery never guesses ownership of an unmarked directory.
		markErr := s.boundary("directory_created:" + dir)
		if markErr == nil {
			markErr = publishOpaque(ctx, opaque(pool, "d", i), filepath.Join(path, ownerName), false, hardlinkTarget)
		}
		if markErr != nil {
			current, readErr := os.Lstat(path)
			if readErr == nil && current.IsDir() && current.Mode()&os.ModeSymlink == 0 && os.SameFile(created, current) {
				_ = statefs.Remove(path) // only an empty directory; never RemoveAll
			}
			return ErrUnavailable
		}
	}
	indices := make([]int, len(c.Files))
	for i := range indices {
		indices[i] = i
	}
	rank := func(path string) int {
		if path == "SKILL.md" {
			return 2
		}
		if filepath.Base(path) == "SKILL.md" {
			return 1
		}
		return 0
	}
	sort.SliceStable(indices, func(i, j int) bool { return rank(c.Files[indices[i]].Path) < rank(c.Files[indices[j]].Path) })
	for _, i := range indices {
		if err := s.checkAuthority(ctx, c.Plan, false); err != nil {
			return err
		}
		file := c.Files[i]
		path := filepath.Join(destination, filepath.FromSlash(file.Path))
		if err := checkDirectories(filepath.Dir(path)); err != nil {
			return err
		}
		parent := filepath.ToSlash(filepath.Dir(filepath.FromSlash(file.Path)))
		if parent == "." {
			parent = ""
		}
		if err := s.ownerMatches(ctx, c, destination, pool, parent, dirIndices[parent]); err != nil {
			return err
		}
		raw, info, err := readBounded(ctx, opaque(pool, "f", i), 8<<20)
		if err != nil || int64(len(raw)) != file.Bytes || hash(raw) != file.SHA256 || (info.Mode().Perm()&0111 != 0) != file.Executable {
			return ErrChanged
		}
		if err := publishOpaque(ctx, opaque(pool, "f", i), path, file.Executable, hardlinkTarget); err != nil {
			return err
		}
		if err := s.boundary("file_published:" + file.Path); err != nil {
			return ErrUnavailable
		}
	}
	if err := snapshot.Verify(ctx); err != nil {
		return sourceError(ctx, err)
	}
	if err := s.imports.VerifyInstallationCopy(ctx, c.Plan.Source.ImportID, filepath.Join(s.stage(c.Plan.PlanID), "payload")); err != nil {
		return sourceError(ctx, err)
	}
	if err := s.boundary("before_readback"); err != nil {
		return ErrUnavailable
	}
	_, err = s.verifyTarget(ctx, c, true)
	return err
}

// verifyTarget accepts only original manifest members and verified ownership
// markers. Partial mode supports rollback of a prefix after interruption.
func (s *Store) verifyTarget(ctx context.Context, c *Claim, complete bool) ([]string, error) {
	destination, pool, err := s.destination(ctx, c.Plan)
	if err != nil {
		return nil, err
	}
	if _, err := os.Lstat(destination); os.IsNotExist(err) {
		if complete {
			return nil, ErrChanged
		}
		return []string{}, nil
	} else if err != nil {
		return nil, ErrChanged
	}
	if err := checkDirectories(destination); err != nil {
		return nil, err
	}
	dirs := append([]string{""}, c.Directories...)
	dirIndex := map[string]int{}
	fileIndex := map[string]int{}
	for i, dir := range dirs {
		dirIndex[dir] = i
	}
	for i, file := range c.Files {
		fileIndex[file.Path] = i
	}
	present := []string{}
	visitedDirs, visitedFiles := 0, 0
	var visit func(string) error
	visit = func(relative string) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		index, ok := dirIndex[relative]
		if !ok {
			return ErrChanged
		}
		if err := s.ownerMatches(ctx, c, destination, pool, relative, index); err != nil {
			return err
		}
		visitedDirs++
		directory := filepath.Join(destination, filepath.FromSlash(relative))
		if err := checkDirectories(directory); err != nil {
			return err
		}
		f, err := statefs.Open(directory)
		if err != nil {
			return ErrChanged
		}
		names, err := f.Readdirnames(4002)
		f.Close()
		if err != nil && err != io.EOF {
			return ErrChanged
		}
		if len(names) > 4001 {
			return ErrLimit
		}
		for _, name := range names {
			if name == ownerName {
				continue
			}
			path := name
			if relative != "" {
				path = relative + "/" + name
			}
			if i, ok := fileIndex[path]; ok {
				if err := ownedFile(ctx, destination, pool, c.Files[i], i, c.Plan.Platform); err != nil {
					return err
				}
				visitedFiles++
				present = append(present, path)
			} else if _, ok := dirIndex[path]; ok {
				if err := visit(path); err != nil {
					return err
				}
			} else {
				return ErrChanged
			}
		}
		return nil
	}
	if err := visit(""); err != nil {
		return nil, err
	}
	if complete && (visitedDirs != len(dirs) || visitedFiles != len(c.Files)) {
		return nil, ErrChanged
	}
	return present, nil
}
func (s *Store) rollbackTarget(ctx context.Context, c *Claim) error {
	return s.cleanupTarget(ctx, c, "")
}

func (s *Store) cleanupTarget(ctx context.Context, c *Claim, prefix string) error {
	files, err := s.verifyTarget(ctx, c, false)
	if err != nil {
		return err
	}
	destination, pool, err := s.destination(ctx, c.Plan)
	if err != nil {
		return err
	}
	if _, err := os.Lstat(destination); os.IsNotExist(err) {
		return nil
	}
	index := map[string]int{}
	for i, file := range c.Files {
		index[file.Path] = i
	}
	sort.SliceStable(files, func(i, j int) bool {
		return filepath.Base(files[i]) == "SKILL.md" && filepath.Base(files[j]) != "SKILL.md"
	})
	for _, path := range files {
		i := index[path]
		if err := ownedFile(ctx, destination, pool, c.Files[i], i, c.Plan.Platform); err != nil {
			return err
		}
		if err := statefs.Remove(filepath.Join(destination, filepath.FromSlash(path))); err != nil {
			return ErrChanged
		}
		if prefix != "" {
			if err := s.boundary(prefix + "file_removed:" + path); err != nil {
				return ErrUnavailable
			}
		}
	}
	dirs := append([]string{""}, c.Directories...)
	for i := len(dirs) - 1; i >= 0; i-- {
		directory := filepath.Join(destination, filepath.FromSlash(dirs[i]))
		if _, err := os.Lstat(directory); os.IsNotExist(err) {
			continue
		}
		if err := s.ownerMatches(ctx, c, destination, pool, dirs[i], i); err != nil {
			return err
		}
		f, err := statefs.Open(directory)
		if err != nil {
			return ErrChanged
		}
		names, err := f.Readdirnames(2)
		f.Close()
		if err != nil && err != io.EOF {
			return ErrChanged
		}
		if len(names) != 1 || names[0] != ownerName {
			return ErrChanged
		}
		if err := statefs.Remove(filepath.Join(directory, ownerName)); err != nil {
			return ErrChanged
		}
		if prefix != "" {
			if err := s.boundary(prefix + "owner_removed:" + dirs[i]); err != nil {
				return ErrUnavailable
			}
		}
		if err := statefs.Remove(directory); err != nil {
			return ErrChanged
		}
	}
	return nil
}

func reservedMetadata(path string) bool {
	for _, part := range strings.Split(path, "/") {
		if strings.EqualFold(part, ownerName) {
			return true
		}
	}
	return false
}

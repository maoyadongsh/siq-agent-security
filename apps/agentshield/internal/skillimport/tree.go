// Package skillimport fixes installation candidates before admission or approval.
// It never executes package contents and never installs into a platform directory.
package skillimport

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/fileopen"
)

const maxFiles = 2000
const maxDirs = 2000
const maxDepth = 16
const maxFileBytes int64 = 8 << 20
const maxTotalBytes int64 = 64 << 20
const maxArchiveBytes int64 = 32 << 20

var ErrInvalid = errors.New("skill_import_invalid")
var ErrLimit = errors.New("skill_import_limit")
var ErrChanged = errors.New("skill_import_changed")
var ErrConflict = errors.New("skill_import_conflict")
var ErrUnavailable = errors.New("skill_import_unavailable")
var ErrNotFound = errors.New("skill_import_not_found")

type File struct {
	Path       string `json:"path"`
	SHA256     string `json:"sha256"`
	Bytes      int64  `json:"bytes"`
	Executable bool   `json:"executable"`
}
type tree struct {
	Directories []string `json:"directories"`
	Files       []File   `json:"files"`
}

func emptyTree() tree { return tree{Directories: []string{}, Files: []File{}} }
func (t *tree) finish() {
	sort.Strings(t.Directories)
	sort.Slice(t.Files, func(i, j int) bool { return t.Files[i].Path < t.Files[j].Path })
}
func (t tree) digest() (string, error) {
	raw, err := json.Marshal(t)
	if err != nil {
		return "", ErrInvalid
	}
	value, err := canon.Decode(raw)
	if err != nil {
		return "", ErrInvalid
	}
	canonical, err := canon.Marshal(value)
	if err != nil {
		return "", ErrInvalid
	}
	return sum(canonical), nil
}
func sum(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func validPath(path string) bool {
	if path == "" || len(path) > 512 || !utf8.ValidString(path) || strings.ContainsAny(path, "\\:<>|?*\x00") {
		return false
	}
	parts := strings.Split(path, "/")
	if len(parts) > maxDepth {
		return false
	}
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || len(part) > 128 || strings.HasSuffix(part, ".") || strings.HasSuffix(part, " ") || strings.IndexFunc(part, func(r rune) bool { return unicode.IsControl(r) || unicode.Is(unicode.Cf, r) }) >= 0 {
			return false
		}
		base := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		if base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" || base == "CONIN$" || base == "CONOUT$" {
			return false
		}
		if (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && len([]rune(base)) == 4 && strings.ContainsRune("123456789¹²³", []rune(base)[3]) {
			return false
		}
	}
	return true
}
func gitMetadata(path string) bool {
	for _, part := range strings.Split(path, "/") {
		if strings.EqualFold(part, ".git") {
			return true
		}
	}
	return false
}
func checkDirs(path string) error {
	for {
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return ErrInvalid
		}
		parent := filepath.Dir(path)
		if parent == path {
			return nil
		}
		path = parent
	}
}

type contextReader struct {
	ctx context.Context
	io.Reader
}

func (r contextReader) Read(b []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.Reader.Read(b)
}

func readRegular(ctx context.Context, path string, limit int64) ([]byte, os.FileInfo, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, nil, ErrUnavailable
	}
	if !info.Mode().IsRegular() {
		return nil, nil, ErrInvalid
	}
	if info.Size() > limit {
		return nil, nil, ErrLimit
	}
	f, err := fileopen.Regular(path)
	if err != nil {
		return nil, nil, ErrUnavailable
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return nil, nil, ErrChanged
	}
	raw, err := io.ReadAll(io.LimitReader(contextReader{ctx, f}, limit+1))
	if err != nil {
		if ctx.Err() != nil {
			return nil, nil, ctx.Err()
		}
		return nil, nil, ErrUnavailable
	}
	if int64(len(raw)) > limit {
		return nil, nil, ErrLimit
	}
	after, err := f.Stat()
	if err != nil || after.Size() != info.Size() || int64(len(raw)) != info.Size() || !after.ModTime().Equal(info.ModTime()) || after.Mode() != info.Mode() {
		return nil, nil, ErrChanged
	}
	return raw, info, nil
}
func writeFile(path string, raw []byte, executable bool) error {
	mode := os.FileMode(0600)
	if executable {
		mode = 0700
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
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

// directoryTree copies independent files if target is nonempty; otherwise it
// hashes a bounded readback. Links and special files never become payload files.
func directoryTree(ctx context.Context, root, target string, skipGit bool) (tree, bool, error) {
	out := emptyTree()
	if err := checkDirs(root); err != nil {
		return out, false, err
	}
	if target != "" {
		rel, err := filepath.Rel(root, target)
		if err != nil || rel == "." || (!strings.HasPrefix(rel, ".."+string(filepath.Separator)) && rel != "..") {
			return out, false, ErrInvalid
		}
	}
	var total int64
	excluded := false
	seen := map[string]bool{}
	var walk func(string) error
	walk = func(rel string) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		path := root
		if rel != "" {
			path = filepath.Join(root, filepath.FromSlash(rel))
		}
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return ErrInvalid
		}
		dir, err := os.Open(path)
		if err != nil {
			return ErrUnavailable
		}
		opened, err := dir.Stat()
		if err != nil || !os.SameFile(info, opened) {
			dir.Close()
			return ErrChanged
		}
		names, err := dir.Readdirnames(maxFiles + maxDirs + 1)
		dir.Close()
		if err != nil && err != io.EOF {
			return ErrUnavailable
		}
		if len(names) > maxFiles+maxDirs {
			return ErrLimit
		}
		sort.Strings(names)
		for _, name := range names {
			if err := ctx.Err(); err != nil {
				return err
			}
			child := name
			if rel != "" {
				child = rel + "/" + name
			}
			if skipGit && gitMetadata(child) {
				excluded = true
				continue
			}
			if !validPath(child) {
				return ErrInvalid
			}
			key := strings.ToLower(child)
			if seen[key] {
				return ErrInvalid
			}
			seen[key] = true
			source := filepath.Join(root, filepath.FromSlash(child))
			stat, err := os.Lstat(source)
			if err != nil {
				return ErrChanged
			}
			if stat.IsDir() && stat.Mode()&os.ModeSymlink == 0 {
				if len(out.Directories) >= maxDirs {
					return ErrLimit
				}
				out.Directories = append(out.Directories, child)
				if target != "" {
					if err = os.Mkdir(filepath.Join(target, filepath.FromSlash(child)), 0700); err != nil {
						return ErrUnavailable
					}
				}
				if err = walk(child); err != nil {
					return err
				}
				continue
			}
			if !stat.Mode().IsRegular() {
				return ErrInvalid
			}
			if len(out.Files) >= maxFiles {
				return ErrLimit
			}
			limit := maxFileBytes
			if maxTotalBytes-total < limit {
				limit = maxTotalBytes - total
			}
			raw, info, err := readRegular(ctx, source, limit)
			if err != nil {
				return err
			}
			total += int64(len(raw))
			executable := info.Mode().Perm()&0111 != 0
			if target != "" {
				if err = writeFile(filepath.Join(target, filepath.FromSlash(child)), raw, executable); err != nil {
					return err
				}
			}
			out.Files = append(out.Files, File{child, sum(raw), int64(len(raw)), executable})
		}
		return nil
	}
	err := walk("")
	out.finish()
	return out, excluded, err
}

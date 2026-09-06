package admission

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Limits mirror dev-spec §3.6.1. Exceeding any limit sets integrity.over_limit
// which the schema forces to quarantine.
type Limits struct {
	MaxFiles    int
	MaxDirs     int // 0 means DefaultLimits.MaxDirs; <0 disables dir budget
	MaxTotal    int64
	MaxFileScan int64 // files above this are hashed but not scanned (counted as binary)
	MaxDepth    int
	MaxFindings int
}

// DefaultLimits are the v1 ceilings.
var DefaultLimits = Limits{MaxFiles: 2000, MaxDirs: 2000, MaxTotal: 64 << 20, MaxFileScan: 8 << 20, MaxDepth: 16, MaxFindings: 500}

// FileEntry is one row of file_manifest.
type FileEntry struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}

type walked struct {
	files         []FileEntry
	contents      map[string][]byte // only files <= MaxFileScan
	executable    map[string]bool
	symlinkEscape bool
	overLimit     bool
	canceled      bool
	dirsSeen      int
	totalBytes    int64
}

var skipNames = map[string]bool{".git": true, "skill.oms.sig": true, "skill-manifest.json": true}

// ErrCanceled means the caller canceled enumeration before a complete scan.
var ErrCanceled = errors.New("admission: scan canceled")

// walk traverses root without following symlinks, enforcing Limits and
// detecting symlinks that resolve outside root. Budgets are checked during
// enumeration; reaching a limit returns a controlled over_limit result.
func walk(root string, lim Limits) (*walked, error) {
	return walkContext(context.Background(), root, lim)
}

func walkContext(ctx context.Context, root string, lim Limits) (*walked, error) {
	if lim.MaxFiles <= 0 || lim.MaxTotal <= 0 || lim.MaxFileScan < 0 || lim.MaxDepth <= 0 {
		return nil, errors.New("admission: invalid scan limits")
	}
	if lim.MaxDirs == 0 {
		lim.MaxDirs = DefaultLimits.MaxDirs
	}
	if ctx == nil {
		ctx = context.Background()
	}
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	realRoot, err := filepath.EvalSymlinks(absRoot)
	if err != nil {
		return nil, err
	}
	rootInfo, err := os.Stat(realRoot)
	if err != nil {
		return nil, err
	}
	if !rootInfo.IsDir() {
		return nil, errors.New("admission: scan root must be a directory")
	}
	w := &walked{contents: map[string][]byte{}, executable: map[string]bool{}}
	err = filepath.WalkDir(realRoot, func(p string, d fs.DirEntry, werr error) error {
		if err := ctx.Err(); err != nil {
			w.canceled = true
			return ErrCanceled
		}
		if werr != nil {
			return werr
		}
		rel, _ := filepath.Rel(realRoot, p)
		if rel == "." {
			return nil
		}
		if skipNames[d.Name()] {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.Count(rel, string(filepath.Separator)) >= lim.MaxDepth {
			w.overLimit = true
			return errOverLimit
		}
		if d.IsDir() {
			w.dirsSeen++
			if lim.MaxDirs > 0 && w.dirsSeen > lim.MaxDirs {
				w.overLimit = true
				return errOverLimit
			}
			return nil
		}
		if d.Type()&fs.ModeSymlink != 0 {
			target, err := filepath.EvalSymlinks(p)
			if err != nil {
				w.symlinkEscape = true // dangling links are treated as escapes (fail closed)
				return nil
			}
			if !strings.HasPrefix(target, realRoot+string(filepath.Separator)) && target != realRoot {
				w.symlinkEscape = true
				return nil
			}
			// in-root symlink: record the link itself, do not descend
			info, err := os.Stat(target)
			if err != nil || info.IsDir() {
				return nil
			}
			return w.addFile(rel, target, info, lim)
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		return w.addFile(rel, p, info, lim)
	})
	if errors.Is(err, ErrCanceled) {
		return w, ErrCanceled
	}
	if err != nil && !errors.Is(err, errOverLimit) {
		return nil, err
	}
	sort.Slice(w.files, func(i, j int) bool { return w.files[i].Path < w.files[j].Path })
	return w, nil
}

var errOverLimit = errors.New("over limit")

func (w *walked) addFile(rel, p string, info fs.FileInfo, lim Limits) error {
	if !info.Mode().IsRegular() {
		return errors.New("admission: non-regular file refused")
	}
	if len(w.files) >= lim.MaxFiles {
		w.overLimit = true
		return errOverLimit
	}
	remaining := lim.MaxTotal - w.totalBytes
	if info.Size() < 0 || info.Size() > remaining {
		w.overLimit = true
		return errOverLimit
	}
	posix := filepath.ToSlash(rel)
	// ADR-013: open without following a swapped symlink / blocking on FIFO
	// where the platform allows; always re-Stat the fd and require SameFile.
	f, err := openRegular(p)
	if err != nil {
		return err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil {
		return err
	}
	if !opened.Mode().IsRegular() {
		return errors.New("admission: non-regular file refused after open")
	}
	if !os.SameFile(info, opened) {
		return errors.New("admission: file changed while opening")
	}
	data, err := io.ReadAll(io.LimitReader(f, remaining))
	if err != nil {
		return err
	}
	var extra [1]byte
	n, err := f.Read(extra[:])
	if n != 0 {
		w.overLimit = true
		return errOverLimit
	}
	if err != io.EOF {
		if err != nil {
			return err
		}
		return errors.New("admission: file read did not terminate")
	}
	size := int64(len(data))
	w.totalBytes += size
	sum := sha256.Sum256(data)
	w.files = append(w.files, FileEntry{Path: posix, SHA256: hex.EncodeToString(sum[:]), Bytes: size})
	if size <= lim.MaxFileScan {
		w.contents[posix] = data
	}
	if info.Mode()&0o111 != 0 {
		w.executable[posix] = true
	}
	return nil
}

// HashDir returns the content_hash and manifest of a skill directory using the
// same traversal and limits as Admit (used by inventory for tool pinning).
func HashDir(root string, lim Limits) (string, []FileEntry, error) {
	hash, files, _, err := HashDirWithSkillMD(root, lim)
	return hash, files, err
}

// HashDirContext is HashDir with cooperative cancellation during enumeration.
func HashDirContext(ctx context.Context, root string, lim Limits) (string, []FileEntry, error) {
	hash, files, _, err := HashDirWithSkillMDContext(ctx, root, lim)
	return hash, files, err
}

// HashDirWithSkillMD returns the bounded SKILL.md bytes from the same traversal
// that produced the manifest. Inventory must not reopen an untrusted path after
// hashing it. Oversized SKILL.md files have no scannable metadata.
func HashDirWithSkillMD(root string, lim Limits) (string, []FileEntry, []byte, error) {
	return HashDirWithSkillMDContext(context.Background(), root, lim)
}

// HashDirWithSkillMDContext applies the same rules as HashDirWithSkillMD under ctx.
func HashDirWithSkillMDContext(ctx context.Context, root string, lim Limits) (string, []FileEntry, []byte, error) {
	if lim == (Limits{}) {
		lim = DefaultLimits
	}
	w, err := walkContext(ctx, root, lim)
	if err != nil {
		return "", nil, nil, err
	}
	if w.overLimit || w.symlinkEscape {
		return "", nil, nil, errors.New("admission: incomplete or out-of-scope tree cannot be hashed")
	}
	return contentHash(w.files), w.files, w.contents["SKILL.md"], nil
}

// contentHash implements spec §3.6.2:
// sha256( join( sorted( "<path>\n<sha256>\n<bytes>\n" ) ) ).
func contentHash(files []FileEntry) string {
	h := sha256.New()
	for _, f := range files { // files already sorted by path
		h.Write([]byte(f.Path + "\n" + f.SHA256 + "\n" + itoa64(f.Bytes) + "\n"))
	}
	return hex.EncodeToString(h.Sum(nil))
}

func itoa64(n int64) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

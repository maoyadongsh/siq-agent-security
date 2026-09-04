package admission

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
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
	MaxTotal    int64
	MaxFileScan int64 // files above this are hashed but not scanned (counted as binary)
	MaxDepth    int
	MaxFindings int
}

// DefaultLimits are the v1 ceilings.
var DefaultLimits = Limits{MaxFiles: 2000, MaxTotal: 64 << 20, MaxFileScan: 8 << 20, MaxDepth: 16, MaxFindings: 500}

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
	totalBytes    int64
}

var skipNames = map[string]bool{".git": true, "skill.oms.sig": true, "skill-manifest.json": true}

// walk traverses root without following symlinks, enforcing Limits and
// detecting symlinks that resolve outside root.
func walk(root string, lim Limits) (*walked, error) {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	realRoot, err := filepath.EvalSymlinks(absRoot)
	if err != nil {
		return nil, err
	}
	w := &walked{contents: map[string][]byte{}, executable: map[string]bool{}}
	err = filepath.WalkDir(absRoot, func(p string, d fs.DirEntry, werr error) error {
		if werr != nil {
			return werr
		}
		rel, _ := filepath.Rel(absRoot, p)
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
			return filepath.SkipDir
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
		if d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		return w.addFile(rel, p, info, lim)
	})
	if err != nil && !errors.Is(err, errOverLimit) {
		return nil, err
	}
	sort.Slice(w.files, func(i, j int) bool { return w.files[i].Path < w.files[j].Path })
	return w, nil
}

var errOverLimit = errors.New("over limit")

func (w *walked) addFile(rel, p string, info fs.FileInfo, lim Limits) error {
	if len(w.files) >= lim.MaxFiles {
		w.overLimit = true
		return errOverLimit
	}
	w.totalBytes += info.Size()
	if w.totalBytes > lim.MaxTotal {
		w.overLimit = true
		return errOverLimit
	}
	posix := filepath.ToSlash(rel)
	data, err := os.ReadFile(p)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(data)
	w.files = append(w.files, FileEntry{Path: posix, SHA256: hex.EncodeToString(sum[:]), Bytes: info.Size()})
	if info.Size() <= lim.MaxFileScan {
		w.contents[posix] = data
	}
	if info.Mode()&0o111 != 0 {
		w.executable[posix] = true
	}
	return nil
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

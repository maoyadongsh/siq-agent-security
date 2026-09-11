package skillinstall

import (
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"
	"unicode/utf8"
)

func checkDirectories(path string) error {
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
func privateDirectory(path string) error {
	if err := checkDirectories(filepath.Dir(path)); err != nil {
		return err
	}
	if err := os.Mkdir(path, 0700); err != nil && !os.IsExist(err) {
		return ErrUnavailable
	}
	if err := checkDirectories(path); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return ErrInvalid
	}
	return nil
}
func targetPath(target Target, name string) (string, error) {
	if !nameValid(name) || !filepath.IsAbs(target.Root) || filepath.Clean(target.Root) != target.Root || !utf8.ValidString(target.Root) || strings.IndexFunc(target.Root, unicode.IsControl) >= 0 {
		return "", ErrInvalid
	}
	if err := checkDirectories(target.Root); err != nil {
		return "", err
	}
	parent := filepath.Join(target.Root, "skills")
	destination := filepath.Join(parent, name)
	if _, err := os.Lstat(parent); os.IsNotExist(err) {
		return destination, nil
	} else if err != nil {
		return "", ErrUnavailable
	}
	if err := checkDirectories(parent); err != nil {
		return "", err
	}
	dir, err := os.Open(parent)
	if err != nil {
		return "", ErrUnavailable
	}
	names, err := dir.Readdirnames(4097)
	dir.Close()
	if err != nil && err != io.EOF {
		return "", ErrUnavailable
	}
	if len(names) > 4096 {
		return "", ErrLimit
	}
	for _, existing := range names {
		if strings.EqualFold(existing, name) {
			return "", ErrConflict
		}
	}
	// Also inspect the exact path, including dangling links and case aliases on
	// filesystems whose lookup rules differ from Go's Unicode fold comparison.
	if _, err := os.Lstat(destination); err == nil {
		return "", ErrConflict
	} else if !os.IsNotExist(err) {
		return "", ErrUnavailable
	}
	return destination, nil
}

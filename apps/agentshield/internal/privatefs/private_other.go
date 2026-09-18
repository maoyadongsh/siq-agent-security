//go:build !windows

package privatefs

import "os"

func Open(path string) (*os.File, error) { return os.Open(path) }
func CreateNew(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_EXCL, 0600)
}
func CreateTemp(dir, pattern string) (*os.File, error) { return os.CreateTemp(dir, pattern) }
func MkdirAll(path string) error                       { return os.MkdirAll(path, 0700) }
func CheckDir(path string) error                       { return nil }
func checkFile(f *os.File, directory bool) error       { return nil }

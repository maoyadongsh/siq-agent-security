//go:build !windows

package linktest

import "os"

func Directory(target, link string) error { return os.Symlink(target, link) }

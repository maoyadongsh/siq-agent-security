//go:build !windows

package state

import "os"

func migrationPublishScratch(path, target string, created os.FileInfo) (bool, error) {
	return false, os.Link(path, target)
}

//go:build !windows

package privatefs

import "os"

func PublishNew(source, target string, created os.FileInfo) (bool, error) {
	return false, os.Link(source, target)
}

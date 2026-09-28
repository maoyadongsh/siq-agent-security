package adapterinstall

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func configPublishBusy(err error, path string) bool {
	var rename *os.LinkError
	if !errors.As(err, &rename) || rename.Op != "rename" || rename.New != path ||
		filepath.Dir(rename.Old) != filepath.Dir(path) || !strings.HasPrefix(filepath.Base(rename.Old), ".siq-adapter-pending-") {
		return false
	}
	return errors.Is(rename.Err, syscall.ERROR_ACCESS_DENIED) || errors.Is(rename.Err, syscall.Errno(32))
}

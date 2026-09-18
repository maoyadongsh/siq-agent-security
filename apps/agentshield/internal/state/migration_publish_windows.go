package state

import (
	"errors"
	"os"
	"syscall"

	"siq-agent-security/apps/agentshield/internal/privatefs"
)

// Publish by exclusive handle rename, not Link+Remove. After a process crash,
// the complete output is either still in scratch or a single private target.
func migrationPublishScratch(path, target string, created os.FileInfo) (moved bool, resultErr error) {
	native, err := windowsWriterPath(path)
	if err != nil {
		return false, err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return false, errors.New("state-migrate: invalid publication path")
	}
	const deleteAccess = 0x10000
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ|deleteAccess, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return false, errors.New("state-migrate: publication file unavailable")
	}
	f := os.NewFile(uintptr(h), path)
	defer func() { resultErr = errors.Join(resultErr, f.Close()) }()
	actual, err := f.Stat()
	if err != nil || !actual.Mode().IsRegular() || !os.SameFile(created, actual) || privatefs.CheckFile(f) != nil {
		return false, errors.New("state-migrate: publication identity or permissions changed")
	}
	// The existing FileRenameInfo primitive always keeps ReplaceIfExists=false.
	if err := renameWriterHandle(h, target); err != nil {
		return false, errors.New("state-migrate: exclusive publication failed")
	}
	return true, nil
}

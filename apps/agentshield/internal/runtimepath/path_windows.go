package runtimepath

import (
	"strings"
	"syscall"
	"unsafe"
)

var (
	kernel            = syscall.NewLazyDLL("kernel32.dll")
	queryDevice       = kernel.NewProc("QueryDosDeviceW")
	driveType         = kernel.NewProc("GetDriveTypeW")
	finalPath         = kernel.NewProc("GetFinalPathNameByHandleW")
	volumeInformation = kernel.NewProc("GetVolumeInformationByHandleW")
	fileInformation   = kernel.NewProc("GetFileInformationByHandleEx")
)

func localDevice(drive string) (string, error) {
	name, err := syscall.UTF16PtrFromString(drive)
	if err != nil {
		return "", ErrUnverified
	}
	var buffer [1024]uint16
	n, _, _ := queryDevice.Call(uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)))
	if n == 0 || n > uintptr(len(buffer)) {
		return "", ErrUnverified
	}
	device := syscall.UTF16ToString(buffer[:n])
	const prefix = `\Device\HarddiskVolume`
	suffix, ok := strings.CutPrefix(device, prefix)
	if !ok || suffix == "" {
		return "", ErrUnverified
	}
	for _, r := range suffix {
		if r < '0' || r > '9' {
			return "", ErrUnverified
		}
	}
	root, _ := syscall.UTF16PtrFromString(drive + `\`)
	t, _, _ := driveType.Call(uintptr(unsafe.Pointer(root)))
	if t != 3 {
		return "", ErrUnverified
	} // DRIVE_FIXED; no remote or removable fallback.
	return device, nil
}

func openComponent(path string) (syscall.Handle, error) {
	name, err := syscall.UTF16PtrFromString(strings.ReplaceAll(path, "/", `\`))
	if err != nil {
		return syscall.InvalidHandle, ErrUnverified
	}
	// FILE_READ_DATA (FILE_LIST_DIRECTORY for directories) makes the handle
	// participate in sharing checks; READ_ATTRIBUTES alone cannot pin a name.
	// Contents are never read. Omitting SHARE_DELETE pins opened components.
	return syscall.CreateFile(name, 0x81, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE, nil,
		syscall.OPEN_EXISTING, syscall.FILE_FLAG_BACKUP_SEMANTICS|syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
}

func handlePath(h syscall.Handle, flags uintptr) (string, error) {
	var buffer [1024]uint16
	n, _, _ := finalPath.Call(uintptr(h), uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)), flags)
	if n == 0 || n >= uintptr(len(buffer)) {
		return "", ErrUnverified
	}
	return syscall.UTF16ToString(buffer[:n]), nil
}

func checkComponent(h syscall.Handle, path, device string, requireDirectory bool) (identity, error) {
	var info syscall.ByHandleFileInformation
	if err := syscall.GetFileInformationByHandle(h, &info); err != nil {
		return identity{}, ErrUnverified
	}
	// Verify live deletion/link state on this same handle, independently of
	// the caller's access rights or the preceding sharing checks.
	var standard struct {
		AllocationSize, EndOfFile int64
		NumberOfLinks             uint32
		DeletePending, Directory  uint8
		Padding                   [2]byte
	}
	ok, _, _ := fileInformation.Call(uintptr(h), 1, uintptr(unsafe.Pointer(&standard)), unsafe.Sizeof(standard))
	if ok == 0 || standard.DeletePending != 0 {
		return identity{}, ErrUnverified
	}
	directory := info.FileAttributes&syscall.FILE_ATTRIBUTE_DIRECTORY != 0
	if directory != (standard.Directory != 0) || requireDirectory && !directory || info.FileAttributes&(syscall.FILE_ATTRIBUTE_REPARSE_POINT|0x40|0x1000) != 0 || !directory && (info.NumberOfLinks != 1 || standard.NumberOfLinks != 1) {
		return identity{}, ErrUnverified
	}
	t, err := syscall.GetFileType(h)
	if err != nil || t != syscall.FILE_TYPE_DISK {
		return identity{}, ErrUnverified
	}
	dos, err := handlePath(h, 0) // normalized DOS name, including long stored spelling.
	want := strings.ReplaceAll(path, "/", `\`)
	if err != nil || dos != `\\?\`+want {
		return identity{}, ErrUnverified
	}
	nt, err := handlePath(h, 2) // VOLUME_NAME_NT: prove the actual opened volume.
	if err != nil || nt != device+want[2:] {
		return identity{}, ErrUnverified
	}
	if directory {
		var flags uint32
		ok, _, _ := fileInformation.Call(uintptr(h), 23, uintptr(unsafe.Pointer(&flags)), unsafe.Sizeof(flags))
		if ok == 0 || flags != 0 {
			return identity{}, ErrUnverified
		}
	}
	return identity{volume: info.VolumeSerialNumber, indexHigh: info.FileIndexHigh, indexLow: info.FileIndexLow,
		createdHigh: info.CreationTime.HighDateTime, createdLow: info.CreationTime.LowDateTime, directory: directory}, nil
}

func inspectWindows(path string, allowMissing bool) (*Snapshot, error) {
	device, err := localDevice(path[:2])
	if err != nil {
		return nil, ErrUnverified
	}
	paths := []string{path[:3]}
	if len(path) > 3 {
		current := path[:2]
		for _, part := range strings.Split(path[3:], "/") {
			current += "/" + part
			paths = append(paths, current)
		}
	}
	handles := make([]syscall.Handle, 0, len(paths))
	defer func() {
		for i := len(handles) - 1; i >= 0; i-- {
			_ = syscall.CloseHandle(handles[i])
		}
	}()
	s := &Snapshot{path: path, device: device, allowMissing: allowMissing, exists: true}
	for i, component := range paths {
		h, err := openComponent(component)
		if err != nil {
			if i == len(paths)-1 && i > 0 && allowMissing && err == syscall.ERROR_FILE_NOT_FOUND {
				s.exists = false
				break
			}
			return nil, ErrUnverified
		}
		handles = append(handles, h)
		object, err := checkComponent(h, component, device, i < len(paths)-1)
		if err != nil {
			return nil, ErrUnverified
		}
		if i == 0 {
			var name [32]uint16
			ok, _, _ := volumeInformation.Call(uintptr(h), 0, 0, 0, 0, 0, uintptr(unsafe.Pointer(&name[0])), uintptr(len(name)))
			if ok == 0 || syscall.UTF16ToString(name[:]) != "NTFS" {
				return nil, ErrUnverified
			}
		}
		s.objects = append(s.objects, object)
	}
	// Repeat mutable attribute/namespace checks before returning the observation.
	for i, h := range handles {
		object, err := checkComponent(h, paths[i], device, i < len(paths)-1)
		if err != nil || object != s.objects[i] {
			return nil, ErrUnverified
		}
	}
	if !s.exists {
		h, err := openComponent(path)
		if err == nil {
			_ = syscall.CloseHandle(h)
			return nil, ErrUnverified
		}
		if err != syscall.ERROR_FILE_NOT_FOUND {
			return nil, ErrUnverified
		}
	}
	current, err := localDevice(path[:2])
	if err != nil || current != device {
		return nil, ErrUnverified
	}
	return s, nil
}

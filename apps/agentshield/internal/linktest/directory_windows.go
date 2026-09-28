package linktest

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"syscall"
)

// Directory creates a real junction without changing privilege or system policy.
// The caller owns both temporary paths and must remove the link before cleanup.
func Directory(target, link string) (err error) {
	target, err = filepath.Abs(target)
	if err != nil {
		return err
	}
	sub, err := syscall.UTF16FromString(`\??\` + target)
	if err != nil {
		return err
	}
	printName, err := syscall.UTF16FromString(target)
	if err != nil {
		return err
	}
	p, err := syscall.UTF16PtrFromString(link)
	if err != nil {
		return err
	}
	if err = os.Mkdir(link, 0700); err != nil {
		return err
	}
	defer func() {
		if err != nil {
			_ = os.Remove(link)
		}
	}()
	data := make([]byte, 16+2*(len(sub)+len(printName)))
	binary.LittleEndian.PutUint32(data, 0xa0000003)
	binary.LittleEndian.PutUint16(data[4:], uint16(len(data)-8))
	binary.LittleEndian.PutUint16(data[10:], uint16((len(sub)-1)*2))
	binary.LittleEndian.PutUint16(data[12:], uint16(len(sub)*2))
	binary.LittleEndian.PutUint16(data[14:], uint16((len(printName)-1)*2))
	for i, v := range append(sub, printName...) {
		binary.LittleEndian.PutUint16(data[16+i*2:], v)
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT|syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		return err
	}
	defer syscall.CloseHandle(h)
	var returned uint32
	return syscall.DeviceIoControl(h, 0x000900a4, &data[0], uint32(len(data)), nil, 0, &returned, nil)
}

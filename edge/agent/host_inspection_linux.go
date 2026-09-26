//go:build linux

package main

import (
	"errors"
	"io"
	"os"
	"syscall"
)

func readHostMetadata(path string) ([]byte, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), "host-metadata")
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return nil, errors.New("metadata_unavailable")
	}
	raw, err := io.ReadAll(io.LimitReader(f, (16<<10)+1))
	if err != nil || len(raw) > 16<<10 {
		return nil, errors.New("metadata_unavailable")
	}
	return raw, nil
}

func inspectLinuxHost() hostInspection {
	var uname syscall.Utsname
	machine := ""
	if syscall.Uname(&uname) == nil {
		for _, c := range uname.Machine {
			if c == 0 {
				break
			}
			machine += string(byte(c))
		}
	}
	return inspectHost(readHostMetadata, machine)
}

func cmdInspectHost(args []string) error {
	if len(args) != 0 {
		return errors.New("inspect-host accepts no arguments")
	}
	return printHostReport(os.Stdout, inspectLinuxHost())
}

//go:build linux

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf8"

	"siq-agent-security/edge/agent/installplan"
)

var errDeviceStateRead = errors.New("device_state_unsafe")

// Pin every path component before reading credentials. No automatic chmod or
// repair: a permissive/linked state needs explicit owner review.
func readDeviceState(path string) ([]byte, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errDeviceStateRead
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errDeviceStateRead
	}
	defer func() { syscall.Close(fd) }()
	parts := strings.Split(strings.TrimPrefix(filepath.Dir(path), "/"), "/")
	for i, part := range parts {
		if part == "" {
			return nil, errDeviceStateRead
		}
		next, err := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if err != nil {
			return nil, err
		}
		syscall.Close(fd)
		fd = next
		var st syscall.Stat_t
		if syscall.Fstat(fd, &st) != nil || (st.Uid != 0 && int(st.Uid) != os.Geteuid()) ||
			(st.Mode&0022 != 0 && !(st.Uid == 0 && st.Mode&syscall.S_ISVTX != 0)) {
			return nil, errors.New("device_state_ancestor_unsafe")
		}
		if i == len(parts)-1 && (int(st.Uid) != os.Geteuid() || st.Mode&0077 != 0) {
			return nil, errors.New("device_state_directory_unsafe")
		}
	}
	fileFD, err := syscall.Openat(fd, filepath.Base(path), syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fileFD), "device-state")
	defer f.Close()
	const limit = installplan.MaxBytes + 8192
	var before, after syscall.Stat_t
	if syscall.Fstat(fileFD, &before) != nil || before.Mode&syscall.S_IFMT != syscall.S_IFREG || before.Mode&0077 != 0 || before.Nlink != 1 || int(before.Uid) != os.Geteuid() || before.Size > limit {
		return nil, errors.New("device_state_file_unsafe")
	}
	raw, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || len(raw) > limit || syscall.Fstat(fileFD, &after) != nil || before.Size != after.Size || before.Mtim != after.Mtim || before.Ctim != after.Ctim || before.Mode != after.Mode || before.Nlink != after.Nlink || before.Uid != after.Uid {
		return nil, errors.New("device_state_changed")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if !utf8.Valid(raw) || checkStateJSON(decoder, 0) != nil {
		return nil, errors.New("device_state_json_invalid")
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, errors.New("device_state_json_trailing")
	}
	return raw, nil
}

func checkStateJSON(decoder *json.Decoder, depth int) error {
	if depth > 64 {
		return errDeviceStateRead
	}
	token, err := decoder.Token()
	if err != nil {
		return errDeviceStateRead
	}
	delim, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			key, err := decoder.Token()
			if err != nil {
				return errDeviceStateRead
			}
			name, ok := key.(string)
			if !ok || seen[name] {
				return errDeviceStateRead
			}
			seen[name] = true
			if err := checkStateJSON(decoder, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for decoder.More() {
			if err := checkStateJSON(decoder, depth+1); err != nil {
				return err
			}
		}
	default:
		return errDeviceStateRead
	}
	if _, err := decoder.Token(); err != nil {
		return errDeviceStateRead
	}
	return nil
}

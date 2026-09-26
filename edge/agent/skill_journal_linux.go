//go:build linux

package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const skillJournalLimit = 8 * 1024 * 1024

func skillJournalDirectory(create bool) (*os.File, error) {
	path, err := StateDir()
	if err != nil || !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" {
		return nil, errSkillJournal
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errSkillJournal
	}
	for _, part := range strings.Split(strings.TrimPrefix(path, "/"), "/") {
		next, err := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		syscall.Close(fd)
		if err != nil {
			return nil, errSkillJournal
		}
		fd = next
		var info syscall.Stat_t
		if syscall.Fstat(fd, &info) != nil || (int(info.Uid) != os.Geteuid() && info.Uid != 0) || (info.Mode&0022 != 0 && !(info.Uid == 0 && info.Mode&syscall.S_ISVTX != 0)) {
			syscall.Close(fd)
			return nil, errSkillJournal
		}
	}
	defer syscall.Close(fd)
	if !privateSkillDirectory(fd) {
		return nil, errSkillJournal
	}
	if create {
		if err := syscall.Mkdirat(fd, "skill_uploads", 0700); err != nil && err != syscall.EEXIST {
			return nil, errSkillJournal
		}
		if syscall.Fsync(fd) != nil {
			return nil, errSkillJournal
		}
	}
	next, err := syscall.Openat(fd, "skill_uploads", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err == syscall.ENOENT && !create {
		return nil, os.ErrNotExist
	}
	if err != nil {
		return nil, errSkillJournal
	}
	if !privateSkillDirectory(next) {
		syscall.Close(next)
		return nil, errSkillJournal
	}
	return os.NewFile(uintptr(next), "skill-upload-journal"), nil
}

func privateSkillDirectory(fd int) bool {
	var info syscall.Stat_t
	return syscall.Fstat(fd, &info) == nil && info.Mode&syscall.S_IFMT == syscall.S_IFDIR && int(info.Uid) == os.Geteuid() && info.Mode&0077 == 0
}

func readSkillRecord(dir *os.File, state *State, task *Task) (*skillUploadRecord, error) {
	fd, err := syscall.Openat(int(dir.Fd()), task.TaskID+".json", syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err == syscall.ENOENT {
		return nil, nil
	}
	if err != nil {
		return nil, errSkillJournal
	}
	file := os.NewFile(uintptr(fd), "skill-upload-record")
	defer file.Close()
	var info syscall.Stat_t
	if syscall.Fstat(fd, &info) != nil || info.Mode&syscall.S_IFMT != syscall.S_IFREG || info.Mode&0077 != 0 || info.Nlink != 1 || int(info.Uid) != os.Geteuid() || info.Size > skillJournalLimit {
		return nil, errSkillJournal
	}
	raw, err := io.ReadAll(io.LimitReader(file, skillJournalLimit+1))
	if err != nil || len(raw) > skillJournalLimit {
		return nil, errSkillJournal
	}
	var record skillUploadRecord
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&record) != nil || decoder.Decode(new(any)) != io.EOF || validateSkillRecord(&record, state, task) != nil {
		return nil, errSkillJournal
	}
	if file.Sync() != nil || dir.Sync() != nil {
		return nil, errSkillJournal
	}
	return &record, nil
}

func loadSkillUpload(state *State, task *Task) (*skillUploadRecord, error) {
	if _, _, err := skillRecordContext(state, task); err != nil {
		return nil, err
	}
	dir, err := skillJournalDirectory(false)
	if err == os.ErrNotExist {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer dir.Close()
	return readSkillRecord(dir, state, task)
}

func saveSkillUpload(state *State, task *Task, body json.RawMessage, digest string) error {
	taskDigest, contextDigest, err := skillRecordContext(state, task)
	if err != nil {
		return err
	}
	record := skillUploadRecord{"edge-skill-upload-journal/v1", taskDigest, contextDigest, digest, body}
	if validateSkillRecord(&record, state, task) != nil {
		return errSkillJournal
	}
	raw, err := json.Marshal(record)
	if err != nil || len(raw) > skillJournalLimit {
		return errSkillJournal
	}
	dir, err := skillJournalDirectory(true)
	if err != nil {
		return err
	}
	defer dir.Close()
	fd, err := syscall.Openat(int(dir.Fd()), task.TaskID+".json", syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err == syscall.EEXIST {
		prior, err := readSkillRecord(dir, state, task)
		if err != nil || prior == nil || prior.BatchDigest != digest {
			return errSkillJournal
		}
		return nil
	}
	if err != nil {
		return errSkillJournal
	}
	file := os.NewFile(uintptr(fd), "skill-upload-record")
	defer file.Close()
	if n, err := file.Write(raw); err != nil || n != len(raw) {
		return errSkillJournal
	}
	if file.Sync() != nil || dir.Sync() != nil {
		return errSkillJournal
	}
	return nil
}

package runtimeidentity

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

const maxRecordBytes = 16 << 10

// This is conservative path validation, not a hostile same-UID race sandbox.
func checkAncestors(dir string) error {
	for {
		info, err := os.Lstat(dir)
		if err != nil {
			return err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return ErrInvalid
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return nil
		}
		dir = parent
	}
}
func privateDir(dir string) error {
	if err := checkAncestors(filepath.Dir(dir)); err != nil {
		return err
	}
	if err := os.Mkdir(dir, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	if err := checkAncestors(dir); err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return ErrInvalid
	}
	return nil
}
func publish(path string, b []byte) error {
	if err := privateDir(filepath.Dir(path)); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".runtime-identity-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(b); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Link(f.Name(), path)
}
func readJSON(path string, out any) error {
	if err := checkAncestors(filepath.Dir(path)); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() > maxRecordBytes || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return ErrInvalid
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return ErrInvalid
	}
	b, err := io.ReadAll(io.LimitReader(f, maxRecordBytes+1))
	if err != nil || len(b) > maxRecordBytes {
		return ErrInvalid
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err = dec.Decode(out); err != nil {
		return ErrInvalid
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return ErrInvalid
	}
	// Canonical re-encoding of typed fields must equal canonical input. Rejects
	// aliases/unknown fields/null substitutions even if encoding/json accepts them.
	// Duplicate keys are rejected separately before signature verification.
	if !uniqueJSONKeys(b) {
		return ErrInvalid
	}
	var original any
	raw := json.NewDecoder(bytes.NewReader(b))
	raw.UseNumber()
	if raw.Decode(&original) != nil {
		return ErrInvalid
	}
	typed, _ := json.Marshal(out)
	var normalized any
	rd := json.NewDecoder(bytes.NewReader(typed))
	rd.UseNumber()
	_ = rd.Decode(&normalized)
	a, _ := json.Marshal(original)
	c, _ := json.Marshal(normalized)
	if !bytes.Equal(a, c) {
		return ErrInvalid
	}
	return nil
}
func uniqueJSONKeys(b []byte) bool {
	dec := json.NewDecoder(bytes.NewReader(b))
	var value func() bool
	value = func() bool {
		tok, err := dec.Token()
		if err != nil {
			return false
		}
		delim, ok := tok.(json.Delim)
		if !ok {
			return true
		}
		switch delim {
		case '{':
			seen := map[string]bool{}
			for dec.More() {
				k, e := dec.Token()
				if e != nil {
					return false
				}
				key, ok := k.(string)
				if !ok || seen[key] {
					return false
				}
				seen[key] = true
				if !value() {
					return false
				}
			}
		case '[':
			for dec.More() {
				if !value() {
					return false
				}
			}
		default:
			return false
		}
		_, err = dec.Token()
		return err == nil
	}
	if !value() {
		return false
	}
	_, err := dec.Token()
	return err == io.EOF
}
func recordIDs(dir string, limit int) ([]string, error) {
	if err := checkAncestors(dir); err != nil {
		return nil, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	entries, err := f.ReadDir(limit + 1)
	if err != nil && err != io.EOF {
		return nil, err
	}
	if len(entries) > limit {
		return nil, ErrUnavailable
	}
	ids := []string{}
	for _, entry := range entries {
		// Incomplete publication files never count as authority. They still consume
		// the directory read budget, avoiding unbounded orphan scanning.
		if strings.HasPrefix(entry.Name(), ".runtime-identity-") {
			continue
		}
		id := strings.TrimSuffix(entry.Name(), ".json")
		if !strings.HasSuffix(entry.Name(), ".json") || !identityID.MatchString(id) {
			return nil, ErrInvalid
		}
		ids = append(ids, id)
	}
	return ids, nil
}

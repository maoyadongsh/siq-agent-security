package skillcontext

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const invocationRecordBytes = 16 << 10

// This is conservative path validation, not a hostile same-UID race sandbox.
func invocationAncestors(dir string) error {
	for {
		info, err := os.Lstat(dir)
		if err != nil {
			return err
		}
		if !stateformat.AcceptDirectory(info, dir) {
			return invalid("")
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return nil
		}
		dir = parent
	}
}
func invocationPrivateDir(dir string) error {
	if err := invocationAncestors(filepath.Dir(dir)); err != nil {
		return err
	}
	if err := statefs.MkdirAllPrivate(dir); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	if err := invocationAncestors(dir); err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
		return invalid("")
	}
	return nil
}
func invocationPublish(path string, b []byte) error {
	if err := invocationPrivateDir(filepath.Dir(path)); err != nil {
		return err
	}
	f, err := statefs.CreatePrivateTemp(filepath.Dir(path), ".skill-invocation-*")
	if err != nil {
		return err
	}
	defer statefs.Remove(f.Name())
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
	return statefs.Link(f.Name(), path)
}
func readInvocationJSON(path string, out any) error {
	if err := invocationAncestors(filepath.Dir(path)); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() > invocationRecordBytes || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return invalid("")
	}
	f, err := statefs.OpenPrivate(path)
	if err != nil {
		return err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return invalid("")
	}
	b, err := io.ReadAll(io.LimitReader(f, invocationRecordBytes+1))
	if err != nil || len(b) > invocationRecordBytes {
		return invalid("")
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err = dec.Decode(out); err != nil {
		return invalid("")
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return invalid("")
	}
	// Canonical re-encoding of typed fields must equal canonical input. Rejects
	// aliases/unknown fields/null substitutions even if encoding/json accepts them.
	// Duplicate keys are rejected separately before signature verification.
	if !invocationUniqueKeys(b) {
		return invalid("")
	}
	var original any
	raw := json.NewDecoder(bytes.NewReader(b))
	raw.UseNumber()
	if raw.Decode(&original) != nil {
		return invalid("")
	}
	typed, _ := json.Marshal(out)
	var normalized any
	rd := json.NewDecoder(bytes.NewReader(typed))
	rd.UseNumber()
	_ = rd.Decode(&normalized)
	a, _ := json.Marshal(original)
	c, _ := json.Marshal(normalized)
	if !bytes.Equal(a, c) {
		return invalid("")
	}
	return nil
}
func invocationUniqueKeys(b []byte) bool {
	dec := json.NewDecoder(bytes.NewReader(b))
	var value func(int) bool
	value = func(depth int) bool {
		if depth > 16 {
			return false
		}
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
				if !value(depth + 1) {
					return false
				}
			}
		case '[':
			for dec.More() {
				if !value(depth + 1) {
					return false
				}
			}
		default:
			return false
		}
		_, err = dec.Token()
		return err == nil
	}
	if !value(0) {
		return false
	}
	_, err := dec.Token()
	return err == io.EOF
}

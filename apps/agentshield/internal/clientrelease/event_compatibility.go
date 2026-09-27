package clientrelease

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

var errEventCompatibility = errors.New("client-upgrade-check: candidate cannot read local event history or compatibility cannot be established; keep the current service and use a compatible release")

// This check only gates candidates without v2 local event support. It does not
// validate receipt signatures or authorize writes. Service transactions repeat
// their state-bound candidate check after acquiring their existing Writers.
func checkLegacyEventCompatibility(dir string) error {
	info, err := os.Lstat(dir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errEventCompatibility
	}
	snapshot, err := privatefs.OpenReadSnapshot(dir)
	if err != nil {
		return errEventCompatibility
	}
	defer snapshot.Close()
	pinDirectory := func(name string) error {
		info, err := os.Lstat(filepath.Join(dir, name))
		if err != nil {
			return err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return errEventCompatibility
		}
		return snapshot.PinDirectory(name)
	}
	remaining, entries := int64(256<<20), 10000
	readLog := func(name string, pending bool) error {
		if remaining <= 0 {
			return errEventCompatibility
		}
		path := filepath.Join(dir, name)
		before, err := os.Lstat(path)
		if err != nil || !before.Mode().IsRegular() || before.Size() > remaining {
			return errEventCompatibility
		}
		raw, err := snapshot.ReadFile(name, remaining)
		if err != nil {
			return errEventCompatibility
		}
		after, err := os.Lstat(path)
		if err != nil || !after.Mode().IsRegular() || !os.SameFile(before, after) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
			return errEventCompatibility
		}
		remaining -= int64(len(raw))
		scanner := bufio.NewScanner(bytes.NewReader(raw))
		scanner.Buffer(make([]byte, 4096), 1<<20)
		for scanner.Scan() {
			line := bytes.TrimSpace(scanner.Bytes())
			if len(line) != 0 && !legacyEventLine(line, pending) {
				return errEventCompatibility
			}
		}
		if scanner.Err() != nil {
			return errEventCompatibility
		}
		return nil
	}
	if err := pinDirectory("pending"); err == nil {
		if _, err := os.Lstat(filepath.Join(dir, "pending", "decisions.jsonl")); err == nil {
			if err := readLog(filepath.Join("pending", "decisions.jsonl"), true); err != nil {
				return err
			}
		} else if !os.IsNotExist(err) {
			return errEventCompatibility
		}
	} else if !os.IsNotExist(err) {
		return errEventCompatibility
	}
	if err := pinDirectory("receipts"); err == nil {
		chains, err := eventEntries(filepath.Join(dir, "receipts"), entries)
		if err != nil || len(chains) > entries {
			return errEventCompatibility
		}
		entries -= len(chains)
		for _, chain := range chains {
			if !chain.IsDir() {
				return errEventCompatibility
			}
			name := filepath.Join("receipts", chain.Name())
			if err := pinDirectory(name); err != nil {
				return errEventCompatibility
			}
			files, err := eventEntries(filepath.Join(dir, name), entries)
			if err != nil || len(files) > entries {
				return errEventCompatibility
			}
			entries -= len(files)
			for _, file := range files {
				if strings.HasSuffix(file.Name(), ".jsonl") {
					if err := readLog(filepath.Join(name, file.Name()), false); err != nil {
						return err
					}
				}
			}
		}
	} else if !os.IsNotExist(err) {
		return errEventCompatibility
	}
	if snapshot.Verify() != nil {
		return errEventCompatibility
	}
	return nil
}

func eventEntries(path string, limit int) ([]os.DirEntry, error) {
	f, err := statefs.OpenPrivateDir(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	entries, err := f.ReadDir(limit + 1)
	if errors.Is(err, io.EOF) {
		err = nil
	}
	return entries, err
}

func legacyEventLine(raw []byte, pending bool) bool {
	if !utf8.Valid(raw) {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return false
	}
	seen := map[string]bool{}
	for decoder.More() {
		token, err := decoder.Token()
		key, ok := token.(string)
		if err != nil || !ok || seen[key] {
			return false
		}
		seen[key] = true
		var value json.RawMessage
		if decoder.Decode(&value) != nil {
			return false
		}
		switch strings.ToLower(key) {
		case "schema_version", "local_origin":
			return false // Not present in historical receipts or pending v1.
		case "schema":
			var schema string
			if key != "schema" || !pending || bytes.Equal(value, []byte("null")) || json.Unmarshal(value, &schema) != nil || (schema != "" && schema != "pending_decision/v1") {
				return false
			}
		case "record_type":
			var kind string
			if key != "record_type" || json.Unmarshal(value, &kind) != nil || kind == "local_failure" {
				return false
			}
		}
	}
	_, err = decoder.Token()
	return err == nil && decoder.Decode(new(any)) == io.EOF
}

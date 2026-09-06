package pending

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const cursorFile = "promoted.lines"

// Promote appends signed observed receipts for each unpromoted pending line
// (DEV07-D). Cursor <state>/pending/promoted.lines stores how many leading
// JSONL lines were already promoted. appendOne must persist the signed
// receipt before returning nil; the cursor advances after each success.
func Promote(stateDir string, appendOne func(Record) error) (int, error) {
	if stateDir == "" {
		return 0, nil
	}
	path := filepath.Join(stateDir, "pending", "decisions.jsonl")
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}
	defer f.Close()

	var lines []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for sc.Scan() {
		lines = append(lines, sc.Text())
	}
	if err := sc.Err(); err != nil {
		return 0, err
	}

	start, err := readCursor(stateDir)
	if err != nil {
		return 0, err
	}
	if start > len(lines) {
		// Log truncated; reset cursor to len to avoid replaying missing lines as new.
		if err := writeCursor(stateDir, len(lines)); err != nil {
			return 0, err
		}
		return 0, nil
	}

	promoted := 0
	for i := start; i < len(lines); i++ {
		line := strings.TrimSpace(lines[i])
		if line == "" {
			if err := writeCursor(stateDir, i+1); err != nil {
				return promoted, err
			}
			continue
		}
		var rec Record
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			return promoted, fmt.Errorf("pending: corrupt JSONL at line %d: %w", i+1, err)
		}
		if rec.Schema != "" && rec.Schema != SchemaID {
			return promoted, fmt.Errorf("pending: unknown schema %q at line %d", rec.Schema, i+1)
		}
		if err := appendOne(rec); err != nil {
			return promoted, err
		}
		if err := writeCursor(stateDir, i+1); err != nil {
			return promoted, err
		}
		promoted++
	}
	return promoted, nil
}

func readCursor(stateDir string) (int, error) {
	raw, err := os.ReadFile(filepath.Join(stateDir, "pending", cursorFile))
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}
	s := strings.TrimSpace(string(raw))
	if s == "" {
		return 0, nil
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < 0 {
		return 0, fmt.Errorf("pending: bad %s", cursorFile)
	}
	return n, nil
}

func writeCursor(stateDir string, n int) error {
	dir := filepath.Join(stateDir, "pending")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".promoted.*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := fmt.Fprintf(tmp, "%d\n", n); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, 0o600); err != nil {
		return err
	}
	dest := filepath.Join(dir, cursorFile)
	if err := os.Rename(tmpName, dest); err != nil {
		return err
	}
	cleanup = false
	return nil
}

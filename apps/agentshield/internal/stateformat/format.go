// Package stateformat provides dependency-free state compatibility checks.
package stateformat

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"
	"unicode/utf8"
)

const MarkerName = "state-format.json"
const Budget = 4096
const ReaderVersion = 2
const WriterVersion = 2
const PlanName = "logs/migration-plan.json"
const MigrationDir = "state-migration-v2"

var ErrIncompatible = errors.New("state: incompatible state directory")
var ErrCorrupt = errors.New("state: invalid state format marker or directory")
var ErrFuture = errors.New("state: format requires a newer program")
var ErrMigration = errors.New("state: migration incomplete; run state-migrate --confirm with the compatible program")

type Marker struct {
	Schema         string `json:"schema"`
	ProgramVersion string `json:"program_version"`
	FormatVersion  int    `json:"format_version"`
	PublishedAt    string `json:"published_at"`
	MinReader      int    `json:"min_reader,omitempty"`
	MinWriter      int    `json:"min_writer,omitempty"`
	DirectoryID    string `json:"state_directory_id,omitempty"`
	InstanceID     string `json:"instance_id,omitempty"`
}

func Fail(err error) error { return errors.Join(ErrIncompatible, err) }

// DecodeObject requires exactly one UTF-8 object, exact field names, no nulls
// or duplicate keys. Nested values are subsequently validated by their owner.
func DecodeObject(raw []byte, fields []string, out any) error {
	if !utf8.Valid(raw) {
		return ErrCorrupt
	}
	allowed := map[string]bool{}
	for _, k := range fields {
		allowed[k] = true
	}
	seen := map[string]bool{}
	d := json.NewDecoder(bytes.NewReader(raw))
	t, e := d.Token()
	if e != nil || t != json.Delim('{') {
		return ErrCorrupt
	}
	for d.More() {
		t, e = d.Token()
		k, ok := t.(string)
		if e != nil || !ok || !allowed[k] || seen[k] {
			return ErrCorrupt
		}
		seen[k] = true
		var v json.RawMessage
		if d.Decode(&v) != nil || bytes.Equal(bytes.TrimSpace(v), []byte("null")) {
			return ErrCorrupt
		}
	}
	if _, e = d.Token(); e != nil || d.Decode(new(any)) != io.EOF {
		return ErrCorrupt
	}
	for _, k := range fields {
		if !seen[k] {
			return ErrCorrupt
		}
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(out) != nil {
		return ErrCorrupt
	}
	return nil
}
func Decode(raw []byte) (Marker, error) {
	var m Marker
	if len(raw) > Budget {
		return m, ErrCorrupt
	}
	var header struct {
		Schema string `json:"schema"`
	}
	if json.Unmarshal(raw, &header) != nil {
		return m, ErrCorrupt
	}
	fields := []string{"schema", "program_version", "format_version", "published_at"}
	if header.Schema == "state-format/v2" {
		fields = append(fields, "min_reader", "min_writer", "state_directory_id", "instance_id")
	} else if header.Schema != "state-format/v1" {
		return m, ErrCorrupt
	}
	if DecodeObject(raw, fields, &m) != nil || m.FormatVersion < 0 || m.ProgramVersion == "" || utf8.RuneCountInString(m.ProgramVersion) > 128 {
		return m, ErrCorrupt
	}
	if _, e := time.Parse(time.RFC3339Nano, m.PublishedAt); e != nil {
		return m, ErrCorrupt
	}
	if m.Schema == "state-format/v2" && (m.FormatVersion != 2 || m.MinReader < 1 || m.MinWriter < m.MinReader || !Digest(m.DirectoryID) || !Digest(m.InstanceID)) {
		return m, ErrCorrupt
	}
	return m, nil
}
func Digest(s string) bool {
	b, e := hex.DecodeString(s)
	return e == nil && len(b) == 32 && hex.EncodeToString(b) == s
}
func Hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func CheckParents(dir string) error {
	if dir == "" {
		return ErrCorrupt
	}
	p, e := filepath.Abs(dir)
	if e != nil {
		return ErrCorrupt
	}
	for {
		i, e := os.Lstat(p)
		if e == nil && !AcceptDirectory(i, p) {
			return ErrCorrupt
		}
		if e != nil && !errors.Is(e, os.ErrNotExist) {
			return ErrCorrupt
		}
		parent := filepath.Dir(p)
		if parent == p {
			return nil
		}
		p = parent
	}
}

// AcceptDirectory reports whether path is a directory. Darwin volume aliases
// such as /var -> /private/var sit directly under the volume root and must not
// make an otherwise ordinary temp or /tmp path look corrupt. User-created
// intermediate symlinks stay rejected.
func AcceptDirectory(info os.FileInfo, path string) bool {
	if info.IsDir() {
		return true
	}
	if info.Mode()&os.ModeSymlink == 0 || filepath.Dir(path) != filepath.Dir(filepath.Dir(path)) {
		return false
	}
	resolved, err := os.Stat(path)
	return err == nil && resolved.IsDir()
}

// LeafDirectory requires path itself to be a real directory, not a symlink.
// EvalSymlinks may rewrite ancestor volume aliases; the resolved object must
// still be the same directory.
func LeafDirectory(path string) error {
	if path == "" || filepath.Clean(path) != path {
		return ErrCorrupt
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return ErrCorrupt
	}
	canonical, err := filepath.EvalSymlinks(path)
	if err != nil {
		return err
	}
	resolved, err := os.Stat(canonical)
	if err != nil || !os.SameFile(info, resolved) {
		return ErrCorrupt
	}
	return nil
}
func ReadRegular(path string, limit int64) ([]byte, error) {
	i, e := os.Lstat(path)
	if e != nil {
		return nil, e
	}
	if !i.Mode().IsRegular() || i.Size() > limit {
		return nil, ErrCorrupt
	}
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	opened, e := f.Stat()
	if e != nil || !os.SameFile(i, opened) {
		return nil, ErrCorrupt
	}
	b, e := io.ReadAll(io.LimitReader(f, limit+1))
	after, se := os.Lstat(path)
	if e != nil || se != nil || len(b) > int(limit) || !after.Mode().IsRegular() || !os.SameFile(i, after) || after.Size() != i.Size() || !after.ModTime().Equal(i.ModTime()) {
		return nil, ErrCorrupt
	}
	return b, nil
}
func DirectoryID(dir string) (string, error) {
	p, e := filepath.Abs(dir)
	if e != nil {
		return "", e
	}
	p, e = filepath.EvalSymlinks(p)
	if e != nil {
		return "", e
	}
	return Hash([]byte("local-state-directory/v1\x00" + p)), nil
}
func ReadMarker(dir string) (Marker, error) {
	b, e := ReadRegular(filepath.Join(dir, MarkerName), Budget)
	if e != nil {
		return Marker{}, e
	}
	return Decode(b)
}
func ValidateBinding(dir string, m Marker) error {
	if m.Schema != "state-format/v2" {
		return nil
	}
	id, e := DirectoryID(dir)
	if e != nil || id != m.DirectoryID {
		return ErrCorrupt
	}
	raw, e := ReadRegular(filepath.Join(dir, "local-instance.json"), 65536)
	if e != nil {
		return ErrCorrupt
	}
	var instance struct {
		Schema string `json:"schema_version"`
		ID     string `json:"instance_id"`
	}
	if DecodeObject(raw, []string{"schema_version", "instance_id"}, &instance) != nil || instance.Schema != "local-client-instance/v1" || instance.ID != m.InstanceID {
		return ErrCorrupt
	}
	return nil
}

// Check ignores only an owned migration barrier when called by the migration
// engine. Ordinary clients must always pass ignoreMigration=false.
func Check(dir string, write, ignoreMigration bool) error {
	if e := CheckParents(dir); e != nil {
		return Fail(e)
	}
	if !ignoreMigration {
		if e := checkMigration(dir); e != nil {
			return Fail(e)
		}
	}
	m, e := ReadMarker(dir)
	if errors.Is(e, os.ErrNotExist) {
		return nil
	}
	if e != nil {
		return Fail(ErrCorrupt)
	}
	if m.Schema == "state-format/v1" {
		if m.FormatVersion != 1 {
			return Fail(ErrFuture)
		}
		return nil
	}
	if m.MinReader > ReaderVersion || (write && m.MinWriter > WriterVersion) {
		return Fail(ErrFuture)
	}
	if e := ValidateBinding(dir, m); e != nil {
		return Fail(e)
	}
	return nil
}
func checkMigration(dir string) error {
	plan, e := ReadRegular(filepath.Join(dir, PlanName), 8<<20)
	if errors.Is(e, os.ErrNotExist) {
		return nil
	}
	if e != nil {
		return ErrCorrupt
	}
	var header struct {
		Schema string `json:"schema"`
	}
	if json.Unmarshal(plan, &header) != nil || header.Schema != "state-migration-plan/v1" {
		return ErrCorrupt
	}
	done, e := ReadRegular(filepath.Join(dir, MigrationDir, "done.json"), Budget)
	if e != nil {
		return ErrMigration
	}
	var d struct {
		Schema string `json:"schema"`
		Plan   string `json:"plan_sha256"`
		Marker string `json:"marker_sha256"`
	}
	if DecodeObject(done, []string{"schema", "plan_sha256", "marker_sha256"}, &d) != nil || d.Schema != "state-migration-done/v1" || d.Plan != Hash(plan) {
		return ErrCorrupt
	}
	marker, e := ReadRegular(filepath.Join(dir, MarkerName), Budget)
	if e != nil || d.Marker != Hash(marker) {
		return ErrCorrupt
	}
	return nil
}

// RequirePath checks every state marker/barrier above a file or directory.
// A nested artifact/backup marker cannot shadow an incompatible outer state.
// Paths outside any state root retain their existing owner-specific validation.
func RequirePath(path string, write bool) error {
	if path == "" {
		return nil
	}
	p, e := filepath.Abs(path)
	if e != nil {
		return Fail(ErrCorrupt)
	}
	for {
		for _, n := range []string{MarkerName, PlanName} {
			_, e := os.Lstat(filepath.Join(p, filepath.FromSlash(n)))
			if e == nil {
				if err := Check(p, write, false); err != nil {
					return err
				}
				break
			}
		}
		q := filepath.Dir(p)
		if p == q {
			return nil
		}
		p = q
	}
}
func RecoveryMessage() string {
	return "状态版本不兼容或迁移未完成。请保留状态目录，运行 siq-agent-security state-status；中断迁移可用原兼容版本执行 state-migrate --confirm。未知版本请使用匹配程序，不要删除状态或回放旧授权。"
}

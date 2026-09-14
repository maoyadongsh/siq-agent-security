package state

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	StateFormatMarkerName   = "state-format.json"
	StateFormatSchema       = "state-format/v1"
	CurrentFormatVersion    = 2
	MinSupportedFormat      = 1
	MaxSupportedFormat      = 2
	StateFormatMarkerBudget = 4096
	CompatStatusOK          = "ok"
	CompatStatusLegacy      = "legacy_unversioned"
	CompatStatusFuture      = "future"
	CompatStatusCorrupt     = "corrupt"
	CompatStatusEmpty       = "empty"
)

// ProgramVersion is set by main before any worker starts; it is informational.
var ProgramVersion = "unversioned"

// Directory names created by Open for the existing ledger format family.
var coreStateDirs = []string{"keys", "admissions", "grants", "policies", "evidence", "receipts", "checkpoints", "inventory", "backups", "logs", "assets", "findings", "commits", "challenges", "intents", "intent-bindings", "action-correlation"}

// Version 1 is additive metadata for the existing local ledger format family.
// It is not a migration protocol and cannot constrain arbitrary historical binaries.
type StateFormatMarker struct {
	Schema         string `json:"schema"`
	ProgramVersion string `json:"program_version"`
	FormatVersion  int    `json:"format_version"`
	PublishedAt    string `json:"published_at"`
}

type StateCompatibility struct {
	Status         string
	Format         int
	ProgramVersion string
	Recovery       string
}

var (
	ErrIncompatibleState = stateformat.ErrIncompatible
	ErrFutureState       = stateformat.ErrFuture
	ErrLegacyState       = errors.New("state: explicit old format has no supported migration")
	ErrCorruptState      = stateformat.ErrCorrupt
	ErrMissingMarker     = errors.New("state: unrecognized nonempty state without a format marker")
)

func compatibilityFailure(status string, cause error) (StateCompatibility, error) {
	return StateCompatibility{Status: status, Recovery: "Use a compatible program or a verified backup; automatic migration is unavailable."}, fmt.Errorf("%w: %w", ErrIncompatibleState, cause)
}

// CheckStateCompatibility is read-only, including on missing or rejected roots.
func CheckStateCompatibility(dir string) (StateCompatibility, error) {
	if err := checkStateParents(dir); err != nil {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	// Validate every existing core directory before Open creates any missing one.
	for _, name := range coreStateDirs {
		info, err := os.Lstat(filepath.Join(dir, name))
		if (err == nil && !info.IsDir()) || (err != nil && !errors.Is(err, os.ErrNotExist)) {
			return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
		}
	}
	if err := stateformat.Check(dir, true, false); err != nil {
		if errors.Is(err, stateformat.ErrFuture) {
			if m, e := stateformat.ReadMarker(dir); e == nil && m.FormatVersion < 1 {
				return compatibilityFailure("unsupported_legacy", ErrLegacyState)
			}
			return compatibilityFailure(CompatStatusFuture, ErrFutureState)
		}
		return compatibilityFailure(CompatStatusCorrupt, err)
	}
	if m, err := stateformat.ReadMarker(dir); err == nil && m.Schema == "state-format/v2" {
		return StateCompatibility{Status: CompatStatusOK, Format: m.FormatVersion, ProgramVersion: m.ProgramVersion}, nil
	}
	path := filepath.Join(dir, StateFormatMarkerName)
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return checkUnmarkedState(dir)
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > StateFormatMarkerBudget {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	f, err := statefs.Open(path)
	if err != nil {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	raw, err := io.ReadAll(io.LimitReader(f, StateFormatMarkerBudget+1))
	after, statErr := os.Lstat(path)
	if err != nil || statErr != nil || !after.Mode().IsRegular() || !os.SameFile(info, after) || info.Size() != after.Size() || !info.ModTime().Equal(after.ModTime()) || len(raw) > StateFormatMarkerBudget || !utf8.Valid(raw) {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	marker, err := decodeStateMarker(raw)
	if err != nil {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	if marker.FormatVersion > MaxSupportedFormat {
		return compatibilityFailure(CompatStatusFuture, ErrFutureState)
	}
	if marker.FormatVersion < MinSupportedFormat {
		return compatibilityFailure("unsupported_legacy", ErrLegacyState)
	}
	return StateCompatibility{Status: CompatStatusOK, Format: marker.FormatVersion, ProgramVersion: marker.ProgramVersion}, nil
}

// Reject duplicate keys before decoding the typed flat record. encoding/json's
// default last-key-wins behavior is unsuitable for compatibility declarations.
func decodeStateMarker(raw []byte) (StateFormatMarker, error) {
	var m StateFormatMarker
	d := json.NewDecoder(bytes.NewReader(raw))
	first, err := d.Token()
	if err != nil || first != json.Delim('{') {
		return m, ErrCorruptState
	}
	seen := map[string]bool{}
	for d.More() {
		token, err := d.Token()
		if err != nil {
			return m, ErrCorruptState
		}
		key, ok := token.(string)
		if !ok || seen[key] {
			return m, ErrCorruptState
		}
		switch key {
		case "schema", "program_version", "format_version", "published_at":
		default:
			return m, ErrCorruptState
		}
		seen[key] = true
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return m, ErrCorruptState
		}
	}
	if _, err = d.Token(); err != nil || d.Decode(new(any)) != io.EOF {
		return m, ErrCorruptState
	}
	for _, key := range []string{"schema", "program_version", "format_version", "published_at"} {
		if !seen[key] {
			return m, ErrCorruptState
		}
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&m) != nil || m.Schema != StateFormatSchema || m.FormatVersion < 0 || m.ProgramVersion == "" || utf8.RuneCountInString(m.ProgramVersion) > 128 {
		return m, ErrCorruptState
	}
	if _, err := time.Parse(time.RFC3339Nano, m.PublishedAt); err != nil {
		return m, ErrCorruptState
	}
	return m, nil
}

// Root and existing ancestors must be real directories. Missing directories are
// allowed for initialization. No files or locks are created by this check.
func checkStateParents(dir string) error {
	if err := stateformat.ValidatePath(dir); err != nil {
		return err
	}
	if dir == "" {
		return ErrCorruptState
	}
	path, err := filepath.Abs(dir)
	if err != nil {
		return err
	}
	for {
		info, err := os.Lstat(path)
		if err == nil && !info.IsDir() {
			return ErrCorruptState
		}
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		parent := filepath.Dir(path)
		if parent == path {
			return nil
		}
		path = parent
	}
}

func checkUnmarkedState(dir string) (StateCompatibility, error) {
	f, err := statefs.Open(dir)
	if errors.Is(err, os.ErrNotExist) {
		return StateCompatibility{Status: CompatStatusEmpty}, nil
	}
	if err != nil {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	defer f.Close()
	entries, err := f.Readdirnames(4097)
	if err != nil && err != io.EOF || len(entries) > 4096 {
		return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
	}
	populated := false
	for _, entry := range entries {
		if entry != LockFile && !strings.HasPrefix(entry, LockFile+".stale.") {
			populated = true
			break
		}
	}
	if !populated {
		return StateCompatibility{Status: CompatStatusEmpty}, nil
	}
	// Recognize the complete core scaffold, not a lone arbitrary "grants" folder.
	scaffold := true
	for _, name := range coreStateDirs {
		info, err := os.Lstat(filepath.Join(dir, name))
		if err != nil || !info.IsDir() {
			scaffold = false
			break
		}
	}
	if !scaffold {
		partial := true
		for _, name := range entries {
			if name == LockFile || strings.HasPrefix(name, LockFile+".stale.") {
				continue
			}
			switch name {
			case "client-releases", "client-snapshots", "skill-imports", "adapter-write", "service-control":
				info, err := os.Lstat(filepath.Join(dir, name))
				if err != nil || !info.IsDir() {
					partial = false
				}
			default:
				partial = false
			}
		}
		if partial {
			return StateCompatibility{Status: CompatStatusLegacy}, nil
		}
		// Historical pubkey/admit bootstrap may have created only the identity.
		// Validate the actual bounded file; environment overrides are not evidence.
		info, keyErr := os.Lstat(filepath.Join(dir, "keys"))
		if keyErr == nil && info.IsDir() {
			raw, readErr := readInitializationFile(filepath.Join(dir, "keys", "signing.seed"))
			seed, decodeErr := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(string(raw)))
			if readErr == nil && len(raw) <= 1024 && decodeErr == nil && len(seed) == 32 {
				return StateCompatibility{Status: CompatStatusLegacy}, nil
			}
		}
		raw, err := readInitializationFile(filepath.Join(dir, "config.json"))
		var object map[string]json.RawMessage
		if err != nil || json.Unmarshal(raw, &object) != nil || object == nil {
			return compatibilityFailure(CompatStatusLegacy, ErrMissingMarker)
		}
		if _, err = decodeConfig(raw); err != nil {
			return compatibilityFailure(CompatStatusCorrupt, ErrCorruptState)
		}
	}
	return StateCompatibility{Status: CompatStatusLegacy}, nil
}

func RequireStateCompatibility(dir string) error {
	_, err := CheckStateCompatibility(dir)
	return err
}

// EnforceStateCompatibility does not mutate or migrate. The writer must own the
// exact directory; a version number alone never authorizes changing stored data.
func (s *Store) EnforceStateCompatibility(w *Writer, _ string) error {
	if err := stateformat.ValidatePath(s.Dir); err != nil {
		return err
	}
	if w != nil {
		if err := stateformat.ValidatePath(w.Dir); err != nil {
			return err
		}
	}
	if w == nil || filepath.Clean(w.Dir) != filepath.Clean(s.Dir) {
		return ErrWriterBusy
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil || pid != os.Getpid() || pid != w.pid || owner != w.owner {
		return ErrWriterBusy
	}
	return RequireStateCompatibility(s.Dir)
}

// Explicit initialization may add a marker, never replace one. No historical
// object is rewritten, backed up incompletely, or claimed to have been migrated.
func (s *Store) publishInitialStateFormat(w *Writer, fresh bool) error {
	if err := s.EnforceStateCompatibility(w, ""); err != nil {
		return err
	}
	if _, err := os.Lstat(filepath.Join(s.Dir, StateFormatMarkerName)); err == nil {
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	marker := stateformat.Marker{Schema: StateFormatSchema, ProgramVersion: ProgramVersion, FormatVersion: 1, PublishedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	if fresh {
		var err error
		marker, err = s.newFormatMarker(ProgramVersion)
		if err != nil {
			return err
		}
	}
	raw, err := json.Marshal(marker)
	if err != nil {
		return err
	}
	if _, err := stateformat.Decode(raw); err != nil {
		return err
	}
	return publishCommitFile(filepath.Join(s.Dir, StateFormatMarkerName), append(raw, '\n'))
}

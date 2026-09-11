package skillimport

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const maxImports = 64
const maxMetadataBytes int64 = 4 << 20

var importID = regexp.MustCompile(`^si-[a-f0-9]{32}$`)
var writeSlot = make(chan struct{}, 1)

type CreateRequest struct {
	SchemaVersion string `json:"schema_version"`
	ImportID      string `json:"import_id"`
	SourceKind    string `json:"source_kind"`
	Path          string `json:"path"`
	ActorID       string `json:"actor_id"`
}
type Record struct {
	Remote              *RemoteMetadata `json:"remote,omitempty"`
	SchemaVersion       string          `json:"schema_version"`
	ImportID            string          `json:"import_id"`
	SourceKind          string          `json:"source_kind"`
	SourceLocatorDigest string          `json:"source_locator_digest"`
	ActorID             string          `json:"actor_id"`
	CreatedAt           string          `json:"created_at"`
	ArtifactDigest      string          `json:"artifact_digest"`
	AnalysisSHA256      string          `json:"analysis_sha256"`
	Directories         []string        `json:"directories"`
	Files               []File          `json:"files"`
	ExcludedGitMetadata bool            `json:"excluded_git_metadata"`
	Signature           string          `json:"signature"`
}
type Analysis struct {
	Admission admission.Admission  `json:"admission"`
	Evidence  []admission.Evidence `json:"evidence"`
	SkillCard string               `json:"skill_card"`
}
type Store struct {
	download func(context.Context, string) (downloadedArchive, error)
	dir      string
	key      *signing.Key
	pack     *rulepack.Pack
	version  string
}

func Open(stateDir string, key *signing.Key, pack *rulepack.Pack, version string) (*Store, error) {
	if key == nil || pack == nil {
		return nil, ErrInvalid
	}
	absolute, err := filepath.Abs(stateDir)
	if err != nil || checkDirs(absolute) != nil {
		return nil, ErrInvalid
	}
	s := &Store{dir: filepath.Join(absolute, "skill-imports"), key: key, pack: pack, version: version}
	for _, dir := range []string{s.dir, filepath.Join(s.dir, "blobs"), filepath.Join(s.dir, "records")} {
		if err := privateDir(dir); err != nil {
			return nil, err
		}
	}
	return s, nil
}
func privateDir(path string) error {
	if err := checkDirs(filepath.Dir(path)); err != nil {
		return err
	}
	if err := os.Mkdir(path, 0700); err != nil && !os.IsExist(err) {
		return ErrUnavailable
	}
	if err := checkDirs(path); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return ErrInvalid
	}
	return nil
}
func actorValid(value string) bool {
	return value != "" && strings.TrimSpace(value) == value && utf8.ValidString(value) && utf8.RuneCountInString(value) <= 128 && strings.IndexFunc(value, unicode.IsControl) < 0
}
func kindValid(kind string) bool         { return kind == "local_dir" || kind == "local_zip" }
func (s *Store) blob(id string) string   { return filepath.Join(s.dir, "blobs", id) }
func (s *Store) record(id string) string { return filepath.Join(s.dir, "records", id+".json") }
func unsigned(r Record) map[string]any {
	raw, _ := json.Marshal(r)
	value, _ := canon.Decode(raw)
	m := value.(map[string]any)
	delete(m, "signature")
	return m
}

// Create publishes a fixed, analyzed candidate. Publication itself is the signed
// import audit event; it grants no runtime or platform installation authority.
func (s *Store) Create(ctx context.Context, req CreateRequest) (*Record, *Analysis, bool, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != "local-skill-import-create/v1" || !importID.MatchString(req.ImportID) || !kindValid(req.SourceKind) || !actorValid(req.ActorID) || req.Path == "" || len(req.Path) > 4096 || !utf8.ValidString(req.Path) {
		return nil, nil, false, ErrInvalid
	}
	source, err := filepath.Abs(req.Path)
	if err != nil {
		return nil, nil, false, ErrInvalid
	}
	locator := sum([]byte(source))
	return s.create(ctx, req, source, locator, nil)
}
func (s *Store) create(ctx context.Context, req CreateRequest, source, locator string, remote *RemoteCreateRequest) (*Record, *Analysis, bool, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	var err error
	select {
	case writeSlot <- struct{}{}:
		defer func() { <-writeSlot }()
	case <-ctx.Done():
		return nil, nil, false, ctx.Err()
	}
	if err = ctx.Err(); err != nil {
		return nil, nil, false, err
	}
	if _, err = os.Lstat(s.record(req.ImportID)); err == nil {
		rec, analysis, err := s.Load(ctx, req.ImportID)
		if err != nil {
			return nil, nil, false, err
		}
		if rec.SourceKind != req.SourceKind || rec.SourceLocatorDigest != locator || rec.ActorID != req.ActorID {
			return nil, nil, false, ErrConflict
		}
		return rec, analysis, true, nil
	} else if !os.IsNotExist(err) {
		return nil, nil, false, ErrUnavailable
	}
	if err = checkDirs(filepath.Join(s.dir, "blobs")); err != nil {
		return nil, nil, false, err
	}
	dirs, err := os.Open(filepath.Join(s.dir, "blobs"))
	if err != nil {
		return nil, nil, false, ErrUnavailable
	}
	names, readErr := dirs.Readdirnames(maxImports)
	dirs.Close()
	if readErr != nil && readErr != io.EOF {
		return nil, nil, false, ErrUnavailable
	}
	if len(names) >= maxImports {
		return nil, nil, false, ErrLimit
	}
	blob := s.blob(req.ImportID)
	if err = os.Mkdir(blob, 0700); err != nil {
		if os.IsExist(err) {
			return nil, nil, false, ErrConflict
		}
		return nil, nil, false, ErrUnavailable
	}
	published := false
	defer func() {
		if !published {
			_ = os.RemoveAll(blob)
		}
	}()
	payload := filepath.Join(blob, "payload")
	if err = os.Mkdir(payload, 0700); err != nil {
		return nil, nil, false, ErrUnavailable
	}
	var snapshot tree
	var excluded bool
	var metadata *RemoteMetadata
	switch req.SourceKind {
	case "local_dir":
		snapshot, excluded, err = directoryTree(ctx, source, payload, true)
		if err == nil {
			var again tree
			again, _, err = directoryTree(ctx, source, "", true)
			if err == nil {
				firstDigest, e1 := snapshot.digest()
				secondDigest, e2 := again.digest()
				if e1 != nil || e2 != nil || firstDigest != secondDigest {
					err = ErrChanged
				}
			}
		}
	case "https_zip":
		snapshot, excluded, metadata, err = s.remoteTree(ctx, source, blob, payload, remote)
	case "local_zip":
		if err = checkDirs(filepath.Dir(source)); err == nil {
			var raw []byte
			raw, _, err = readRegular(ctx, source, maxArchiveBytes)
			if err == nil {
				snapshot, excluded, err = extractZip(ctx, raw, payload)
			}
		}
	}
	if err != nil {
		return nil, nil, false, err
	}
	skillMD := false
	for _, file := range snapshot.Files {
		if file.Path == "SKILL.md" {
			skillMD = true
		}
	}
	if !skillMD {
		return nil, nil, false, ErrInvalid
	}
	sourceType := "local_dir"
	if req.SourceKind != "local_dir" {
		sourceType = "zip"
	}
	result, err := admission.Admit(payload, admission.Options{SourceIsOpaque: true, Source: admission.Source{Type: sourceType, Locator: "skill-import:" + req.ImportID, TrustLevel: "unknown"}, Key: s.key, Pack: s.pack, Version: s.version})
	if err != nil {
		return nil, nil, false, ErrUnavailable
	}
	if err = ctx.Err(); err != nil {
		return nil, nil, false, err
	}
	actual, _, err := directoryTree(ctx, payload, "", false)
	snapshotDigest, e1 := snapshot.digest()
	actualDigest, e2 := actual.digest()
	if err != nil || e1 != nil || e2 != nil || actualDigest != snapshotDigest {
		return nil, nil, false, ErrChanged
	}
	analysis := &Analysis{result.Admission, result.Evidence, result.SkillCard}
	analysisRaw, err := json.Marshal(analysis)
	if err != nil || int64(len(analysisRaw)) > maxMetadataBytes {
		return nil, nil, false, ErrLimit
	}
	if err = writeFile(filepath.Join(blob, "analysis.json"), analysisRaw, false); err != nil {
		return nil, nil, false, err
	}
	record := &Record{SchemaVersion: "local-skill-import/v1", ImportID: req.ImportID, SourceKind: req.SourceKind, SourceLocatorDigest: locator, ActorID: req.ActorID, CreatedAt: time.Now().UTC().Format(time.RFC3339Nano), ArtifactDigest: snapshotDigest, AnalysisSHA256: sum(analysisRaw), Directories: snapshot.Directories, Files: snapshot.Files, ExcludedGitMetadata: excluded}
	if metadata != nil {
		record.SchemaVersion = "local-skill-import/v2"
		record.Remote = metadata
	}
	record.Signature, err = s.key.SignCanonical(unsigned(*record))
	if err != nil {
		return nil, nil, false, ErrUnavailable
	}
	encoded, err := json.Marshal(record)
	if err != nil || int64(len(encoded)) > maxMetadataBytes {
		return nil, nil, false, ErrLimit
	}
	if err = ctx.Err(); err != nil {
		return nil, nil, false, err
	}
	if err = publish(s.record(req.ImportID), encoded); err != nil {
		return nil, nil, false, err
	}
	published = true
	return record, analysis, false, nil
}
func publish(path string, raw []byte) error {
	if err := privateDir(filepath.Dir(path)); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".import-*")
	if err != nil {
		return ErrUnavailable
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnavailable
	}
	if err = os.Link(f.Name(), path); err != nil {
		if os.IsExist(err) {
			return ErrConflict
		}
		return ErrUnavailable
	}
	return nil
}

// readRecord validates signed metadata; Load additionally verifies the entire payload.
func (s *Store) readRecord(ctx context.Context, id string) (*Record, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !importID.MatchString(id) {
		return nil, ErrInvalid
	}
	if err := checkDirs(filepath.Dir(s.record(id))); err != nil {
		return nil, err
	}
	if _, err := os.Lstat(s.record(id)); os.IsNotExist(err) {
		return nil, ErrNotFound
	}
	raw, _, err := readRegular(ctx, s.record(id), maxMetadataBytes)
	if err != nil {
		return nil, err
	}
	var rec Record
	if err = strictJSON(raw, &rec); err != nil {
		return nil, err
	}
	if !recordVersionValid(rec) || rec.ImportID != id || !actorValid(rec.ActorID) || len(rec.Files) == 0 || len(rec.Files) > maxFiles || len(rec.Directories) > maxDirs || !signing.VerifyCanonical(s.key.Public(), unsigned(rec), rec.Signature) {
		return nil, ErrChanged
	}
	if _, err = time.Parse(time.RFC3339Nano, rec.CreatedAt); err != nil {
		return nil, ErrChanged
	}

	expected := tree{rec.Directories, rec.Files}
	digest, err := expected.digest()
	if err != nil || digest != rec.ArtifactDigest {
		return nil, ErrChanged
	}
	var total int64
	for _, f := range rec.Files {
		if f.Bytes < 0 || f.Bytes > maxFileBytes {
			return nil, ErrChanged
		}
		total += f.Bytes
	}
	if total > maxTotalBytes {
		return nil, ErrChanged
	}
	return &rec, nil
}
func (s *Store) Load(ctx context.Context, id string) (*Record, *Analysis, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	rec, err := s.readRecord(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	payload := filepath.Join(s.blob(id), "payload")
	actual, _, err := directoryTree(ctx, payload, "", false)
	if err != nil {
		return nil, nil, err
	}
	expected := tree{rec.Directories, rec.Files}
	actualDigest, e1 := actual.digest()
	expectedDigest, e2 := expected.digest()
	if e1 != nil || e2 != nil || actualDigest != rec.ArtifactDigest || expectedDigest != rec.ArtifactDigest {
		return nil, nil, ErrChanged
	}
	if err = checkDirs(s.blob(id)); err != nil {
		return nil, nil, err
	}
	analysisRaw, _, err := readRegular(ctx, filepath.Join(s.blob(id), "analysis.json"), maxMetadataBytes)
	if err != nil {
		return nil, nil, err
	}
	if sum(analysisRaw) != rec.AnalysisSHA256 {
		return nil, nil, ErrChanged
	}
	var analysis Analysis
	if err = strictJSON(analysisRaw, &analysis); err != nil || !admission.Verify(s.key.Public(), analysis.Admission) {
		return nil, nil, ErrChanged
	}
	contentHash, _, err := admission.HashDirContext(ctx, payload, admission.DefaultLimits)
	if err != nil || contentHash != analysis.Admission.ContentHash {
		return nil, nil, ErrChanged
	}
	return rec, &analysis, nil
}
func strictJSON(raw []byte, out any) error {
	if !uniqueKeys(json.NewDecoder(bytes.NewReader(raw)), 0) {
		return ErrChanged
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(out) != nil {
		return ErrChanged
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return ErrChanged
	}
	original, err := canon.Decode(raw)
	if err != nil {
		return ErrChanged
	}
	typed, err := json.Marshal(out)
	if err != nil {
		return ErrChanged
	}
	normalized, err := canon.Decode(typed)
	if err != nil {
		return ErrChanged
	}
	a, _ := canon.Marshal(original)
	b, _ := canon.Marshal(normalized)
	if !bytes.Equal(a, b) {
		return ErrChanged
	}
	return nil
}
func uniqueKeys(d *json.Decoder, depth int) bool {
	if depth > 32 {
		return false
	}
	token, err := d.Token()
	if err != nil {
		return false
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return true
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			key, err := d.Token()
			name, ok := key.(string)
			if err != nil || !ok || seen[name] {
				return false
			}
			seen[name] = true
			if !uniqueKeys(d, depth+1) {
				return false
			}
		}
		end, err := d.Token()
		return err == nil && end == json.Delim('}')
	case '[':
		for d.More() {
			if !uniqueKeys(d, depth+1) {
				return false
			}
		}
		end, err := d.Token()
		return err == nil && end == json.Delim(']')
	}
	return false
}

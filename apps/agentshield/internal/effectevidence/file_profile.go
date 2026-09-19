package effectevidence

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
)

// CaptureFileForProfile never selects an interpretation from the path or OS.
// Its caller must derive profile from verified, currently usable authority.
func CaptureFileForProfile(profile runtimeaction.FilesystemProfile, path string, maxBytes int64) (FileSnapshot, error) {
	if profile == runtimeaction.FilesystemPOSIXV1 {
		return CaptureFile(path, maxBytes)
	}
	if profile != runtimeaction.FilesystemWindowsLocalDriveV1 || maxBytes < 1 || maxBytes > MaxFileBytes {
		return FileSnapshot{}, ErrFileObservation
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(profile, "filesystem", path)
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	path = canonical
	facts, err := runtimepath.InspectWindows(path, true)
	if err != nil || facts.IsDirectory() {
		return FileSnapshot{}, ErrFileObservation
	}
	last := strings.LastIndexByte(path, '/')
	if last < 2 {
		return FileSnapshot{}, ErrFileObservation
	}
	parent := path[:last]
	if last == 2 {
		parent = path[:3]
	}
	identity, err := facts.IdentityDigest()
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	parentIdentity, err := facts.AncestorIdentityDigest(parent)
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: canonical}})
	ref, err := ResourceReference(refs[0])
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	out := FileSnapshot{SchemaVersion: "file-snapshot/v2", FilesystemProfile: string(profile), IdentityDigest: identity, ParentIdentityDigest: parentIdentity, ResourceRef: ref}
	if !facts.Exists() {
		if facts.Revalidate() != nil {
			return FileSnapshot{}, ErrFileObservation
		}
		out.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
		return out, nil
	}
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() || before.Size() > maxBytes {
		return FileSnapshot{}, ErrFileObservation
	}
	f, err := fileopen.Regular(path)
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(before, opened) || facts.Revalidate() != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, maxBytes+1))
	if err != nil || n > maxBytes {
		return FileSnapshot{}, ErrFileObservation
	}
	after, err := f.Stat()
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	current, err := os.Lstat(path)
	if err != nil || !current.Mode().IsRegular() || !os.SameFile(opened, current) || n != opened.Size() || opened.Size() != after.Size() || !opened.ModTime().Equal(after.ModTime()) || current.Size() != after.Size() || !current.ModTime().Equal(after.ModTime()) || facts.Revalidate() != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	out.Exists, out.Size, out.Digest = true, n, hex.EncodeToString(h.Sum(nil))
	out.MTime = after.ModTime().UTC().Format(time.RFC3339Nano)
	out.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
	return out, nil
}

// Exact field presence prevents new empty/null interpretation fields from
// disappearing during canonical reconstruction of an old signed document.
func decodeFileObject(raw []byte, out any, fields []string) error {
	if !utf8.Valid(raw) {
		return ErrFileObservation
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	token, err := d.Token()
	if err != nil || token != json.Delim('{') {
		return ErrFileObservation
	}
	allowed, seen := map[string]bool{}, map[string]bool{}
	for _, field := range fields {
		allowed[field] = true
	}
	for d.More() {
		token, err = d.Token()
		field, ok := token.(string)
		if err != nil || !ok || !allowed[field] || seen[field] {
			return ErrFileObservation
		}
		seen[field] = true
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return ErrFileObservation
		}
	}
	if _, err := d.Token(); err != nil || d.Decode(new(any)) != io.EOF {
		return ErrFileObservation
	}
	if len(seen) != len(allowed) {
		return ErrFileObservation
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(out) != nil {
		return ErrFileObservation
	}
	return nil
}

func (s *FileSnapshot) UnmarshalJSON(raw []byte) error {
	type wire FileSnapshot
	var header struct {
		SchemaVersion string `json:"schema_version"`
	}
	if json.Unmarshal(raw, &header) != nil {
		return ErrFileObservation
	}
	fields := []string{"resource_ref", "exists", "digest", "size", "mtime", "captured_at"}
	if header.SchemaVersion != "" {
		fields = append(fields, "schema_version", "filesystem_profile", "identity_digest", "parent_identity_digest")
	}
	var value wire
	if decodeFileObject(raw, &value, fields) != nil || !validSnapshot(FileSnapshot(value)) {
		return ErrFileObservation
	}
	*s = FileSnapshot(value)
	return nil
}

func (o *FileObservation) UnmarshalJSON(raw []byte) error {
	type wire FileObservation
	var header struct {
		SchemaVersion string `json:"schema_version"`
	}
	if json.Unmarshal(raw, &header) != nil {
		return ErrFileObservation
	}
	fields := []string{"before", "after", "expected_digest", "execution_state", "result"}
	if header.SchemaVersion != "" {
		fields = append(fields, "schema_version")
	}
	var value wire
	if decodeFileObject(raw, &value, fields) != nil {
		return ErrFileObservation
	}
	expected, err := FileWrite(value.Before, value.After, value.ExpectedDigest)
	if err != nil || expected != FileObservation(value) {
		return ErrFileObservation
	}
	*o = FileObservation(value)
	return nil
}

func (p *PendingFile) UnmarshalJSON(raw []byte) error {
	type wire PendingFile
	var header struct {
		SchemaVersion string `json:"schema_version"`
	}
	if json.Unmarshal(raw, &header) != nil {
		return ErrFileObservation
	}
	fields := []string{"schema_version", "observation_id", "action_id", "decision_receipt_id", "scope", "source", "before", "owner_digest", "expected_digest", "max_bytes", "expires_at", "signing_schema", "signature"}
	if header.SchemaVersion == "file-observation-pending/v2" {
		fields = append(fields, "intent_id", "intent_digest")
	}
	var value wire
	if decodeFileObject(raw, &value, fields) != nil || !PendingFile(value).valid() {
		return ErrFileObservation
	}
	*p = PendingFile(value)
	return nil
}

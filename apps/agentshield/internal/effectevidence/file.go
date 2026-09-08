package effectevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

const MaxFileBytes int64 = 16 << 20

var ErrFileObservation = errors.New("file_observation_unavailable")

type FileSnapshot struct {
	ResourceRef string `json:"resource_ref"`
	Exists      bool   `json:"exists"`
	Digest      string `json:"digest"`
	Size        int64  `json:"size"`
	MTime       string `json:"mtime"`
	CapturedAt  string `json:"captured_at"`
}
type FileObservation struct {
	Before         FileSnapshot `json:"before"`
	After          FileSnapshot `json:"after"`
	ExpectedDigest string       `json:"expected_digest"`
	ExecutionState string       `json:"execution_state"`
	Result         string       `json:"result"`
}

// CaptureFile reads real host state. It never saves the path or content. The
// caller chooses the path from trusted observer configuration, not model input.
func CaptureFile(path string, maxBytes int64) (FileSnapshot, error) {
	var out FileSnapshot
	if maxBytes < 1 || maxBytes > MaxFileBytes || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return out, ErrFileObservation
	}
	normalized, normalizeErr := runtimeaction.NormalizeResource("filesystem", path)
	if normalizeErr != nil || normalized != path {
		return out, ErrFileObservation
	}
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})
	if len(refs) != 1 {
		return out, ErrFileObservation
	}
	ref, err := ResourceReference(refs[0])
	if err != nil {
		return out, ErrFileObservation
	}
	// Check every parent too. This reduces, but does not eliminate, directory
	// replacement races by a same-UID adversary (ADR-013).
	for current := filepath.Dir(path); ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return out, ErrFileObservation
		}
		if filepath.Dir(current) == current {
			break
		}
	}
	out.ResourceRef = ref
	before, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		out.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
		return out, nil
	}
	if err != nil || !before.Mode().IsRegular() || before.Size() > maxBytes {
		return FileSnapshot{}, ErrFileObservation
	}
	f, err := fileopen.Regular(path)
	if err != nil {
		return FileSnapshot{}, ErrFileObservation
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(before, opened) {
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
	if err != nil || !current.Mode().IsRegular() || !os.SameFile(opened, current) || n != opened.Size() || opened.Size() != after.Size() || !opened.ModTime().Equal(after.ModTime()) || current.Size() != after.Size() || !current.ModTime().Equal(after.ModTime()) {
		return FileSnapshot{}, ErrFileObservation
	}
	out.Exists = true
	out.Digest = hex.EncodeToString(h.Sum(nil))
	out.Size = n
	out.MTime = after.ModTime().UTC().Format(time.RFC3339Nano)
	out.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
	return out, nil
}

func validSnapshot(s FileSnapshot) bool {
	if !resourcePattern.MatchString(s.ResourceRef) {
		return false
	}
	if _, err := time.Parse(time.RFC3339Nano, s.CapturedAt); err != nil {
		return false
	}
	if !s.Exists {
		return s.Digest == "" && s.Size == 0 && s.MTime == ""
	}
	_, err := time.Parse(time.RFC3339Nano, s.MTime)
	return err == nil && s.Size >= 0 && s.Size <= MaxFileBytes && digestPattern.MatchString(s.Digest)
}

// FileWrite compares observations; equal content and metadata do not prove a
// write occurred. A changed file is still only partial host-side evidence.
func FileWrite(before, after FileSnapshot, expectedDigest string) (FileObservation, error) {
	if !validSnapshot(before) || !validSnapshot(after) || before.ResourceRef != after.ResourceRef || !digestPattern.MatchString(expectedDigest) {
		return FileObservation{}, ErrFileObservation
	}
	start, _ := time.Parse(time.RFC3339Nano, before.CapturedAt)
	end, _ := time.Parse(time.RFC3339Nano, after.CapturedAt)
	if end.Before(start) {
		return FileObservation{}, ErrFileObservation
	}
	o := FileObservation{Before: before, After: after, ExpectedDigest: expectedDigest, ExecutionState: "unknown", Result: "unknown"}
	if !after.Exists {
		o.ExecutionState = "failed"
		o.Result = "unexpected"
		return o, nil
	}
	if !before.Exists || before.Digest != after.Digest || before.Size != after.Size || before.MTime != after.MTime {
		o.ExecutionState = "completed"
		o.Result = "unexpected"
		if after.Digest == expectedDigest {
			o.Result = "expected"
		}
	}
	return o, nil
}

func (o FileObservation) Evidence(id string, action Action, source Source) (Evidence, error) {
	checked, err := FileWrite(o.Before, o.After, o.ExpectedDigest)
	if err != nil || checked != o || source.Type != "host_observer" || source.Independence != "host_independent" {
		return Evidence{}, ErrFileObservation
	}
	wire, _ := json.Marshal(o)
	var raw map[string]any
	_ = json.Unmarshal(wire, &raw)
	encoded, err := canon.Marshal(raw)
	if err != nil {
		return Evidence{}, ErrFileObservation
	}
	sum := sha256.Sum256(encoded)
	e := Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: id, ActionID: action.ActionID, DecisionReceiptID: action.DecisionReceiptID, EffectType: "file.write", ResourceRef: o.After.ResourceRef, ExecutionState: o.ExecutionState, Source: source, Coverage: "partial", Result: o.Result, EvidenceDigest: hex.EncodeToString(sum[:]), ObservedAt: o.After.CapturedAt, SigningSchema: "local_canonical/v1"}
	return e, e.Validate(time.Now())
}

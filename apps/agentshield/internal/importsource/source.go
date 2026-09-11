// Package importsource defines the immutable Skill content referenced by an
// imported permission admission. It conveys provenance, never runtime authority.
package importsource

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"regexp"
	"strings"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

var ErrInvalid = errors.New("skill_import_permission_source_invalid")
var hex64 = regexp.MustCompile(`^[a-f0-9]{64}$`)
var importID = regexp.MustCompile(`^si-[a-f0-9]{32}$`)

type Source struct {
	SchemaVersion  string `json:"schema_version"`
	ImportID       string `json:"import_id"`
	ArtifactDigest string `json:"artifact_digest"`
	AnalysisSHA256 string `json:"analysis_sha256"`
}

func Reserved(id string) bool { return strings.HasPrefix(id, "adm-si-") }
func (s Source) Canonical() ([]byte, error) {
	if s.SchemaVersion != "local-skill-import-permission-source/v1" || !importID.MatchString(s.ImportID) || !hex64.MatchString(s.ArtifactDigest) || !hex64.MatchString(s.AnalysisSHA256) {
		return nil, ErrInvalid
	}
	return canon.Marshal(map[string]any{"schema_version": s.SchemaVersion, "import_id": s.ImportID, "artifact_digest": s.ArtifactDigest, "analysis_sha256": s.AnalysisSHA256})
}
func (s Source) AdmissionID() (string, error) {
	raw, err := s.Canonical()
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(raw)
	return "adm-si-" + hex.EncodeToString(digest[:]), nil
}
func Parse(a admission.Admission) (Source, error) {
	var s Source
	if !Reserved(a.AdmissionID) || a.Source.Ref == nil || len(*a.Source.Ref) > 1024 {
		return s, ErrInvalid
	}
	if json.Unmarshal([]byte(*a.Source.Ref), &s) != nil {
		return s, ErrInvalid
	}
	raw, err := s.Canonical()
	if err != nil || !bytes.Equal(raw, []byte(*a.Source.Ref)) {
		return s, ErrInvalid
	}
	id, err := s.AdmissionID()
	if err != nil || id != a.AdmissionID || a.Source.Locator != "skill-import:"+s.ImportID {
		return s, ErrInvalid
	}
	return s, nil
}

// Bind signs a provenance-specific copy, retaining the original analysis clock
// and facts. Callers must first verify the complete imported snapshot.
func (s Source) Bind(a admission.Admission, key *signing.Key) (admission.Admission, error) {
	if key == nil || !admission.Verify(key.Public(), a) || a.Verdict == "quarantine" || !hex64.MatchString(a.ContentHash) {
		return admission.Admission{}, ErrInvalid
	}
	raw, err := s.Canonical()
	if err != nil {
		return admission.Admission{}, err
	}
	// Detach nested facts, findings and optional pointers from the original analysis.
	encoded, err := json.Marshal(a)
	if err != nil {
		return admission.Admission{}, ErrInvalid
	}
	var out admission.Admission
	if json.Unmarshal(encoded, &out) != nil {
		return out, ErrInvalid
	}
	out.AdmissionID, err = s.AdmissionID()
	if err != nil {
		return out, err
	}
	ref := string(raw)
	out.Source.Ref = &ref
	out.Source.Locator = "skill-import:" + s.ImportID
	for i, id := range out.EvidenceIDs {
		out.EvidenceIDs[i] = EvidenceID(out.AdmissionID, id)
	}
	for i := range out.DeclaredFacts {
		for j, id := range out.DeclaredFacts[i].EvidenceIDs {
			out.DeclaredFacts[i].EvidenceIDs[j] = EvidenceID(out.AdmissionID, id)
		}
	}
	for i := range out.Findings {
		for j, id := range out.Findings[i].EvidenceIDs {
			out.Findings[i].EvidenceIDs[j] = EvidenceID(out.AdmissionID, id)
		}
	}
	out.SkillCardRef = nil
	encoded, err = json.Marshal(out)
	if err != nil {
		return out, ErrInvalid
	}
	value, err := canon.Decode(encoded)
	if err != nil {
		return out, ErrInvalid
	}
	doc := value.(map[string]any)
	delete(doc, "signature")
	out.Signature, err = key.SignCanonical(doc)
	if err != nil || !admission.Verify(key.Public(), out) {
		return admission.Admission{}, ErrInvalid
	}
	return out, nil
}

func EvidenceID(admissionID, original string) string {
	digest := sha256.Sum256([]byte(admissionID + "\x00" + original))
	return "evi-si-" + hex.EncodeToString(digest[:])
}
func BindEvidence(e admission.Evidence, a admission.Admission, key *signing.Key) (admission.Evidence, error) {
	if _, err := Parse(a); err != nil || key == nil {
		return admission.Evidence{}, ErrInvalid
	}
	e.EvidenceID = EvidenceID(a.AdmissionID, e.EvidenceID)
	e.SourceLocator = a.Source.Locator
	id := a.AdmissionID
	e.SubjectRef = &id
	raw, err := json.Marshal(e)
	if err != nil {
		return e, ErrInvalid
	}
	value, err := canon.Decode(raw)
	if err != nil {
		return e, ErrInvalid
	}
	doc := value.(map[string]any)
	delete(doc, "signature")
	e.Signature, err = key.SignCanonical(doc)
	return e, err
}

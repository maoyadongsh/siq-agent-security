package state

import (
	"encoding/json"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

// PutImportAdmission preserves exact deterministic derived records. This does
// not publish a Grant or authority; a later audited GrantCommit does that.
func (s *Store) PutImportAdmission(result *admission.Result) error {
	if result == nil {
		return importsource.ErrInvalid
	}
	if _, err := importsource.Parse(result.Admission); err != nil {
		return err
	}
	// Evidence/card can exist after an interrupted preparation; deterministic
	// bytes make retry safe without silently accepting earlier source metadata.
	for _, ev := range result.Evidence {
		if !safeID(ev.EvidenceID) {
			return importsource.ErrInvalid
		}
		raw, err := json.MarshalIndent(ev, "", "  ")
		if err != nil {
			return err
		}
		if err := publishCommitFile(filepath.Join(s.Dir, "evidence", ev.EvidenceID+".json"), raw); err != nil {
			return err
		}
	}
	base := filepath.Join(s.Dir, "admissions", result.Admission.AdmissionID)
	if err := publishCommitFile(base+".skill-card.md", []byte(result.SkillCard)); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(result.Admission, "", "  ")
	if err != nil {
		return err
	}
	return publishCommitFile(base+".json", raw)
}

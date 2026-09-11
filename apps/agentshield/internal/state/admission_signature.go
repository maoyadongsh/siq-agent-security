package state

import (
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/admission"
)

// VerifyAdmission recognizes only the historical local-store transformation
// that appended its own card path after signing a null reference. This does not
// relax admission.Verify or ignore changes to any authorization-bearing field.
func (s *Store) VerifyAdmission(pub []byte, value admission.Admission) bool {
	if admission.Verify(pub, value) {
		return true
	}
	if !safeID(value.AdmissionID) || value.SkillCardRef == nil || *value.SkillCardRef != filepath.Join(s.Dir, "admissions", value.AdmissionID+".skill-card.md") {
		return false
	}
	value.SkillCardRef = nil
	return admission.Verify(pub, value)
}

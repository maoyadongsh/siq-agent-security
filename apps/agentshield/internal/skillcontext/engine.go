package skillcontext

import (
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// VerifyForEngine adapts Verify to the receipt engine's SkillContextLookup
// contract. The claim is engine-validated already; a claim conflicting with
// the SEC skill identity invalidates instead of verifying. A nil claim never
// downgrades a SEC-covered subject: attribution comes from the SEC itself.
func (s *Store) VerifyForEngine(platform, agentID, sessionID, taskID string, claim *receipt.SkillClaim) *receipt.SkillContextVerification {
	v, err := s.Verify(platform, agentID, sessionID, taskID)
	if err != nil {
		return &receipt.SkillContextVerification{Invalid: true, ReasonCode: "skill_context_invalid"}
	}
	if v == nil {
		return nil
	}
	if v.Invalid {
		return &receipt.SkillContextVerification{Invalid: true, ReasonCode: v.ReasonCode}
	}
	c := v.Context
	if claim != nil && (claim.SkillID != c.Skill.SkillID || (claim.ContentHash != "" && claim.ContentHash != c.Skill.ContentHash) || (c.Skill.Version != "" && claim.Version != c.Skill.Version)) {
		return &receipt.SkillContextVerification{Invalid: true, ReasonCode: "skill_context_mismatch"}
	}
	return &receipt.SkillContextVerification{
		ContextID:     c.ContextID,
		EvidenceLevel: c.EvidenceLevel,
		SkillID:       c.Skill.SkillID,
		Version:       c.Skill.Version,
		ContentHash:   c.Skill.ContentHash,
		Grant:         v.Grant,
	}
}

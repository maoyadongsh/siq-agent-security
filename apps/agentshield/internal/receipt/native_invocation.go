package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

// These references are evidence of a live trusted lookup, not client claims or
// portable authorization tokens. RuntimeReceipt v3 authenticates the full chain.
type NativeAuthorityRef struct {
	GrantID     string `json:"grant_id"`
	GrantDigest string `json:"grant_digest"`
}
type NativeContextRef struct {
	ContextID        string             `json:"context_id"`
	ContextSignature string             `json:"context_signature"`
	Authority        NativeAuthorityRef `json:"authority"`
}
type NativeInvocationEvidence struct {
	CallID                string             `json:"call_id"`
	CallSignature         string             `json:"call_signature"`
	SessionRegistrationID string             `json:"session_registration_id"`
	SessionSignature      string             `json:"session_signature"`
	RequestBinding        string             `json:"request_binding"`
	AgentAuthority        NativeAuthorityRef `json:"agent_authority"`
	NoSkill               bool               `json:"no_skill"`
	Contexts              []NativeContextRef `json:"contexts"`
}
type NativeInvocationVerification struct {
	Evidence    *NativeInvocationEvidence
	AgentGrant  *grant.Grant
	SkillGrants []*grant.Grant // exact leaf-to-root order, including repeated grants
}

// NativeCallLookup determines Required from trusted enrollment/host policy,
// never from request claims or the presence/absence of a call record. All live
// signature, installation, session, task and ancestor checks precede return.
// A lookup failure is an authority denial, even when Required could not be read.
type NativeCallLookup func(Request) (required bool, verified *NativeInvocationVerification, err error)

var nativeCallIDPattern = regexp.MustCompile(`^ncall-[0-9a-f]{32}$`)
var nativeSessionIDPattern = regexp.MustCompile(`^nsess-[0-9a-f]{32}$`)
var nativeContextIDPattern = regexp.MustCompile(`^sec-[0-9a-f]{32}$`)
var nativeDigestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var nativeSignaturePattern = regexp.MustCompile(`^[0-9a-f]{128}$`)

func nativeGrantMatches(g *grant.Grant, ref NativeAuthorityRef, req Request) bool {
	if g == nil || g.GrantID != ref.GrantID || g.Subject.Type != "agent_instance" || g.Subject.ID != req.AgentID || g.Platform != req.Platform || !nativeDigestPattern.MatchString(ref.GrantDigest) {
		return false
	}
	b, err := json.Marshal(g)
	if err != nil {
		return false
	}
	var m map[string]any
	if json.Unmarshal(b, &m) != nil {
		return false
	}
	b, err = canon.Marshal(m)
	if err != nil {
		return false
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]) == ref.GrantDigest
}

func (e *Engine) resolveNativeInvocation(req Request) (*SkillContextVerification, bool) {
	if e.opts.NativeCalls == nil {
		return nil, false
	}
	required, v, err := e.opts.NativeCalls(req)
	fail := func(code string) (*SkillContextVerification, bool) {
		return &SkillContextVerification{Invalid: true, ReasonCode: code}, true
	}
	if err != nil {
		return fail("native_skill_authority_unavailable")
	}
	if !required {
		if v != nil {
			return fail("native_skill_authority_invalid")
		}
		return nil, false
	}
	if v == nil || v.Evidence == nil || v.AgentGrant == nil {
		return fail("native_skill_call_required")
	}
	// Decouple receipts and decisions from mutable callback-owned documents.
	raw, err := json.Marshal(v)
	if err != nil {
		return fail("native_skill_authority_invalid")
	}
	var value NativeInvocationVerification
	if json.Unmarshal(raw, &value) != nil {
		return fail("native_skill_authority_invalid")
	}
	v = &value
	a := v.Evidence
	binding, err := trustedcontext.RequestBinding(trustedcontext.Subject{Platform: req.Platform, AgentID: req.AgentID, SessionID: req.SessionID}, requestRuntimeTaskID(req), req.Tool, req.ToolCallID, req.Params)
	if err != nil || a.RequestBinding != binding || !nativeCallIDPattern.MatchString(a.CallID) || !nativeSignaturePattern.MatchString(a.CallSignature) ||
		!nativeSessionIDPattern.MatchString(a.SessionRegistrationID) || !nativeSignaturePattern.MatchString(a.SessionSignature) ||
		!nativeGrantMatches(v.AgentGrant, a.AgentAuthority, req) || v.AgentGrant.Skill != nil ||
		(v.AgentGrant.Status != "deployed" && v.AgentGrant.Status != "effective") || a.Contexts == nil || len(a.Contexts) > 8 ||
		len(a.Contexts) != len(v.SkillGrants) || a.NoSkill != (len(a.Contexts) == 0) {
		return fail("native_skill_authority_invalid")
	}
	now := e.opts.Now()
	if grant.ValidateLifetime(*v.AgentGrant, now) != nil {
		return fail("native_skill_authority_invalid")
	}
	seen := map[string]bool{}
	for i, c := range a.Contexts {
		g := v.SkillGrants[i]
		if !nativeContextIDPattern.MatchString(c.ContextID) || !nativeSignaturePattern.MatchString(c.ContextSignature) || seen[c.ContextID] ||
			!nativeGrantMatches(g, c.Authority, req) || g.Skill == nil || g.GrantID == v.AgentGrant.GrantID {
			return fail("native_skill_authority_invalid")
		}
		seen[c.ContextID] = true
		if grant.ValidateLifetime(*g, now) != nil || (g.Status != "deployed" && g.Status != "effective" && !(g.Status == "approved" && importsource.Reserved(g.AdmissionID))) {
			return fail("native_skill_authority_invalid")
		}
		if !validSkillClaim(nativeSkillClaim(g)) {
			return fail("native_skill_authority_invalid")
		}
	}
	if a.NoSkill {
		if req.Skill != nil {
			return fail("native_skill_claim_conflict")
		}
		return &SkillContextVerification{Grant: v.AgentGrant, Native: v}, true
	}
	g := v.SkillGrants[0]
	claim := nativeSkillClaim(g)
	if req.Skill != nil && (!validSkillClaim(req.Skill) || req.Skill.SkillID != claim.SkillID ||
		(req.Skill.ContentHash != "" && req.Skill.ContentHash != claim.ContentHash) ||
		(claim.Version != "" && req.Skill.Version != claim.Version)) {
		return fail("native_skill_claim_conflict")
	}
	return &SkillContextVerification{ContextID: a.Contexts[0].ContextID, EvidenceLevel: "controlled_invocation",
		SkillID: claim.SkillID, Version: claim.Version, ContentHash: claim.ContentHash, Grant: g, Native: v}, true
}

func nativeSkillClaim(g *grant.Grant) *SkillClaim {
	c := &SkillClaim{SkillID: g.Skill.SkillID, ContentHash: g.Skill.ContentHash}
	if g.Skill.Version != nil {
		c.Version = *g.Skill.Version
	}
	return c
}

func nativeAttribution(sec *SkillContextVerification) *SkillAttribution {
	if sec.Native.Evidence.NoSkill {
		return nil
	}
	return &SkillAttribution{SkillID: sec.SkillID, Version: sec.Version, ContentHash: sec.ContentHash, Status: SkillAttributionVerified,
		EvidenceLevel: "controlled_invocation", ContextID: sec.ContextID, CallBinding: sec.Native.Evidence.RequestBinding}
}

func (e *Engine) evaluateNativeIntersection(req Request, s *session, d runtimeaction.Descriptor, rec *Receipt, now time.Time, sec *SkillContextVerification) (string, string) {
	v := sec.Native
	// Reconfirm the final parameter binding before any grant is evaluated.
	binding, err := trustedcontext.CallBinding(req.Platform, req.SessionID, req.AgentID, requestRuntimeTaskID(req), req.Tool, req.ToolCallID, req.Params)
	if err != nil || binding != v.Evidence.RequestBinding {
		return denyGrantAuthority(rec, "native_skill_call_changed")
	}
	action, reason := ActionAllow, "granted by exact Agent and Skill authority intersection"
	grants := append([]*grant.Grant{v.AgentGrant}, v.SkillGrants...)
	for i, g := range grants {
		scratch := &Receipt{MatchedFactIDs: []string{}}
		if i > 0 {
			claim := nativeSkillClaim(g)
			scratch.SkillAttribution = &SkillAttribution{SkillID: claim.SkillID, Version: claim.Version, ContentHash: claim.ContentHash,
				Status: SkillAttributionVerified, EvidenceLevel: "controlled_invocation", ContextID: v.Evidence.Contexts[i-1].ContextID, CallBinding: binding}
		}
		leg, why := e.evaluateGrant(req, s, d, scratch, now, g, false)
		if scratch.AuthorityStatus == "invalid" {
			rec.AuthorityStatus, rec.AuthorityReasonCode = scratch.AuthorityStatus, scratch.AuthorityReasonCode
			return leg, why
		}
		for _, fid := range scratch.MatchedFactIDs {
			rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
		}
		if leg == ActionDeny || (leg == ActionHold && action == ActionAllow) {
			action, reason = leg, why
		}
	}
	// The leaf is the displayed match; complete authority is retained in v3.
	id := sec.Grant.GrantID
	rec.MatchedGrantID = &id
	return action, reason
}

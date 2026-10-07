package skillcontext

import (
	"strings"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

// VerifyNativeForEngine does not decide whether a session is required. The
// trusted enrollment/host policy must select this mandatory path independently
// of request claims or stored-call presence. Missing authority returns an error.
func (s *NativeCallStore) VerifyNativeForEngine(req receipt.Request) (*receipt.NativeInvocationVerification, error) {
	if !agentPattern.MatchString(req.AgentID) {
		return nil, invalid("native_skill_agent_invalid")
	}
	task := req.RuntimeTaskID
	if task == "" {
		task = req.TaskID
	}
	v, err := s.VerifyCall(NativeCallRequest{Subject: Subject{Platform: req.Platform, InstanceID: "hi-" + strings.TrimPrefix(req.AgentID, "hri-"),
		AgentID: req.AgentID, SessionID: req.SessionID, TaskID: task}, Tool: req.Tool, ToolCallID: req.ToolCallID, Params: req.Params})
	if err != nil {
		return nil, err
	}
	a := &receipt.NativeInvocationEvidence{CallID: v.Call.CallID, CallSignature: v.Call.Signature, SessionRegistrationID: v.Session.RegistrationID,
		SessionSignature: v.Session.Signature, RequestBinding: v.Call.RequestBinding, NoSkill: v.Call.NoSkill,
		AgentAuthority: receipt.NativeAuthorityRef{GrantID: v.Call.AgentAuthority.GrantID, GrantDigest: v.Call.AgentAuthority.GrantDigest},
		Contexts:       []receipt.NativeContextRef{}}
	result := &receipt.NativeInvocationVerification{Evidence: a, AgentGrant: v.AgentGrant}
	if v.Invocation != nil {
		result.SkillGrants = v.Invocation.SkillGrants
		for _, c := range v.Invocation.Contexts {
			a.Contexts = append(a.Contexts, receipt.NativeContextRef{ContextID: c.ContextID, ContextSignature: c.Signature,
				Authority: receipt.NativeAuthorityRef{GrantID: c.Authority.GrantID, GrantDigest: c.Authority.GrantDigest}})
		}
	}
	return result, nil
}

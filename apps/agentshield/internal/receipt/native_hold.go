package receipt

import "reflect"

// Call identity differs on an explicit retry. Every authority-bearing field
// must remain identical; the actual tool/parameters/subject are independently
// checked by the reservation request correlation and each trusted lookup.
func sameNativeLineage(a, b *NativeInvocationEvidence) bool {
	return a != nil && b != nil && a.NoSkill == b.NoSkill && a.SessionRegistrationID == b.SessionRegistrationID &&
		a.SessionSignature == b.SessionSignature && a.AgentAuthority == b.AgentAuthority && reflect.DeepEqual(a.Contexts, b.Contexts)
}

func sameNativeCallEvidence(sec *SkillContextVerification, evidence *NativeInvocationEvidence) bool {
	return sec != nil && !sec.Invalid && sec.Native != nil && evidence != nil && reflect.DeepEqual(sec.Native.Evidence, evidence)
}

func nativeFollowupMatches(source, follow Receipt) bool {
	if source.NativeInvocation == nil && follow.NativeInvocation == nil {
		return source.SchemaVersion != "runtime-receipt/v3" && follow.SchemaVersion != "runtime-receipt/v3"
	}
	return source.SchemaVersion == "runtime-receipt/v3" && follow.SchemaVersion == "runtime-receipt/v3" &&
		receiptRuntimeTaskID(source) == receiptRuntimeTaskID(follow) && reflect.DeepEqual(source.NativeInvocation, follow.NativeInvocation)
}

func nativeReservationMatches(decision, reservation Receipt) bool {
	if decision.NativeInvocation == nil && reservation.NativeInvocation == nil {
		return decision.SchemaVersion != "runtime-receipt/v3" && reservation.SchemaVersion != "runtime-receipt/v3"
	}
	return decision.SchemaVersion == "runtime-receipt/v3" && reservation.SchemaVersion == "runtime-receipt/v3" &&
		receiptRuntimeTaskID(decision) == receiptRuntimeTaskID(reservation) && sameNativeLineage(decision.NativeInvocation, reservation.NativeInvocation) &&
		decision.NativeInvocation.CallID != reservation.NativeInvocation.CallID
}

func (e *Engine) nativeRetryAuthority(req Request, decision Receipt) (*SkillContextVerification, error) {
	sec := e.resolveSkillContext(req)
	if sec == nil || sec.Invalid || sec.Native == nil || decision.NativeInvocation == nil ||
		sec.Native.Evidence.CallID == decision.NativeInvocation.CallID || !sameNativeLineage(sec.Native.Evidence, decision.NativeInvocation) {
		return nil, correlationError("hold_native_retry_authority_changed")
	}
	return sec, nil
}

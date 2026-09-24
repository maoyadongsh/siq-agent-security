package rawcontent

import (
	"encoding/hex"
	"encoding/json"
	"io"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

const (
	MinPermitDuration = 10 * time.Second
	MaxPermitDuration = 5 * time.Minute
)

// CapturePermit is a short-lived signed proof that one active runtime session
// was matched to one raw-content Grant. It is not persisted and is not a bearer
// credential: capture still requires the same runtime identity credential.
type CapturePermit struct {
	SchemaVersion          string `json:"schema_version"`
	PermitID               string `json:"permit_id"`
	GrantID                string `json:"grant_id"`
	ExpectedGrantSignature string `json:"expected_grant_signature"`
	RuntimeIdentityRef     string `json:"runtime_identity_ref"`
	SessionRef             string `json:"session_ref"`
	BindingRef             string `json:"binding_ref"`
	TaskRef                string `json:"task_ref"`
	Kind                   string `json:"kind"`
	IssuedAt               string `json:"issued_at"`
	ExpiresAt              string `json:"expires_at"`
	SigningSchema          string `json:"signing_schema"`
	Signature              string `json:"signature"`
}

func capturePermitMap(permit CapturePermit) map[string]any {
	return map[string]any{
		"schema_version":           permit.SchemaVersion,
		"permit_id":                permit.PermitID,
		"grant_id":                 permit.GrantID,
		"expected_grant_signature": permit.ExpectedGrantSignature,
		"runtime_identity_ref":     permit.RuntimeIdentityRef,
		"session_ref":              permit.SessionRef,
		"binding_ref":              permit.BindingRef,
		"task_ref":                 permit.TaskRef,
		"kind":                     permit.Kind,
		"issued_at":                permit.IssuedAt,
		"expires_at":               permit.ExpiresAt,
		"signing_schema":           permit.SigningSchema,
	}
}

func validCapturePermit(permit CapturePermit, key *signing.Key) bool {
	issued, issuedErr := time.Parse(time.RFC3339Nano, permit.IssuedAt)
	expires, expiresErr := time.Parse(time.RFC3339Nano, permit.ExpiresAt)
	duration := expires.Sub(issued)
	return key != nil && issuedErr == nil && expiresErr == nil && duration > 0 && duration <= MaxPermitDuration &&
		permit.SchemaVersion == "local-raw-task-content-capture-permit/v1" &&
		len(permit.PermitID) == len("rawpermit-")+32 && permit.PermitID[:len("rawpermit-")] == "rawpermit-" && lowerHex(permit.PermitID[len("rawpermit-"):], 16) &&
		grantIDPattern.MatchString(permit.GrantID) && lowerHex(permit.ExpectedGrantSignature, 64) &&
		digestRefPattern.MatchString(permit.RuntimeIdentityRef) && digestRefPattern.MatchString(permit.SessionRef) &&
		digestRefPattern.MatchString(permit.BindingRef) && digestRefPattern.MatchString(permit.TaskRef) && allowedKind(permit.Kind) &&
		permit.SigningSchema == signing.SchemaLocalCanonicalV1 && lowerHex(permit.Signature, 64) &&
		signing.VerifyCanonical(key.Public(), capturePermitMap(permit), permit.Signature)
}

// IssueCapturePermit binds a current runtime identity/session/binding tuple to
// an active Grant. runtimeExpires is the already verified session deadline.
func (a *Authority) IssueCapturePermit(grantID, expectedGrantSignature, runtimeIdentityID, sessionID, bindingID, taskID, kind string, runtimeExpires time.Time, duration time.Duration, now time.Time) (CapturePermit, error) {
	authorityMu.Lock()
	defer authorityMu.Unlock()
	var permit CapturePermit
	identityRef, identityOK := hashRef(runtimeIdentityID)
	sessionRef, sessionOK := hashRef(sessionID)
	bindingRef, bindingOK := hashRef(bindingID)
	task, taskOK := taskRef(taskID)
	if now.IsZero() || runtimeExpires.IsZero() || duration < MinPermitDuration || duration > MaxPermitDuration || duration%time.Second != 0 ||
		!identityOK || !sessionOK || !bindingOK || !taskOK || !allowedKind(kind) || !lowerHex(expectedGrantSignature, 64) {
		return permit, ErrInvalid
	}
	grant, err := a.activeGrant(grantID, now)
	if err != nil {
		return permit, err
	}
	if grant.Signature != expectedGrantSignature || grant.TaskRef != task || !grantAllowsKind(grant, kind) {
		return permit, ErrDenied
	}
	grantExpires, _ := time.Parse(time.RFC3339Nano, grant.ExpiresAt)
	expires := now.Add(duration)
	if grantExpires.Before(expires) {
		expires = grantExpires
	}
	if runtimeExpires.Before(expires) {
		expires = runtimeExpires
	}
	if !now.Before(expires) {
		return permit, ErrExpired
	}
	idBytes := make([]byte, 16)
	if _, err := io.ReadFull(random, idBytes); err != nil {
		return CapturePermit{}, ErrState
	}
	permit = CapturePermit{
		SchemaVersion:          "local-raw-task-content-capture-permit/v1",
		PermitID:               "rawpermit-" + hex.EncodeToString(idBytes),
		GrantID:                grant.GrantID,
		ExpectedGrantSignature: grant.Signature,
		RuntimeIdentityRef:     identityRef,
		SessionRef:             sessionRef,
		BindingRef:             bindingRef,
		TaskRef:                task,
		Kind:                   kind,
		IssuedAt:               now.UTC().Format(time.RFC3339Nano),
		ExpiresAt:              expires.UTC().Format(time.RFC3339Nano),
		SigningSchema:          signing.SchemaLocalCanonicalV1,
	}
	permit.Signature, err = a.key.SignCanonical(capturePermitMap(permit))
	if err != nil {
		return CapturePermit{}, ErrState
	}
	return permit, nil
}

func grantAllowsKind(grant Grant, kind string) bool {
	for _, allowed := range grant.Kinds {
		if allowed == kind {
			return true
		}
	}
	return false
}

// CaptureWithPermit is the runtime-facing write path. It revalidates the
// permit, current Grant, revocation, runtime tuple, content kind and size while
// holding the same authority lock used by revocation.
func (a *Authority) CaptureWithPermit(permit CapturePermit, runtimeIdentityID, sessionID, bindingID, taskID string, content Prepared, now time.Time) (Envelope, error) {
	authorityMu.Lock()
	defer authorityMu.Unlock()
	identityRef, identityOK := hashRef(runtimeIdentityID)
	sessionRef, sessionOK := hashRef(sessionID)
	bindingRef, bindingOK := hashRef(bindingID)
	task, taskOK := taskRef(taskID)
	if now.IsZero() || !identityOK || !sessionOK || !bindingOK || !taskOK || !validCapturePermit(permit, a.key) {
		return Envelope{}, ErrInvalid
	}
	issued, _ := time.Parse(time.RFC3339Nano, permit.IssuedAt)
	expires, _ := time.Parse(time.RFC3339Nano, permit.ExpiresAt)
	if now.Before(issued) {
		return Envelope{}, ErrDenied
	}
	if !now.Before(expires) {
		return Envelope{}, ErrExpired
	}
	grant, err := a.activeGrant(permit.GrantID, now)
	if err != nil {
		return Envelope{}, err
	}
	if grant.Signature != permit.ExpectedGrantSignature || grant.TaskRef != task ||
		permit.RuntimeIdentityRef != identityRef || permit.SessionRef != sessionRef || permit.BindingRef != bindingRef || permit.TaskRef != task {
		return Envelope{}, ErrDenied
	}
	var prepared payload
	if json.Unmarshal(content.raw, &prepared) != nil || prepared.Kind != permit.Kind || !grantAllowsKind(grant, prepared.Kind) {
		return Envelope{}, ErrDenied
	}
	if len(content.raw) == 0 || len(content.raw) > grant.MaxPlaintextBytes {
		return Envelope{}, ErrDenied
	}
	return a.store.writeFromRuntime(taskID, content, time.Duration(grant.RetentionSeconds)*time.Second, now,
		&RuntimeSource{RuntimeIdentityRef: identityRef, SessionRef: sessionRef, BindingRef: bindingRef})
}

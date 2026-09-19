package runtimeidentity

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/intent"
)

const workBuddySessionPrefix = "workbuddy-session/v1:"
const workBuddyCallPrefix = "workbuddy-call/v1:"

func validWorkBuddyNativeID(value string) bool {
	if len(value) == 0 || len(value) > 256 || !utf8.ValidString(value) || strings.TrimSpace(value) != value {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

// WorkBuddySessionID namespaces a host ID; it does not attest a host epoch,
// authorization, or independence of child tasks collapsed by the host.
func WorkBuddySessionID(hostSession string) (string, error) {
	if !validWorkBuddyNativeID(hostSession) {
		return "", ErrInvalid
	}
	digest := sha256.Sum256([]byte("workbuddy-native-session/v1\x00" + hostSession))
	return workBuddySessionPrefix + hex.EncodeToString(digest[:]), nil
}

// WorkBuddyCallID binds the raw call namespace to its raw host session.
func WorkBuddyCallID(hostSession, hostCall string) (string, error) {
	if !validWorkBuddyNativeID(hostSession) || !validWorkBuddyNativeID(hostCall) {
		return "", ErrInvalid
	}
	digest := sha256.Sum256([]byte("workbuddy-native-call/v1\x00" + hostSession + "\x00" + hostCall))
	return workBuddyCallPrefix + hex.EncodeToString(digest[:]), nil
}

func validWorkBuddyDerivedID(value, prefix string) bool {
	return strings.HasPrefix(value, prefix) && len(value) == len(prefix)+64 && hexDigest.MatchString(strings.TrimPrefix(value, prefix))
}

func ValidWorkBuddyCallID(value string) bool {
	return validWorkBuddyDerivedID(value, workBuddyCallPrefix)
}

func validateManagedSession(r Record, session string) error {
	if r.Platform == "workbuddy" && (!validRecordProfile(r) || r.SchemaVersion != "local-runtime-identity/v2" || !validWorkBuddyDerivedID(session, workBuddySessionPrefix)) {
		return ErrInvalid
	}
	return intent.ValidateNativeSession(r.Platform, session)
}

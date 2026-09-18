package intent

import (
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"strings"
	"unicode/utf8"
)

const openClawSessionPrefix = "openclaw-session/v1:"

var openClawEpoch = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// OpenClawSessionID derives the versioned identity from trusted host metadata.
// The digest is not authority: callers still need an authenticated channel and
// a separately verified, immutable binding. Never take these inputs from a tool.
func OpenClawSessionID(key, epoch string) (string, error) {
	if key == "" || len(key) > 256 || !utf8.ValidString(key) || !openClawEpoch.MatchString(epoch) {
		return "", violation("native_session_epoch_required")
	}
	for _, ch := range key {
		if ch < 32 || ch == 127 {
			return "", violation("native_session_epoch_required")
		}
	}
	hash := sha256.Sum256([]byte("openclaw-native-session/v1\x00" + key + "\x00" + epoch))
	return openClawSessionPrefix + hex.EncodeToString(hash[:]), nil
}

// ValidateNativeSession rejects historical routing-key-only OpenClaw identities
// at live authority boundaries. Historical signed records remain readable.
func ValidateNativeSession(platform, session string) error {
	if platform != "openclaw" {
		return nil
	}
	if !strings.HasPrefix(session, openClawSessionPrefix) || len(session) != len(openClawSessionPrefix)+64 {
		return violation("native_session_epoch_required")
	}
	for _, ch := range session[len(openClawSessionPrefix):] {
		if !(ch >= '0' && ch <= '9' || ch >= 'a' && ch <= 'f') {
			return violation("native_session_epoch_required")
		}
	}
	return nil
}

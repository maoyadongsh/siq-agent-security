package effectevidence

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const MaxRecoveries = 64

type FileRecovery struct {
	SchemaVersion string `json:"schema_version"`
	ObservationID string `json:"observation_id"`
	PendingDigest string `json:"pending_digest"`
	Sequence      int    `json:"sequence"`
	PreviousHash  string `json:"previous_hash"`
	OwnerDigest   string `json:"owner_digest"`
	RecoveredAt   string `json:"recovered_at"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

func recoveryMap(value any) map[string]any {
	raw, _ := json.Marshal(value)
	decoded, _ := canon.Decode(raw)
	return decoded.(map[string]any)
}
func recoveryHash(value any) string {
	raw, _ := canon.Marshal(recoveryMap(value))
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
func (r FileRecovery) unsigned() map[string]any {
	value := recoveryMap(r)
	delete(value, "signature")
	return value
}

// RecoveryOwners verifies immutable ownership history. Callers must separately
// check every returned owner against durable revocations before resuming work.
func RecoveryOwners(p PendingFile, history []FileRecovery, pub ed25519.PublicKey, now time.Time) ([]string, error) {
	if !p.valid() || !signing.VerifyCanonical(pub, p.unsigned(), p.Signature) {
		return nil, ErrState
	}
	if len(history) > MaxRecoveries {
		return nil, ErrCapacity
	}
	owners := []string{p.OwnerDigest}
	previous := strings.Repeat("0", 64)
	pendingHash := recoveryHash(p)
	last, _ := time.Parse(time.RFC3339Nano, p.Before.CapturedAt)
	expiry, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	for index, r := range history {
		stamp, err := time.Parse(time.RFC3339Nano, r.RecoveredAt)
		if err != nil || len(r.RecoveredAt) > 64 || stamp.Before(last) || stamp.After(now) || !stamp.Before(expiry) || r.SchemaVersion != "file-observation-recovery/v1" || r.ObservationID != p.ID || r.PendingDigest != pendingHash || r.Sequence != index+1 || r.PreviousHash != previous || !digestPattern.MatchString(r.OwnerDigest) || r.OwnerDigest == owners[len(owners)-1] || r.SigningSchema != signing.SchemaLocalCanonicalV1 || !signing.VerifyCanonical(pub, r.unsigned(), r.Signature) {
			return nil, ErrState
		}
		owners = append(owners, r.OwnerDigest)
		last = stamp
		previous = recoveryHash(r)
	}
	return owners, nil
}
func newRecovery(p PendingFile, history []FileRecovery, owner string, key *signing.Key, now time.Time) (FileRecovery, error) {
	owners, err := RecoveryOwners(p, history, key.Public(), now)
	if err != nil {
		return FileRecovery{}, err
	}
	if len(history) >= MaxRecoveries {
		return FileRecovery{}, ErrCapacity
	}
	if !digestPattern.MatchString(owner) || owner == owners[len(owners)-1] {
		return FileRecovery{}, ErrConflict
	}
	previous := strings.Repeat("0", 64)
	if len(history) > 0 {
		previous = recoveryHash(history[len(history)-1])
	}
	r := FileRecovery{SchemaVersion: "file-observation-recovery/v1", ObservationID: p.ID, PendingDigest: recoveryHash(p), Sequence: len(history) + 1, PreviousHash: previous, OwnerDigest: owner, RecoveredAt: now.UTC().Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = key.SignCanonical(r.unsigned())
	if err != nil {
		return FileRecovery{}, ErrState
	}
	if _, err = RecoveryOwners(p, append(append([]FileRecovery{}, history...), r), key.Public(), now); err != nil {
		return FileRecovery{}, err
	}
	return r, nil
}

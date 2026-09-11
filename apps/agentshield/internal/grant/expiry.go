package grant

import (
	"errors"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

var (
	ErrExpired       = errors.New("grant: permission has expired")
	ErrInvalidExpiry = errors.New("grant: invalid expiration")
)

// ValidateLifetime uses a half-open interval. A missing deadline preserves the
// legacy unlimited lifetime; a malformed deadline never means unlimited.
func ValidateLifetime(g Grant, now time.Time) error {
	if g.ExpiresAt == nil {
		return nil
	}
	deadline, err := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
	if err != nil {
		return ErrInvalidExpiry
	}
	if !now.Before(deadline) {
		return ErrExpired
	}
	return nil
}

// SetExpiration changes pending scope only. Existing approval challenges bind
// expires_at, so changing it requires a new challenge and human approval.
func SetExpiration(g Grant, deadline *time.Time, now time.Time, key *signing.Key) (Grant, error) {
	if key == nil || g.Status != "pending_approval" {
		return g, errors.New("grant: expiration can only change before approval")
	}
	g.ExpiresAt = nil
	if deadline != nil {
		value := deadline.UTC().Format(time.RFC3339Nano)
		g.ExpiresAt = &value
		if err := ValidateLifetime(g, now); err != nil {
			return Grant{}, err
		}
	}
	resign(key, &g)
	return g, nil
}

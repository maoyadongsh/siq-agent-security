package skillcontext

import (
	"context"
	"errors"
	"io"
	"os"
	"sort"
	"strings"
	"time"
	"unicode"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

const InvocationRevokeRequestSchema = "local-skill-execution-context-revoke/v2"

type InvocationRevokeRequest ManagementRevokeRequest

func (r InvocationRevokeRequest) Valid() bool {
	return r.SchemaVersion == InvocationRevokeRequestSchema && hex128Pattern.MatchString(r.ExpectedContextSignature) &&
		validActor(r.ActorID) && r.ConfirmRevoke
}

// InvocationRecord is signed history, never a live execution authorization.
type InvocationRecord struct {
	Context    *InvocationContext    `json:"context"`
	Revocation *InvocationRevocation `json:"revocation"`
}

type InvocationPage struct {
	SchemaVersion string             `json:"schema_version"`
	Contexts      []InvocationRecord `json:"contexts"`
	NextAfter     string             `json:"next_after"`
}

func ValidInvocationHistoryQuery(installID, sessionID, after string, limit int) bool {
	return textValid(installID, 128) && (sessionID == "" || textValid(sessionID, 256)) &&
		strings.IndexFunc(installID, unicode.IsControl) < 0 && strings.IndexFunc(sessionID, unicode.IsControl) < 0 &&
		(after == "" || contextIDPattern.MatchString(after)) && limit >= 1 && limit <= 64
}

func invocationReadLock(ctx context.Context) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if mu.TryRLock() {
			return nil
		}
		timer := time.NewTimer(5 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

func (s *InvocationStore) managementRecord(id string) (*InvocationRecord, error) {
	c, err := s.read(id)
	if errors.Is(err, os.ErrNotExist) {
		return nil, invalid("skill_context_not_found")
	}
	if err != nil {
		return nil, err
	}
	r, err := s.readRevocation(c)
	if errors.Is(err, os.ErrNotExist) {
		r, err = nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &InvocationRecord{Context: c, Revocation: r}, nil
}

// ReadHistory verifies signatures, even after the original live grant expires.
func (s *InvocationStore) ReadHistory(ctx context.Context, id string) (*InvocationRecord, error) {
	if !contextIDPattern.MatchString(id) {
		return nil, invalid("")
	}
	if err := invocationReadLock(ctx); err != nil {
		return nil, err
	}
	defer mu.RUnlock()
	return s.managementRecord(id)
}

// ListHistory bounds both disk enumeration and the returned page. The cursor
// orders immutable IDs; it does not promise a snapshot across concurrent loads.
func (s *InvocationStore) ListHistory(ctx context.Context, installID, sessionID, after string, limit int) (*InvocationPage, error) {
	if !ValidInvocationHistoryQuery(installID, sessionID, after, limit) {
		return nil, invalid("")
	}
	if err := invocationReadLock(ctx); err != nil {
		return nil, err
	}
	defer mu.RUnlock()
	if err := invocationAncestors(s.contextDir()); err != nil {
		return nil, err
	}
	f, err := statefs.Open(s.contextDir())
	if err != nil {
		return nil, err
	}
	defer f.Close()
	entries, err := f.ReadDir(maxInvocations + 1)
	if (err != nil && err != io.EOF) || len(entries) > maxInvocations {
		return nil, invalid("skill_context_capacity")
	}
	ids := make([]string, 0, len(entries))
	for _, entry := range entries {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if strings.HasPrefix(entry.Name(), ".skill-invocation-") {
			continue
		}
		id, ok := strings.CutSuffix(entry.Name(), ".json")
		if !ok || !contextIDPattern.MatchString(id) || !entry.Type().IsRegular() {
			return nil, invalid("")
		}
		if id > after {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	out := &InvocationPage{SchemaVersion: "local-skill-context-management/v2", Contexts: []InvocationRecord{}}
	for _, id := range ids {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		r, err := s.managementRecord(id)
		if err != nil {
			return nil, err
		}
		if r.Context.Install.InstallID != installID || (sessionID != "" && r.Context.Subject.SessionID != sessionID) {
			continue
		}
		if len(out.Contexts) == limit {
			out.NextAfter = out.Contexts[len(out.Contexts)-1].Context.ContextID
			break
		}
		out.Contexts = append(out.Contexts, *r)
	}
	return out, nil
}

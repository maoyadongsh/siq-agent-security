package skillcontext

import (
	"context"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// BindInstallationStore runs once during daemon initialization, before serving.
// The engine and management API keep the same SEC store and signature authority.
func (s *Store) BindInstallationStore(installs *skillinstall.Store) error {
	mu.Lock()
	defer mu.Unlock()
	if installs == nil || s.installationStoreBound {
		return invalid("")
	}
	s.deps.ReadInstall = func(id string) (*skillinstall.Record, error) {
		return installs.RecordByID(context.Background(), id)
	}
	s.installationStoreBound = true
	return nil
}

// ManagementRecord is historical evidence, not a live authorization result.
type ManagementRecord struct {
	Context Context `json:"context"`
	Revoked bool    `json:"revoked"`
}

func (s *Store) ManagementRecords(ctx context.Context, installID string) ([]ManagementRecord, error) {
	mu.RLock()
	defer mu.RUnlock()
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if !textValid(installID, 128) {
		return nil, invalid("")
	}
	ids, err := s.contextIDs()
	if err != nil {
		return nil, err
	}
	out := []ManagementRecord{}
	for _, id := range ids {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		c, err := s.read(id)
		if err != nil {
			return nil, err
		}
		if c.Install.InstallID != installID {
			continue
		}
		revoked, err := s.revoked(id)
		if err != nil {
			return nil, err
		}
		if len(out) >= 64 {
			return nil, invalid("")
		}
		out = append(out, ManagementRecord{Context: *c, Revoked: revoked})
	}
	return out, nil
}

package state

import (
	"runtime"

	"siq-agent-security/apps/agentshield/internal/stateformat"
)

type MigrationPreview struct {
	Schema              string `json:"schema"`
	DirectoryID         string `json:"state_directory_id"`
	InstanceID          string `json:"instance_id"`
	Format              int    `json:"format_version"`
	Entries             int    `json:"backup_entries"`
	Bytes               int64  `json:"backup_bytes"`
	WindowsProfile      string `json:"windows_profile"`
	ServiceStopRequired bool   `json:"service_stop_required"`
}

// PreviewStateMigration performs the same private source inventory without
// acquiring a writer, publishing metadata or changing any existing authority.
// Apply always repeats these checks under the complete lifecycle lock set.
func (s *Store) PreviewStateMigration() (MigrationPreview, error) {
	var preview MigrationPreview
	compat, err := CheckStateCompatibility(s.Dir)
	if err != nil {
		return preview, err
	}
	if err := stateformat.RequirePath(s.Dir, false); err != nil {
		return preview, err
	}
	instance, err := s.ReadLocalInstance()
	if err != nil {
		return preview, err
	}
	directory, err := s.DirectoryID()
	if err != nil {
		return preview, err
	}
	entries, err := snapshotMigration(s.Dir)
	if err != nil {
		return preview, err
	}
	profile := "not_applicable"
	if runtime.GOOS == "windows" {
		profile = "activation_required"
		if err := stateformat.RequireWindowsProfile(s.Dir); err == nil {
			profile = "enabled"
		}
	}
	preview = MigrationPreview{Schema: "local-state-migration-preview/v1", DirectoryID: directory, InstanceID: instance.InstanceID, Format: compat.Format, Entries: len(entries), WindowsProfile: profile, ServiceStopRequired: true}
	if preview.Format == 0 {
		preview.Format = 1
	}
	for _, entry := range entries {
		preview.Bytes += entry.Size
	}
	return preview, nil
}

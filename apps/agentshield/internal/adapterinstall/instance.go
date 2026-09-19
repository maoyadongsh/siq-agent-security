package adapterinstall

import (
	"errors"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

// InstanceTarget is resolved by trusted CLI/server code, never from a raw HTTP path.
type InstanceTarget struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	ConfigDir string `json:"config_dir"`
}

func WithHermesInstance(opts Options, root hermeshome.Root) Options {
	opts.Instance = &InstanceTarget{ID: root.ID, Name: root.Name, ConfigDir: root.Path}
	return opts
}

// WithOpenClawInstance pins the platform's single default config root.
// OpenClaw has no multi-root discovery, so the root is the only input.
func WithOpenClawInstance(opts Options, root string) Options {
	opts.Instance = &InstanceTarget{ID: hermeshome.Identifier(root), Name: "default", ConfigDir: root}
	return opts
}

// DefaultConfigDir exposes the platform's default config root to trusted
// server code; multi-root discovery (Hermes) resolves roots independently.
func DefaultConfigDir(home, platform string) string {
	return configDir(home, platform)
}

// DefaultInstanceID is the content-derived instance ID of the platform's
// default config root, used when no explicit instance target is pinned.
func DefaultInstanceID(home, platform string) string {
	return hermeshome.Identifier(configDir(home, platform))
}
func (o Options) configRoot() string {
	if o.Instance != nil {
		return o.Instance.ConfigDir
	}
	return configDir(o.Home, o.Platform)
}
func operationKey(o Options) string {
	if o.Instance == nil || o.Platform == WorkBuddy || o.Platform == Hermes && o.Instance.ConfigDir == hermeshome.LegacyRoot(o.Home) {
		return o.Platform
	}
	return o.Platform + "-" + strings.TrimPrefix(o.Instance.ID, "hi-")
}
func (o Options) wrapperPath() string {
	if o.Instance != nil {
		return filepath.Join(o.configRoot(), "bin", "hermes-skills-install")
	}
	return filepath.Join(o.Home, ".local", "bin", "hermes-skills-install")
}
func validateInstance(o Options) error {
	if o.Instance == nil {
		return nil
	}
	if o.Platform != Hermes && o.Platform != OpenClaw && o.Platform != WorkBuddy {
		return errors.New("adapter: invalid instance target")
	}
	if !filepath.IsAbs(o.Instance.ConfigDir) || o.Instance.ID != hermeshome.Identifier(o.Instance.ConfigDir) || o.Instance.Name == "" {
		return errors.New("adapter: invalid instance target")
	}
	if o.Platform == WorkBuddy && o.Instance.ConfigDir != configDir(o.Home, WorkBuddy) {
		return errors.New("adapter: WorkBuddy instance differs from discovered configuration root")
	}
	return nil
}
func newestInstanceRecord(o Options) (*Record, error) {
	key := operationKey(o)
	if key == o.Platform {
		return newestRecord(o.StateDir, o.Platform)
	}
	record, found, err := latestManagedRecord(o.StateDir, o.Platform, key)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, errNoInstallRecord
	}
	return record, nil
}
func RecoverInstance(opts Options) (*Result, error) {
	if err := opts.normalise(); err != nil {
		return nil, err
	}
	return recoverOperation(opts.StateDir, opts.Platform, operationKey(opts), &opts)
}

// WorkBuddy keeps one historical operation key across config-root changes.
// Compare only the authenticated plan, while recoverOperation holds its writer;
// claim.Record is an unauthenticated summary and cannot authorize recovery.
func workBuddyRecoveryMatches(p *Plan, selected Options) bool {
	root := selected.configRoot()
	old := p.payload.Options
	record := p.payload.Record
	paths := hostConfigPaths(record)
	if old.Platform != WorkBuddy || record.Platform != WorkBuddy || len(paths) != 1 || paths[0] != filepath.Join(root, "settings.json") {
		return false
	}
	id := hermeshome.Identifier(root)
	if old.Instance != nil {
		return old.Instance.ConfigDir == root && old.Instance.ID == id && record.ConfigDir == root && record.InstanceID == id
	}
	// Legacy plans did not freeze an InstanceTarget. Their sole recorded host
	// config path above pins the old root without consulting today's environment.
	return (record.ConfigDir == "" || record.ConfigDir == root) && (record.InstanceID == "" || record.InstanceID == id)
}

// Package adapterinstall writes and restores host-platform adapter files
// (dev-spec §4). It mutates user config only through a reviewed recovery plan and
// holds no policy, rules or signing keys.
package adapterinstall

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"embed"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

//go:embed assets/hermes/plugin.yaml assets/hermes/__init__.py assets/openclaw/package.json assets/openclaw/index.ts assets/openclaw/openclaw.plugin.json
var embedded embed.FS

// Platforms the installer knows.
const (
	OpenClaw  = "openclaw"
	Hermes    = "hermes"
	CodeBuddy = "codebuddy"
	Trae      = "trae"
)

// Options for Install / Uninstall.
type Options struct {
	RuntimeIdentityID string          `json:"runtime_identity_id,omitempty"`
	Instance          *InstanceTarget `json:"instance,omitempty"`
	NativeEnable      bool            `json:"native_enable,omitempty"`
	NativeCLI         string          `json:"native_cli,omitempty"`
	Platform          string          // required
	Home              string          // override os.UserHomeDir (tests)
	StateDir          string
	Binary            string // absolute path to agentshield
	Endpoint          string
	Mode              string
	From              string // extra adapters/runtime tree (takes precedence over embed)
	Now               time.Time
}

// Record is the uninstall recipe in versioned adapter operation claims.
// Historical backups/adapters records remain readable for migration.
type Record struct {
	RuntimeIdentityID string              `json:"runtime_identity_id,omitempty"`
	NativeOriginal    *NativeRegistration `json:"native_original,omitempty"`
	NativeConfigHash  string              `json:"native_config_hash,omitempty"`
	NativeCLI         string              `json:"native_cli,omitempty"`
	NativeCLIHash     string              `json:"native_cli_hash,omitempty"`
	InstanceID        string              `json:"instance_id,omitempty"`
	ConfigDir         string              `json:"config_dir,omitempty"`
	Platform          string              `json:"platform"`
	InstalledAt       string              `json:"installed_at"`
	Binary            string              `json:"binary"`
	Created           []string            `json:"created"`
	Modified          map[string]string   `json:"modified"`          // dest → backup path
	Written           map[string]string   `json:"written,omitempty"` // installed file digests, for safe uninstall
	OriginalModes     map[string]uint32   `json:"original_modes,omitempty"`
	Note              string              `json:"note,omitempty"`
}

// Result of an install/uninstall.
type Result struct {
	Platform string        `json:"platform"`
	Action   string        `json:"action"`
	Paths    []string      `json:"paths"`
	Note     string        `json:"note,omitempty"`
	Record   *Record       `json:"record,omitempty"`
	Recovery *RecoveryPlan `json:"recovery,omitempty"`
}

// RecoveryPlan is returned when live config cannot be surgically edited
// (DEV07-B). Callers must not treat this as a successful silent rollback.
type RecoveryPlan struct {
	Reason           string   `json:"reason"`
	LivePath         string   `json:"live_path"`
	OriginalSnapshot string   `json:"original_snapshot,omitempty"`
	SuggestedActions []string `json:"suggested_actions"`
}

var known = map[string]bool{OpenClaw: true, Hermes: true, CodeBuddy: true, Trae: true}

// Detect lists platforms whose well-known config dir exists under home.
func Detect(home string) []string {
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	var out []string
	for _, p := range []string{OpenClaw, Hermes, CodeBuddy, Trae} {
		if p == CodeBuddy && validateCodeBuddyConfigDir() != nil {
			continue
		}
		if st, err := os.Stat(configDir(home, p)); err == nil && st.IsDir() {
			out = append(out, p)
		}
	}
	return out
}

func configDir(home, platform string) string {
	switch platform {
	case OpenClaw:
		return filepath.Join(home, ".openclaw")
	case Hermes:
		return filepath.Join(home, ".hermes")
	case CodeBuddy:
		if dir := os.Getenv("CODEBUDDY_CONFIG_DIR"); dir != "" {
			return filepath.Clean(dir)
		}
		return filepath.Join(home, ".codebuddy")
	case Trae:
		return filepath.Join(home, ".trae")
	}
	return ""
}

// A bad override must never silently select a different user's configuration.
// This is path validation, not protection against hostile concurrent renames.
func validateCodeBuddyConfigDir() error {
	dir := os.Getenv("CODEBUDDY_CONFIG_DIR")
	if dir == "" {
		return nil
	}
	if !filepath.IsAbs(dir) {
		return errors.New("adapter: CODEBUDDY_CONFIG_DIR must be an absolute path")
	}
	for p := filepath.Clean(dir); ; p = filepath.Dir(p) {
		info, err := os.Lstat(p)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return errors.New("adapter: cannot inspect CODEBUDDY_CONFIG_DIR")
		}
		if err == nil && (!info.IsDir() || info.Mode()&os.ModeSymlink != 0) {
			return errors.New("adapter: CODEBUDDY_CONFIG_DIR requires directory ancestors without symlinks")
		}
		if filepath.Dir(p) == p {
			return nil
		}
	}
}

// Install writes adapter files for one platform. Trae is audit-only: no files.
func Install(opts Options) (*Result, error) {
	plan, err := Prepare(opts, "install")
	if err != nil {
		return nil, err
	}
	return Apply(plan)
}

// Uninstall removes this product's hooks/files. JSON host configs are edited
// surgically so post-install user fields survive (DEV07-B). On conflict
// (bad JSON / symlink), returns an error plus RecoveryPlan — no silent
// full-file rollback onto live user config.
func Uninstall(opts Options) (*Result, error) {
	plan, err := Prepare(opts, "uninstall")
	if err != nil {
		var recovery *RecoveryPlan
		if errors.As(err, &recovery) {
			return &Result{Platform: opts.Platform, Action: "uninstall_conflict", Recovery: recovery}, err
		}
		return nil, err
	}
	return Apply(plan)
}

func conflictRecovery(live, orig string, cause error) error {
	plan := &RecoveryPlan{
		Reason:           cause.Error(),
		LivePath:         live,
		OriginalSnapshot: orig,
		SuggestedActions: []string{
			"inspect the live file and original snapshot",
			"manually remove product hooks or restore from the .siq-agent-security.orig snapshot",
			"do not overwrite live user edits without review",
		},
	}
	return plan
}

func (p *RecoveryPlan) Error() string {
	if p == nil {
		return "adapter: recovery required"
	}
	return "adapter: uninstall conflict: " + p.Reason
}

func (o *Options) normalise() error {
	if !known[o.Platform] {
		return fmt.Errorf("adapter: unknown platform %q", o.Platform)
	}
	if o.Platform == CodeBuddy {
		if err := validateCodeBuddyConfigDir(); err != nil {
			return err
		}
	}
	if o.Home == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		o.Home = h
	}
	if o.StateDir == "" {
		d, err := state.DefaultDir()
		if err != nil {
			return err
		}
		o.StateDir = d
	}
	if o.Binary == "" {
		exe, err := os.Executable()
		if err != nil {
			return err
		}
		o.Binary, _ = filepath.Abs(exe)
	}
	if o.Endpoint == "" {
		o.Endpoint = "http://127.0.0.1:47611"
	}
	if o.Mode == "" {
		o.Mode = "block"
	}
	switch o.Mode {
	case "block", "warn", "audit_only":
	default:
		return fmt.Errorf("adapter: unknown enforcement_mode %q (want block|warn|audit_only)", o.Mode)
	}
	if o.From != "" {
		var err error
		o.From, err = filepath.Abs(o.From)
		if err != nil {
			return err
		}
	}
	if err := validateInstance(*o); err != nil {
		return err
	}
	if o.Now.IsZero() {
		o.Now = time.Now().UTC()
	}
	return nil
}

func upsertHook(existing any, command string) []any {
	entry := map[string]any{
		"matcher": ".*",
		"hooks": []any{
			map[string]any{"type": "command", "command": command, "timeout": 5},
		},
	}
	list, _ := existing.([]any)
	for _, item := range list {
		m, _ := item.(map[string]any)
		inner, _ := m["hooks"].([]any)
		for _, h := range inner {
			hm, _ := h.(map[string]any)
			if c, _ := hm["command"].(string); strings.Contains(c, "hook codebuddy") && product.Mentions(c) {
				hm["command"] = command
				return list
			}
		}
	}
	return append(list, entry)
}

// originalSuffix is the immutable first-seen user content snapshot (DEV07-A).
// Reinstall must never overwrite it. Uninstall prefers surgical live edits
// (DEV07-B); the snapshot remains for conflict recovery.
const originalSuffix = ".siq-agent-security.orig"

func readJSONObject(path string) (map[string]any, error) {
	if err := refuseSymlink(path); err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	trim := strings.TrimSpace(string(data))
	if trim == "" {
		return map[string]any{}, nil
	}
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("adapter: refuse to rewrite invalid JSON at %s: %w", path, err)
	}
	if doc == nil {
		return nil, fmt.Errorf("adapter: refuse to rewrite JSON null at %s", path)
	}
	return doc, nil
}

func refuseSymlink(path string) error {
	fi, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if fi.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("adapter: refuse to modify symlink %s", path)
	}
	return nil
}

func readAsset(opts Options, rel string) ([]byte, error) {
	parts := strings.SplitN(rel, "/", 2)
	if opts.From != "" && len(parts) == 2 {
		for _, path := range []string{filepath.Join(opts.From, parts[0]+"-agentshield", parts[1]), filepath.Join(opts.From, rel)} {
			image, err := readImage(opts.From, path)
			if err != nil {
				return nil, err
			}
			if image.Exists {
				return image.Data, nil
			}
		}
	}
	return embedded.ReadFile("assets/" + rel)
}

var errNoInstallRecord = errors.New("adapter: no install record")

func newestRecord(stateDir, platform string) (*Record, error) {
	if record, found, err := latestManagedRecord(stateDir, platform); found || err != nil {
		return record, err
	}
	dir := filepath.Join(stateDir, "backups", "adapters")
	entries, err := os.ReadDir(dir)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("%w for %s", errNoInstallRecord, platform)
		}
		return nil, err
	}
	var latest string
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, platform+".") && strings.HasSuffix(name, ".json") && name > latest {
			latest = name
		}
	}
	if latest == "" {
		return nil, fmt.Errorf("%w for %s", errNoInstallRecord, platform)
	}
	raw, err := privateRead(filepath.Join(dir, latest), 2<<20)
	if err != nil {
		return nil, err
	}
	var rec Record
	if err := json.Unmarshal(raw, &rec); err != nil {
		return nil, err
	}
	if rec.Platform != platform || rec.Binary == "" || rec.InstalledAt == "" {
		return nil, errors.New("adapter: invalid legacy install record")
	}
	return &rec, nil
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func appendUnique(ss []string, v string) []string {
	for _, s := range ss {
		if s == v {
			return ss
		}
	}
	return append(ss, v)
}

// Status reports whether a platform currently looks installed.
func Status(opts Options) (*Result, error) {
	if opts.Platform == CodeBuddy {
		if err := validateCodeBuddyConfigDir(); err != nil {
			return nil, err
		}
	}
	if opts.Home == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		opts.Home = h
	}
	if !known[opts.Platform] {
		return nil, errors.New("adapter: unknown platform")
	}
	note := "not installed"
	var paths []string
	switch opts.Platform {
	case Hermes:
		for _, leaf := range []string{product.PluginDir(), product.LegacyName} {
			p := filepath.Join(opts.configRoot(), "plugins", leaf, "plugin.yaml")
			if exists(p) {
				note = "installed"
				paths = []string{filepath.Dir(p)}
				break
			}
		}
	case OpenClaw:
		for _, leaf := range []string{product.PluginDir(), product.LegacyName} {
			p := filepath.Join(opts.configRoot(), "plugins", leaf, "index.ts")
			if exists(p) {
				note = "installed"
				paths = []string{filepath.Dir(p)}
				break
			}
		}
	case CodeBuddy:
		p := filepath.Join(opts.configRoot(), "settings.json")
		if exists(p) {
			raw, _ := os.ReadFile(p)
			if strings.Contains(string(raw), "hook codebuddy") && product.Mentions(string(raw)) {
				note = "installed"
				paths = []string{p}
			}
		}
	case Trae:
		note = "audit_only"
	}
	return &Result{Platform: opts.Platform, Action: "status", Paths: paths, Note: note}, nil
}

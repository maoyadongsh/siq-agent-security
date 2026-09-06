// Package adapterinstall writes and restores host-platform adapter files
// (dev-spec §4). It mutates user config only after a timestamped backup and
// holds no policy, rules or signing keys.
package adapterinstall

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"embed"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

//go:embed assets/hermes/plugin.yaml assets/hermes/__init__.py assets/openclaw/package.json assets/openclaw/index.ts
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
	Platform string // required
	Home     string // override os.UserHomeDir (tests)
	StateDir string
	Binary   string // absolute path to agentshield
	Endpoint string
	Mode     string
	From     string // extra adapters/runtime tree (takes precedence over embed)
	Now      time.Time
}

// Record is the uninstall recipe written under <state>/backups/adapters/.
type Record struct {
	Platform    string            `json:"platform"`
	InstalledAt string            `json:"installed_at"`
	Binary      string            `json:"binary"`
	Created     []string          `json:"created"`
	Modified    map[string]string `json:"modified"` // dest → backup path
	Note        string            `json:"note,omitempty"`
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
		return filepath.Join(home, ".codebuddy")
	case Trae:
		return filepath.Join(home, ".trae")
	}
	return ""
}

// Install writes adapter files for one platform. Trae is audit-only: no files.
func Install(opts Options) (*Result, error) {
	if err := opts.normalise(); err != nil {
		return nil, err
	}
	if opts.Platform == Trae {
		return &Result{Platform: Trae, Action: "skipped", Note: "Trae has no tool hook; L0 audit only. Run " + product.Name + " admit before installing a skill."}, nil
	}
	st, err := state.Open(opts.StateDir)
	if err != nil {
		return nil, err
	}
	rec := &Record{
		Platform:    opts.Platform,
		InstalledAt: opts.Now.UTC().Format(time.RFC3339),
		Binary:      opts.Binary,
		Modified:    map[string]string{},
	}
	var paths []string
	switch opts.Platform {
	case Hermes:
		paths, err = installHermes(opts, rec)
	case OpenClaw:
		paths, err = installOpenClaw(opts, rec)
	case CodeBuddy:
		paths, err = installCodeBuddy(opts, rec)
	default:
		return nil, fmt.Errorf("adapter: unknown platform %q", opts.Platform)
	}
	if err != nil {
		return nil, err
	}
	raw, _ := json.MarshalIndent(rec, "", "  ")
	stamp := opts.Now.UTC().Format("20060102T150405Z")
	backup := filepath.Join(st.Dir, "backups", "adapters", opts.Platform+"."+stamp+".json")
	if err := os.MkdirAll(filepath.Dir(backup), 0o700); err != nil {
		return nil, err
	}
	if err := os.WriteFile(backup, raw, 0o600); err != nil {
		return nil, err
	}
	return &Result{Platform: opts.Platform, Action: "install", Paths: paths, Record: rec}, nil
}

// Uninstall removes this product's hooks/files. JSON host configs are edited
// surgically so post-install user fields survive (DEV07-B). On conflict
// (bad JSON / symlink), returns an error plus RecoveryPlan — no silent
// full-file rollback onto live user config.
func Uninstall(opts Options) (*Result, error) {
	if err := opts.normalise(); err != nil {
		return nil, err
	}
	if opts.Platform == Trae {
		return &Result{Platform: Trae, Action: "skipped", Note: "nothing was installed for Trae"}, nil
	}
	rec, err := newestRecord(opts.StateDir, opts.Platform)
	if err != nil {
		return nil, err
	}
	switch opts.Platform {
	case CodeBuddy:
		return uninstallCodeBuddy(opts, rec)
	case OpenClaw:
		return uninstallOpenClaw(opts, rec)
	case Hermes:
		return uninstallHermes(opts, rec)
	default:
		return nil, fmt.Errorf("adapter: unknown platform %q", opts.Platform)
	}
}

func uninstallCodeBuddy(opts Options, rec *Record) (*Result, error) {
	settings := filepath.Join(configDir(opts.Home, CodeBuddy), "settings.json")
	if err := stripCodeBuddyHooks(settings, rec); err != nil {
		var recov *RecoveryPlan
		if errors.As(err, &recov) {
			return &Result{Platform: CodeBuddy, Action: "uninstall_conflict", Record: rec, Recovery: recov, Note: recov.Reason}, err
		}
		return nil, err
	}
	removeCreatedExcept(rec, settings)
	return &Result{Platform: CodeBuddy, Action: "uninstall", Paths: []string{settings}, Record: rec, Note: "surgical: removed product hooks; preserved other settings"}, nil
}

func stripCodeBuddyHooks(settings string, rec *Record) error {
	doc, err := readJSONObject(settings)
	if err != nil {
		return conflictRecovery(settings, rec.Modified[settings], err)
	}
	hooks, _ := doc["hooks"].(map[string]any)
	if hooks != nil {
		for _, event := range []string{"PreToolUse", "PostToolUse"} {
			if cleaned, ok := removeProductHookEntries(hooks[event]); ok {
				if len(cleaned) == 0 {
					delete(hooks, event)
				} else {
					hooks[event] = cleaned
				}
			}
		}
		if len(hooks) == 0 {
			delete(doc, "hooks")
		} else {
			doc["hooks"] = hooks
		}
	}
	if len(doc) == 0 && rec.Modified[settings] == "" {
		// We created an empty-ish file solely for hooks.
		_ = os.Remove(settings)
		return nil
	}
	return writeAtomicJSON(settings, doc)
}

func removeProductHookEntries(existing any) ([]any, bool) {
	list, ok := existing.([]any)
	if !ok {
		return nil, false
	}
	var out []any
	changed := false
	for _, item := range list {
		m, _ := item.(map[string]any)
		inner, _ := m["hooks"].([]any)
		var kept []any
		for _, h := range inner {
			hm, _ := h.(map[string]any)
			c, _ := hm["command"].(string)
			if strings.Contains(c, "hook codebuddy") && product.Mentions(c) {
				changed = true
				continue
			}
			kept = append(kept, h)
		}
		if len(kept) == 0 {
			changed = true
			continue
		}
		m["hooks"] = kept
		out = append(out, m)
	}
	return out, changed || len(out) != len(list)
}

func uninstallOpenClaw(opts Options, rec *Record) (*Result, error) {
	ocPath := filepath.Join(configDir(opts.Home, OpenClaw), "openclaw.json")
	if exists(ocPath) || rec.Modified[ocPath] != "" {
		if err := stripOpenClawInstallPolicy(ocPath, rec); err != nil {
			var recov *RecoveryPlan
			if errors.As(err, &recov) {
				return &Result{Platform: OpenClaw, Action: "uninstall_conflict", Record: rec, Recovery: recov, Note: recov.Reason}, err
			}
			return nil, err
		}
	}
	cfgPath := filepath.Join(configDir(opts.Home, OpenClaw), product.Name+".json")
	removeOwnedFile(cfgPath, rec)
	pluginRoot := filepath.Join(configDir(opts.Home, OpenClaw), "plugins", product.PluginDir())
	removeCreatedMatching(rec, pluginRoot)
	for _, p := range rec.Created {
		if p == ocPath {
			continue
		}
		_ = os.RemoveAll(p)
	}
	return &Result{Platform: OpenClaw, Action: "uninstall", Paths: []string{ocPath, pluginRoot}, Record: rec, Note: "surgical: removed installPolicy and product plugin; preserved other openclaw.json fields"}, nil
}

func stripOpenClawInstallPolicy(ocPath string, rec *Record) error {
	doc, err := readJSONObject(ocPath)
	if err != nil {
		return conflictRecovery(ocPath, rec.Modified[ocPath], err)
	}
	if sec, ok := doc["security"].(map[string]any); ok {
		delete(sec, "installPolicy")
		if len(sec) == 0 {
			delete(doc, "security")
		} else {
			doc["security"] = sec
		}
	}
	if len(doc) == 0 && rec.Modified[ocPath] == "" {
		_ = os.Remove(ocPath)
		return nil
	}
	return writeAtomicJSON(ocPath, doc)
}

func uninstallHermes(opts Options, rec *Record) (*Result, error) {
	pluginRoot := filepath.Join(configDir(opts.Home, Hermes), "plugins", product.PluginDir())
	wrapper := filepath.Join(opts.Home, ".local", "bin", "hermes-skills-install")
	for dest, bak := range rec.Modified {
		if dest == wrapper {
			// Restore pre-install wrapper if any; otherwise delete below via Created.
			if err := restoreFromSnapshot(dest, bak); err != nil {
				return nil, err
			}
		}
	}
	removeCreatedMatching(rec, pluginRoot)
	for _, p := range rec.Created {
		_ = os.RemoveAll(p)
	}
	if exists(wrapper) && rec.Modified[wrapper] == "" {
		// Install created the wrapper (may be listed under Created or only Paths).
		raw, _ := os.ReadFile(wrapper)
		if product.Mentions(string(raw)) && strings.Contains(string(raw), "hermes-skills-install") {
			_ = os.Remove(wrapper)
		}
	}
	return &Result{Platform: Hermes, Action: "uninstall", Paths: []string{pluginRoot}, Record: rec, Note: "removed product plugin; restored prior wrapper if snapshotted"}, nil
}

func restoreFromSnapshot(dest, bak string) error {
	if err := refuseSymlink(dest); err != nil {
		return err
	}
	if err := refuseSymlink(bak); err != nil {
		return err
	}
	data, err := os.ReadFile(bak)
	if err != nil {
		return err
	}
	return writeAtomic(dest, data, 0o600)
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

func writeAtomicJSON(path string, doc map[string]any) error {
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	return writeAtomic(path, append(raw, '\n'), 0o600)
}

func removeOwnedFile(path string, rec *Record) {
	if rec.Modified[path] != "" {
		_ = restoreFromSnapshot(path, rec.Modified[path])
		return
	}
	for _, c := range rec.Created {
		if c == path {
			_ = os.RemoveAll(path)
			return
		}
	}
	if exists(path) {
		raw, _ := os.ReadFile(path)
		if product.Mentions(string(raw)) {
			_ = os.Remove(path)
		}
	}
}

func removeCreatedExcept(rec *Record, keep string) {
	for _, p := range rec.Created {
		if p == keep {
			continue
		}
		_ = os.RemoveAll(p)
	}
}

func removeCreatedMatching(rec *Record, prefix string) {
	for _, p := range rec.Created {
		if p == prefix || strings.HasPrefix(p, prefix+string(filepath.Separator)) {
			_ = os.RemoveAll(p)
		}
	}
}

func (o *Options) normalise() error {
	if !known[o.Platform] {
		return fmt.Errorf("adapter: unknown platform %q", o.Platform)
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
	if o.Now.IsZero() {
		o.Now = time.Now().UTC()
	}
	return nil
}

func installHermes(opts Options, rec *Record) ([]string, error) {
	root := filepath.Join(configDir(opts.Home, Hermes), "plugins", product.PluginDir())
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	pluginExisted := exists(filepath.Join(root, "plugin.yaml"))
	var paths []string
	for _, name := range []string{"plugin.yaml", "__init__.py"} {
		data, err := readAsset(opts, "hermes/"+name)
		if err != nil {
			return nil, err
		}
		dest := filepath.Join(root, name)
		if err := writeNewOrReplace(dest, data, rec); err != nil {
			return nil, err
		}
		paths = append(paths, dest)
	}
	cfg := map[string]any{
		"endpoint":         opts.Endpoint,
		"token_path":       filepath.Join(opts.StateDir, "token"),
		"enforcement_mode": opts.Mode,
		"timeout_s":        5,
	}
	raw, _ := json.MarshalIndent(cfg, "", "  ")
	dest := filepath.Join(root, "config.json")
	if err := writeNewOrReplace(dest, append(raw, '\n'), rec); err != nil {
		return nil, err
	}
	paths = append(paths, dest)
	if !pluginExisted {
		rec.Created = appendUnique(rec.Created, root)
	}
	wrapper, err := writeHermesWrapper(opts, rec)
	if err != nil {
		return nil, err
	}
	if wrapper != "" {
		paths = append(paths, wrapper)
	}
	return paths, nil
}

func writeHermesWrapper(opts Options, rec *Record) (string, error) {
	if runtime.GOOS == "windows" {
		return "", nil
	}
	dir := filepath.Join(opts.Home, ".local", "bin")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	dest := filepath.Join(dir, "hermes-skills-install")
	body := fmt.Sprintf(`#!/bin/sh
set -eu
BIN=%q
if [ $# -lt 1 ]; then
  echo "usage: hermes-skills-install <skill-src> [hermes skills install args...]" >&2
  exit 2
fi
SRC=$1
shift || true
set +e
"$BIN" admit "$SRC"
status=$?
set -e
if [ "$status" -eq 3 ]; then
  echo "%s: skill quarantined; refusing hermes skills install" >&2
  exit 3
fi
if [ "$status" -ne 0 ]; then
  echo "%s: admit failed (exit $status)" >&2
  exit "$status"
fi
exec hermes skills install "$SRC" "$@"
`, opts.Binary, product.Name, product.Name)
	if err := writeNewOrReplace(dest, []byte(body), rec); err != nil {
		return "", err
	}
	_ = os.Chmod(dest, 0o700)
	return dest, nil
}

func installOpenClaw(opts Options, rec *Record) ([]string, error) {
	root := filepath.Join(configDir(opts.Home, OpenClaw), "plugins", product.PluginDir())
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	pluginExisted := exists(filepath.Join(root, "index.ts"))
	var paths []string
	for _, name := range []string{"package.json", "index.ts"} {
		data, err := readAsset(opts, "openclaw/"+name)
		if err != nil {
			return nil, err
		}
		dest := filepath.Join(root, name)
		if err := writeNewOrReplace(dest, data, rec); err != nil {
			return nil, err
		}
		paths = append(paths, dest)
	}
	cfg := map[string]any{
		"endpoint":        opts.Endpoint,
		"tokenPath":       filepath.Join(opts.StateDir, "token"),
		"enforcementMode": opts.Mode,
		"timeoutMs":       5000,
	}
	raw, _ := json.MarshalIndent(cfg, "", "  ")
	cfgPath := filepath.Join(configDir(opts.Home, OpenClaw), product.Name+".json")
	if err := writeNewOrReplace(cfgPath, append(raw, '\n'), rec); err != nil {
		return nil, err
	}
	paths = append(paths, cfgPath)

	ocPath := filepath.Join(configDir(opts.Home, OpenClaw), "openclaw.json")
	doc, err := readJSONObject(ocPath)
	if err != nil {
		return nil, err
	}
	sec, _ := doc["security"].(map[string]any)
	if sec == nil {
		sec = map[string]any{}
	}
	sec["installPolicy"] = map[string]any{
		"enabled": true,
		"targets": []any{"skill", "plugin"},
		"exec": map[string]any{
			"source":      "exec",
			"command":     opts.Binary,
			"args":        []any{"policy-exec"},
			"timeoutMs":   10000,
			"trustedDirs": []any{filepath.Dir(opts.Binary)},
			"passEnv":     []any{product.EnvStateDir, product.EnvStateDirOld, "HOME", "PATH"},
		},
	}
	doc["security"] = sec
	if err := backupAndWriteJSON(ocPath, doc, rec); err != nil {
		return nil, err
	}
	paths = append(paths, ocPath)
	if !pluginExisted {
		rec.Created = appendUnique(rec.Created, root)
	}
	return paths, nil
}

func installCodeBuddy(opts Options, rec *Record) ([]string, error) {
	dir := configDir(opts.Home, CodeBuddy)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	settingsPath := filepath.Join(dir, "settings.json")
	doc, err := readJSONObject(settingsPath)
	if err != nil {
		return nil, err
	}
	cmd := opts.Binary + " hook codebuddy"
	hooks, _ := doc["hooks"].(map[string]any)
	if hooks == nil {
		hooks = map[string]any{}
	}
	for _, event := range []string{"PreToolUse", "PostToolUse"} {
		hooks[event] = upsertHook(hooks[event], cmd)
	}
	doc["hooks"] = hooks
	if err := backupAndWriteJSON(settingsPath, doc, rec); err != nil {
		return nil, err
	}
	return []string{settingsPath}, nil
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

func backupAndWriteJSON(path string, doc map[string]any, rec *Record) error {
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	if err := captureOriginal(path, rec); err != nil {
		return err
	}
	return writeAtomic(path, raw, 0o600)
}

func writeNewOrReplace(dest string, data []byte, rec *Record) error {
	if err := os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
		return err
	}
	if err := captureOriginal(dest, rec); err != nil {
		return err
	}
	return writeAtomic(dest, data, 0o600)
}

// originalSuffix is the immutable first-seen user content snapshot (DEV07-A).
// Reinstall must never overwrite it. Uninstall prefers surgical live edits
// (DEV07-B); the snapshot remains for conflict recovery.
const originalSuffix = ".siq-agent-security.orig"

func captureOriginal(path string, rec *Record) error {
	if rec.Modified[path] != "" {
		return nil
	}
	if err := refuseSymlink(path); err != nil {
		return err
	}
	orig := path + originalSuffix
	if _, err := os.Lstat(orig); err == nil {
		if err := refuseSymlink(orig); err != nil {
			return err
		}
		rec.Modified[path] = orig
		return nil
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if !exists(path) {
		rec.Created = appendUnique(rec.Created, path)
		return nil
	}
	src, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(orig, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if os.IsExist(err) {
			rec.Modified[path] = orig
			return nil
		}
		return err
	}
	defer f.Close()
	if _, err := f.Write(src); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	rec.Modified[path] = orig
	return nil
}

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

func writeAtomic(path string, data []byte, mode os.FileMode) error {
	if err := refuseSymlink(path); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".siq-adapter-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, mode); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		return err
	}
	ok = true
	return nil
}

func readAsset(opts Options, rel string) ([]byte, error) {
	parts := strings.SplitN(rel, "/", 2)
	if opts.From != "" && len(parts) == 2 {
		p := filepath.Join(opts.From, parts[0]+"-agentshield", parts[1])
		if data, err := os.ReadFile(p); err == nil {
			return data, nil
		}
		p = filepath.Join(opts.From, rel)
		if data, err := os.ReadFile(p); err == nil {
			return data, nil
		}
	}
	return embedded.ReadFile("assets/" + rel)
}

func newestRecord(stateDir, platform string) (*Record, error) {
	dir := filepath.Join(stateDir, "backups", "adapters")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("adapter: no install record for %s", platform)
	}
	var latest string
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, platform+".") && strings.HasSuffix(name, ".json") && name > latest {
			latest = name
		}
	}
	if latest == "" {
		return nil, fmt.Errorf("adapter: no install record for %s", platform)
	}
	raw, err := os.ReadFile(filepath.Join(dir, latest))
	if err != nil {
		return nil, err
	}
	var rec Record
	if err := json.Unmarshal(raw, &rec); err != nil {
		return nil, err
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
			p := filepath.Join(configDir(opts.Home, Hermes), "plugins", leaf, "plugin.yaml")
			if exists(p) {
				note = "installed"
				paths = []string{filepath.Dir(p)}
				break
			}
		}
	case OpenClaw:
		for _, leaf := range []string{product.PluginDir(), product.LegacyName} {
			p := filepath.Join(configDir(opts.Home, OpenClaw), "plugins", leaf, "index.ts")
			if exists(p) {
				note = "installed"
				paths = []string{filepath.Dir(p)}
				break
			}
		}
	case CodeBuddy:
		p := filepath.Join(configDir(opts.Home, CodeBuddy), "settings.json")
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

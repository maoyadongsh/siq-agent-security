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
	Platform string   `json:"platform"`
	Action   string   `json:"action"`
	Paths    []string `json:"paths"`
	Note     string   `json:"note,omitempty"`
	Record   *Record  `json:"record,omitempty"`
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

// Uninstall restores the newest backup for the platform.
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
	for dest, bak := range rec.Modified {
		data, err := os.ReadFile(bak)
		if err != nil {
			return nil, err
		}
		if err := os.WriteFile(dest, data, 0o600); err != nil {
			return nil, err
		}
	}
	for _, p := range rec.Created {
		_ = os.RemoveAll(p)
	}
	return &Result{Platform: opts.Platform, Action: "uninstall", Paths: rec.Created, Record: rec}, nil
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
	doc := map[string]any{}
	if data, err := os.ReadFile(ocPath); err == nil {
		_ = json.Unmarshal(data, &doc)
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
	doc := map[string]any{}
	if data, err := os.ReadFile(settingsPath); err == nil {
		_ = json.Unmarshal(data, &doc)
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
	if exists(path) {
		if rec.Modified[path] == "" {
			bak := path + ".agentshield-bak"
			src, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			if err := os.WriteFile(bak, src, 0o600); err != nil {
				return err
			}
			rec.Modified[path] = bak
		}
	} else {
		rec.Created = appendUnique(rec.Created, path)
	}
	return os.WriteFile(path, raw, 0o600)
}

func writeNewOrReplace(dest string, data []byte, rec *Record) error {
	if err := os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
		return err
	}
	if exists(dest) {
		if rec.Modified[dest] == "" {
			src, err := os.ReadFile(dest)
			if err != nil {
				return err
			}
			bak := dest + ".agentshield-bak"
			if err := os.WriteFile(bak, src, 0o600); err != nil {
				return err
			}
			rec.Modified[dest] = bak
		}
	} else {
		rec.Created = appendUnique(rec.Created, dest)
	}
	return os.WriteFile(dest, data, 0o600)
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

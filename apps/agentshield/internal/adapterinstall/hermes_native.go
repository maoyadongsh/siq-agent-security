package adapterinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/product"
)

var ErrNativeCLI = errors.New("adapter: native Hermes CLI unavailable or incompatible")

// Registration is limited to this product's native configuration ownership.
type NativeRegistration struct {
	Enabled  bool  `json:"enabled"`
	Disabled bool  `json:"disabled"`
	Override *bool `json:"override,omitempty"`
}

type nativeStage struct {
	dir, cli string
	env      []string
}
type boundedNativeOutput struct {
	bytes.Buffer
	limit int
}

func (b *boundedNativeOutput) Write(raw []byte) (int, error) {
	if len(raw) > b.limit-b.Len() {
		return 0, errors.New("native output limit")
	}
	return b.Buffer.Write(raw)
}

// FindHermesCLI only locates a program. It never runs a discovered profile file.
func FindHermesCLI(override string) string {
	path := override
	if path == "" {
		var err error
		path, err = exec.LookPath("hermes")
		if err != nil {
			return ""
		}
	}
	if !filepath.IsAbs(path) {
		return ""
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return ""
	}
	info, err := os.Lstat(resolved)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 256<<20 {
		return ""
	}
	return resolved
}

// Native parsing is bounded and rejects YAML alias graphs / explicit tags.
// This guard is deliberately conservative; it is not a YAML parser.
var unsupportedNativeYAML = regexp.MustCompile(`(^|[\s\[\]{},:])[&*!][^\s\[\]{},]+`)

func safeNativeInput(raw []byte) error {
	if len(raw) > 1<<20 || bytes.IndexByte(raw, 0) >= 0 || unsupportedNativeYAML.Match(raw) {
		return errors.New("adapter: native YAML input requires manual review")
	}
	return nil
}

func newNativeStage(cli string) (*nativeStage, error) {
	if cli == "" {
		return nil, ErrNativeCLI
	}
	dir, err := os.MkdirTemp("", "siq-hermes-config-")
	if err != nil {
		return nil, err
	}
	stage := &nativeStage{dir: dir, cli: cli}
	for _, name := range []string{"home", "profile", "bundled", "verify"} {
		if err := os.Mkdir(filepath.Join(dir, name), 0700); err != nil {
			stage.close()
			return nil, err
		}
	}
	for _, key := range []string{"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"} {
		if val := os.Getenv(key); val != "" {
			stage.env = append(stage.env, key+"="+val)
		}
	}
	stage.env = append(stage.env, "HOME="+filepath.Join(dir, "home"), "USERPROFILE="+filepath.Join(dir, "home"), "LOCALAPPDATA="+filepath.Join(dir, "home"), "HERMES_BUNDLED_PLUGINS="+filepath.Join(dir, "bundled"), "HERMES_ENABLE_PROJECT_PLUGINS=0", "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "NO_COLOR=1")
	plugin := filepath.Join(dir, "profile", "plugins", product.PluginDir())
	if err := os.MkdirAll(plugin, 0700); err != nil {
		stage.close()
		return nil, err
	}
	manifest, err := embedded.ReadFile("assets/hermes/plugin.yaml")
	if err != nil {
		stage.close()
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(plugin, "plugin.yaml"), manifest, 0600); err != nil {
		stage.close()
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(plugin, "__init__.py"), []byte("# Metadata-only staging; no runtime plugin execution.\n"), 0600); err != nil {
		stage.close()
		return nil, err
	}
	return stage, nil
}
func (n *nativeStage) close() { _ = os.RemoveAll(n.dir) } // Only our private, newly created temporary tree.
func (n *nativeStage) command(profile string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, n.cli, args...)
	cmd.Dir = n.dir
	cmd.Env = append(append([]string{}, n.env...), "HERMES_HOME="+filepath.Join(n.dir, profile))
	cmd.WaitDelay = time.Second
	output := &boundedNativeOutput{limit: 1 << 20}
	discard := &boundedNativeOutput{limit: 64 << 10}
	cmd.Stdout = output
	cmd.Stderr = discard
	if err := cmd.Run(); err != nil {
		return nil, ErrNativeCLI
	}
	return output.Bytes(), nil
}
func decodeNativeObject(raw []byte) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var doc map[string]any
	if err := decoder.Decode(&doc); err != nil || doc == nil {
		return nil, ErrNativeCLI
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return nil, ErrNativeCLI
	}
	return doc, nil
}

// Indenting a document under a fixed, unknown config key lets the public native
// CLI return its parsed value without injecting Hermes schema defaults into it.
// Directives / multiple-document YAML that cannot be nested are refused.
func (n *nativeStage) document(raw []byte) (map[string]any, error) {
	if err := safeNativeInput(raw); err != nil {
		return nil, err
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		raw = []byte("{}\n")
	}
	nested := "siq_adapter_document:\n  " + strings.ReplaceAll(string(raw), "\n", "\n  ") + "\n"
	path := filepath.Join(n.dir, "verify", "config.yaml")
	if err := os.WriteFile(path, []byte(nested), 0600); err != nil {
		return nil, err
	}
	encoded, err := n.command("verify", "config", "get", "siq_adapter_document", "--json")
	if err != nil {
		return nil, err
	}
	return decodeNativeObject(encoded)
}
func nativePlugins(doc map[string]any) (map[string]any, error) {
	plugins, ok := doc["plugins"].(map[string]any)
	if _, exists := doc["plugins"]; exists && !ok {
		return nil, ErrNativeCLI
	}
	if plugins == nil {
		plugins = map[string]any{}
	}
	for _, key := range []string{"enabled", "disabled"} {
		if value, exists := plugins[key]; exists {
			if _, err := openClawStrings(value, key); err != nil {
				return nil, ErrNativeCLI
			}
		}
	}
	return plugins, nil
}
func nativeRegistration(doc map[string]any) (NativeRegistration, error) {
	p, err := nativePlugins(doc)
	if err != nil {
		return NativeRegistration{}, err
	}
	var state NativeRegistration
	for _, item := range asList(p["enabled"]) {
		state.Enabled = state.Enabled || item == product.PluginDir()
	}
	for _, item := range asList(p["disabled"]) {
		state.Disabled = state.Disabled || item == product.PluginDir()
	}
	entries, ok := p["entries"].(map[string]any)
	if _, exists := p["entries"]; exists && !ok {
		return state, ErrNativeCLI
	}
	entry, ok := entries[product.PluginDir()].(map[string]any)
	if _, exists := entries[product.PluginDir()]; exists && !ok {
		return state, ErrNativeCLI
	}
	if value, exists := entry["allow_tool_override"]; exists {
		flag, ok := value.(bool)
		if !ok {
			return state, ErrNativeCLI
		}
		state.Override = &flag
	}
	return state, nil
}
func nativeUnowned(doc map[string]any) (map[string]any, error) {
	raw, _ := json.Marshal(doc)
	out, err := decodeNativeObject(raw)
	if err != nil {
		return nil, err
	}
	delete(out, "_config_version")
	plugins, err := nativePlugins(out)
	if err != nil {
		return nil, err
	}
	for _, field := range []string{"enabled", "disabled"} {
		list := []string{}
		for _, item := range asList(plugins[field]) {
			if item != product.PluginDir() {
				list = append(list, item.(string))
			}
		}
		sort.Strings(list)
		if len(list) == 0 {
			delete(plugins, field)
		} else {
			plugins[field] = list
		}
	}
	if entries, ok := plugins["entries"].(map[string]any); ok {
		if own, ok := entries[product.PluginDir()].(map[string]any); ok {
			delete(own, "allow_tool_override")
			if len(own) == 0 {
				delete(entries, product.PluginDir())
			}
		}
		if len(entries) == 0 {
			delete(plugins, "entries")
		}
	}
	if len(plugins) == 0 {
		delete(out, "plugins")
	} else {
		out["plugins"] = plugins
	}
	return out, nil
}
func (n *nativeStage) restore(before map[string]any, original NativeRegistration) error {
	plugins, err := nativePlugins(before)
	if err != nil {
		return err
	}
	for _, item := range []struct {
		field   string
		enabled bool
	}{{"enabled", original.Enabled}, {"disabled", original.Disabled}} {
		list := []any{}
		for _, value := range asList(plugins[item.field]) {
			if value != product.PluginDir() {
				list = append(list, value)
			}
		}
		if item.enabled {
			list = append(list, product.PluginDir())
		}
		raw, _ := json.Marshal(list)
		if _, err := n.command("profile", "config", "set", "plugins."+item.field, string(raw)); err != nil {
			return err
		}
	}
	current, err := nativeRegistration(before)
	if err != nil {
		return err
	}
	key := "plugins.entries." + product.PluginDir() + ".allow_tool_override"
	if original.Override != nil {
		value := "false"
		if *original.Override {
			value = "true"
		}
		_, err = n.command("profile", "config", "set", key, value)
	} else if current.Override != nil {
		_, err = n.command("profile", "config", "unset", key)
	}
	return err
}

func (p *Plan) prepareHermesNative(uninstall bool) error {
	o := p.payload.Options
	path := filepath.Join(o.configRoot(), "config.yaml")
	before, err := p.input(path)
	if err != nil {
		return err
	}
	if uninstall && p.payload.Record.NativeOriginal == nil {
		return nil
	}
	cli := FindHermesCLI(o.NativeCLI)
	if cli == "" {
		return ErrNativeCLI
	}
	digest, err := programDigest(cli)
	if err != nil {
		return ErrNativeCLI
	}
	p.payload.Options.NativeCLI = cli
	p.payload.NativeCLIDigest = digest
	stage, err := newNativeStage(cli)
	if err != nil {
		return err
	}
	defer stage.close()
	doc, err := stage.document(before.Data)
	if err != nil {
		return err
	}
	original, err := nativeRegistration(doc)
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(stage.dir, "profile", "config.yaml"), before.Data, 0600); err != nil {
		return err
	}
	if uninstall {
		err = stage.restore(doc, *p.payload.Record.NativeOriginal)
	} else {
		_, err = stage.command("profile", "plugins", "enable", product.PluginDir(), "--no-allow-tool-override")
	}
	if err != nil {
		return err
	}
	after, err := readImage(stage.dir, filepath.Join(stage.dir, "profile", "config.yaml"))
	if err != nil {
		return err
	}
	changed, err := stage.document(after.Data)
	if err != nil {
		return err
	}
	unownedBefore, err := nativeUnowned(doc)
	if err != nil {
		return err
	}
	unownedAfter, err := nativeUnowned(changed)
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(unownedBefore, unownedAfter) {
		return errors.New("adapter: native CLI changed unrelated settings")
	}
	actual, err := nativeRegistration(changed)
	if err != nil {
		return err
	}
	if uninstall {
		if !reflect.DeepEqual(actual, *p.payload.Record.NativeOriginal) {
			return ErrNativeCLI
		}
		if !p.owns(path) {
			return errors.New("adapter: native configuration ownership unavailable")
		}
		if len(changed) == 0 && p.payload.Record.Modified[path] == "" {
			after = fileImage{}
		}
		return p.add(path, after, "恢复接入前本产品的原生启用状态，保留其他插件和当前配置")
	}
	if !actual.Enabled || actual.Disabled || actual.Override == nil || *actual.Override {
		return ErrNativeCLI
	}
	if p.payload.Record.NativeOriginal == nil {
		p.payload.Record.NativeOriginal = &original
	}
	p.payload.Record.NativeConfigHash = imageHash(after)
	p.payload.Record.NativeCLI = cli
	p.payload.Record.NativeCLIHash = digest
	return p.write(path, after.Data, 0600, "由 Hermes 原生命令启用本插件，不授予内置工具覆盖权限；宿主会规范化配置格式")
}

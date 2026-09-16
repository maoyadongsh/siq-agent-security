package adapterinstall

import (
	"errors"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"

	"siq-agent-security/apps/agentshield/internal/product"
)

func (p *Plan) owns(path string) bool {
	if p.payload.Record.Modified[path] != "" {
		return true
	}
	for _, owned := range p.payload.Record.Created {
		if owned == path {
			return true
		}
	}
	return false
}

func (p *Plan) originalJSON(path string) (map[string]any, error) {
	original := p.payload.Record.Modified[path]
	if original == "" {
		return map[string]any{}, nil
	}
	if original != path+originalSuffix {
		return nil, errors.New("adapter: recovery snapshot location does not match")
	}
	image, err := p.input(original)
	if err != nil || !image.Exists {
		return nil, errors.New("adapter: original snapshot unavailable")
	}
	return p.planJSON(original)
}

func (p *Plan) prepareUninstall() error {
	o, rec := p.payload.Options, p.payload.Record
	root := o.configRoot()
	plugin := filepath.Join(root, "plugins", product.PluginDir())
	var paths []string
	switch o.Platform {
	case Hermes:
		if rec.NativeOriginal != nil {
			if err := p.prepareHermesNative(true); err != nil {
				return err
			}
		}
		paths = []string{filepath.Join(plugin, "plugin.yaml"), filepath.Join(plugin, "__init__.py"), filepath.Join(plugin, "config.json")}
		if runtime.GOOS != "windows" {
			paths = append(paths, o.wrapperPath())
			// A default instance may inherit an older installation that owned
			// the shared wrapper. Named profiles must never remove that file.
			legacyWrapper := filepath.Join(o.Home, ".local", "bin", "hermes-skills-install")
			if root == configDir(o.Home, Hermes) && legacyWrapper != o.wrapperPath() && p.owns(legacyWrapper) {
				paths = append(paths, legacyWrapper)
			}
		}
	case OpenClaw:
		paths = []string{filepath.Join(plugin, "package.json"), filepath.Join(plugin, "index.ts"), filepath.Join(plugin, "openclaw.plugin.json"), filepath.Join(root, product.Name+".json")}
		path := filepath.Join(root, "openclaw.json")
		if !p.owns(path) {
			return errors.New("adapter: current configuration differs from install record")
		}
		doc, err := p.planJSON(path)
		if err != nil {
			return conflictRecovery(path, rec.Modified[path], err)
		}
		original, err := p.originalJSON(path)
		if err != nil {
			return conflictRecovery(path, rec.Modified[path], err)
		}
		if sec, ok := doc["security"].(map[string]any); ok {
			oldSec, _ := original["security"].(map[string]any)
			if policy, exists := sec["installPolicy"]; exists && !reflect.DeepEqual(policy, oldSec["installPolicy"]) {
				if !sameOpenClawLegacyPolicy(policy, rec.Binary) {
					return conflictRecovery(path, rec.Modified[path], errors.New("installation policy changed outside this operation"))
				}
				delete(sec, "installPolicy")
				if old, exists := oldSec["installPolicy"]; exists {
					sec["installPolicy"] = old
				}
				if len(sec) == 0 {
					delete(doc, "security")
				}
			}
		}
		if err := restoreOpenClawRegistration(doc, original, plugin); err != nil {
			return conflictRecovery(path, rec.Modified[path], err)
		}
		pruneEmptyOpenClawPlugins(doc, original)
		if err := p.surgicalWrite(path, doc); err != nil {
			return err
		}
	case CodeBuddy, WorkBuddy:
		path := filepath.Join(root, "settings.json")
		if !p.owns(path) {
			return errors.New("adapter: host config directory differs from latest install record")
		}
		for _, owned := range hostConfigPaths(rec) {
			if err := p.prepareHostConfigUninstall(owned); err != nil {
				return err
			}
		}
		return nil
	}
	for _, path := range paths {
		owned := p.owns(path)
		// Legacy installers recorded the plugin directory as created. Its
		// known files may be removed, but unknown user files are never traversed.
		for _, created := range rec.Created {
			owned = owned || created == plugin && strings.HasPrefix(path, plugin+string(filepath.Separator))
		}
		if !owned {
			continue
		}
		current, err := p.input(path)
		if err != nil {
			return err
		}
		if !current.Exists {
			continue
		}
		if hash := rec.Written[path]; hash == "" || imageHash(current) != hash {
			return conflictRecovery(path, rec.Modified[path], errors.New("installed file changed or legacy digest unavailable; preserve and review"))
		}
		after := fileImage{}
		if original := rec.Modified[path]; original != "" {
			if original != path+originalSuffix {
				return errors.New("adapter: snapshot location does not match")
			}
			after, err = p.input(original)
			if err != nil || !after.Exists {
				return errors.New("adapter: original snapshot unavailable")
			}
			if mode, ok := rec.OriginalModes[path]; ok {
				after.Mode = mode
			}
		}
		if err := p.add(path, after, "仅移除本次安装拥有的文件，或恢复接入前的文件"); err != nil {
			return err
		}
	}
	return nil
}

func hostConfigPaths(rec Record) []string {
	set := map[string]struct{}{}
	for _, path := range rec.Created {
		if filepath.Base(path) == "settings.json" {
			set[path] = struct{}{}
		}
	}
	for path := range rec.Modified {
		if filepath.Base(path) == "settings.json" {
			set[path] = struct{}{}
		}
	}
	paths := make([]string, 0, len(set))
	for path := range set {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	return paths
}

func (p *Plan) prepareHostConfigUninstall(path string) error {
	rec := p.payload.Record
	doc, err := p.planJSON(path)
	if err != nil {
		return conflictRecovery(path, rec.Modified[path], err)
	}
	hooks, ok := doc["hooks"].(map[string]any)
	if _, exists := doc["hooks"]; exists && !ok {
		return conflictRecovery(path, rec.Modified[path], errors.New("invalid hooks object"))
	}
	if hooks != nil {
		for _, event := range []string{"PreToolUse", "PostToolUse"} {
			value, exists := hooks[event]
			if !exists {
				continue
			}
			list, ok := value.([]any)
			if !ok {
				return conflictRecovery(path, rec.Modified[path], errors.New("invalid hooks list"))
			}
			kept := []any{}
			for _, item := range list {
				entry, ok := item.(map[string]any)
				if !ok {
					kept = append(kept, item)
					continue
				}
				commands, ok := entry["hooks"].([]any)
				if !ok {
					kept = append(kept, item)
					continue
				}
				remaining := []any{}
				for _, cmdValue := range commands {
					cmd, _ := cmdValue.(map[string]any)
					text, _ := cmd["command"].(string)
					if cmd["type"] == "command" && isRecordedToolHook(text, p.payload.Options.Platform, rec.Binary, p.payload.Options.StateDir) {
						continue
					}
					remaining = append(remaining, cmdValue)
				}
				if len(remaining) > 0 || len(commands) == 0 {
					entry["hooks"] = remaining
					kept = append(kept, entry)
				}
			}
			if len(kept) == 0 {
				delete(hooks, event)
			} else {
				hooks[event] = kept
			}
		}
		if len(hooks) == 0 {
			delete(doc, "hooks")
		}
	}
	return p.surgicalWrite(path, doc)
}

func (p *Plan) surgicalWrite(path string, doc map[string]any) error {
	data := encodePlanJSON(doc)
	mode := uint32(0o600)
	// A configuration this install modified keeps the mode it had before the
	// install touched it, matching the snapshot restore path below.
	if originalMode, ok := p.payload.Record.OriginalModes[path]; ok {
		mode = originalMode
	}
	if orig, err := p.input(path + originalSuffix); err != nil {
		return err
	} else if orig.Exists && jsonDocumentsEqual(orig.Data, data) {
		data = append([]byte(nil), orig.Data...)
	}
	after := fileImage{Exists: true, Data: data, Mode: mode}
	if len(doc) == 0 && p.payload.Record.Modified[path] == "" {
		after = fileImage{}
	}
	return p.add(path, after, "移除本产品登记，保留当前其他平台设置")
}

// Restore only the fields owned by registration, retaining current user fields.
func restoreOpenClawRegistration(doc, original map[string]any, root string) error {
	plugins, ok := doc["plugins"].(map[string]any)
	if _, exists := doc["plugins"]; exists && !ok {
		return errors.New("invalid plugins object")
	}
	if plugins == nil {
		return nil
	}
	old, _ := original["plugins"].(map[string]any)
	removeAdded := func(parent, before map[string]any, field, value string) error {
		for _, item := range asList(before[field]) {
			if item == value {
				return nil
			}
		}
		raw, exists := parent[field]
		if !exists {
			return nil
		}
		list, err := openClawStrings(raw, field)
		if err != nil {
			return err
		}
		kept := []any{}
		for _, item := range list {
			if item != value {
				kept = append(kept, item)
			}
		}
		parent[field] = kept
		return nil
	}
	if err := removeAdded(plugins, old, "allow", product.PluginDir()); err != nil {
		return err
	}
	if load, ok := plugins["load"].(map[string]any); ok {
		prior, _ := old["load"].(map[string]any)
		if err := removeAdded(load, prior, "paths", root); err != nil {
			return err
		}
	} else if _, exists := plugins["load"]; exists {
		return errors.New("invalid load object")
	}
	if entries, ok := plugins["entries"].(map[string]any); ok {
		if entry, ok := entries[product.PluginDir()].(map[string]any); ok {
			oldEntries, _ := old["entries"].(map[string]any)
			oldEntry, _ := oldEntries[product.PluginDir()].(map[string]any)
			if enabled, exists := oldEntry["enabled"]; exists {
				entry["enabled"] = enabled
			} else {
				delete(entry, "enabled")
			}
			if len(entry) == 0 {
				delete(entries, product.PluginDir())
			}
		} else if _, exists := entries[product.PluginDir()]; exists {
			return errors.New("invalid plugin entry")
		}
	} else if _, exists := plugins["entries"]; exists {
		return errors.New("invalid entries object")
	}
	return nil
}

func pruneEmptyOpenClawPlugins(doc, original map[string]any) {
	plugins, ok := doc["plugins"].(map[string]any)
	if !ok || plugins == nil {
		return
	}
	if load, ok := plugins["load"].(map[string]any); ok {
		if paths, ok := load["paths"].([]any); ok && len(paths) == 0 {
			delete(load, "paths")
		}
		if len(load) == 0 {
			delete(plugins, "load")
		}
	}
	if allow, ok := plugins["allow"].([]any); ok && len(allow) == 0 {
		delete(plugins, "allow")
	}
	if entries, ok := plugins["entries"].(map[string]any); ok && len(entries) == 0 {
		delete(plugins, "entries")
	}
	if _, had := original["plugins"]; !had && len(plugins) == 0 {
		delete(doc, "plugins")
	}
}
func asList(raw any) []any { list, _ := raw.([]any); return list }

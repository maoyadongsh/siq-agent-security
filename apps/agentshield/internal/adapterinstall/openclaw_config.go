package adapterinstall

import (
	"fmt"

	"siq-agent-security/apps/agentshield/internal/product"
)

// Configure only this plugin; global disable/deny remains an operator choice.
func configureOpenClawRuntime(doc map[string]any, root string) error {
	object := func(parent map[string]any, field string) (map[string]any, error) {
		if raw, exists := parent[field]; exists {
			m, ok := raw.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("adapter: OpenClaw %s must be an object", field)
			}
			return m, nil
		}
		m := map[string]any{}
		parent[field] = m
		return m, nil
	}
	plugins, err := object(doc, "plugins")
	if err != nil {
		return err
	}
	if enabled, exists := plugins["enabled"]; exists && enabled != true {
		return fmt.Errorf("adapter: OpenClaw plugins globally disabled or invalid")
	}
	for _, field := range []string{"allow", "deny"} {
		if raw, exists := plugins[field]; exists {
			list, err := openClawStrings(raw, field)
			if err != nil {
				return err
			}
			for _, item := range list {
				if field == "deny" && item == product.PluginDir() {
					return fmt.Errorf("adapter: OpenClaw plugin explicitly denied")
				}
			}
			if field == "allow" {
				plugins[field] = appendStringValue(list, product.PluginDir())
			}
		}
	}
	load, err := object(plugins, "load")
	if err != nil {
		return err
	}
	paths := []any{}
	if raw, exists := load["paths"]; exists {
		paths, err = openClawStrings(raw, "load.paths")
		if err != nil {
			return err
		}
	}
	load["paths"] = appendStringValue(paths, root)
	entries, err := object(plugins, "entries")
	if err != nil {
		return err
	}
	entry, err := object(entries, product.PluginDir())
	if err != nil {
		return err
	}
	entry["enabled"] = true
	return nil
}

func openClawStrings(raw any, field string) ([]any, error) {
	list, ok := raw.([]any)
	if !ok {
		return nil, fmt.Errorf("adapter: OpenClaw %s must be a string array", field)
	}
	for _, item := range list {
		if _, ok := item.(string); !ok {
			return nil, fmt.Errorf("adapter: OpenClaw %s must be a string array", field)
		}
	}
	return list, nil
}

func appendStringValue(list []any, value string) []any {
	for _, item := range list {
		if item == value {
			return list
		}
	}
	return append(list, value)
}

func stripOpenClawRuntime(doc map[string]any, root string) {
	plugins, ok := doc["plugins"].(map[string]any)
	if !ok {
		return
	}
	remove := func(parent map[string]any, field, value string) {
		list, ok := parent[field].([]any)
		if !ok {
			return
		}
		kept := make([]any, 0, len(list))
		for _, item := range list {
			if str, ok := item.(string); !ok || str != value {
				kept = append(kept, item)
			}
		}
		parent[field] = kept
	}
	remove(plugins, "allow", product.PluginDir())
	if load, ok := plugins["load"].(map[string]any); ok {
		remove(load, "paths", root)
	}
	if entries, ok := plugins["entries"].(map[string]any); ok {
		delete(entries, product.PluginDir())
	}
}

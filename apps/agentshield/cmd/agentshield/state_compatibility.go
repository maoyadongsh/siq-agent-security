package main

import "siq-agent-security/apps/agentshield/internal/state"

// Central guard also covers commands that create keys directly or operate on
// system services without opening a Store. It must precede command side effects.
func checkCommandState(command string) error {
	switch command {
	case "state-status", "state-migrate", "state-enable-windows-resources", "version", "help", "--help", "-h", "rulepack", "manifest-verify", "serve", "hook":
		// serve checks its explicit directory; hook must emit a structured deny
		// through hostHookClient/Open, because exit 1 alone is non-blocking.
		return nil
	default:
		dir, err := state.DefaultDir()
		if err != nil {
			return err
		}
		return state.RequireStateCompatibility(dir)
	}
}

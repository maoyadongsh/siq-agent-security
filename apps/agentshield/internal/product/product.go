// Package product is the public identity of this local gate.
// The Go module still lives under apps/agentshield; users, the CLI binary,
// and Skill directories use the repository name.
package product

import (
	"os"
	"strings"
)

// Name is the Skill frontmatter name, CLI binary, and default state-dir leaf.
const Name = "siq-agent-security"

// LegacyName is the former public binary / Skill name (kept for detection).
const LegacyName = "agentshield"

// Env names (new first; legacy names still read so existing shells keep working).
const (
	EnvStateDir         = "SIQ_AGENT_SECURITY_STATE_DIR"
	EnvStateDirOld      = "AGENTSHIELD_STATE_DIR"
	EnvBin              = "SIQ_AGENT_SECURITY_BIN"
	EnvBinOld           = "AGENTSHIELD_BIN"
	EnvReleaseSeed      = "SIQ_AGENT_SECURITY_RELEASE_SEED"
	EnvReleaseSeedOld   = "AGENTSHIELD_RELEASE_SEED"
	EnvSigningSeed      = "SIQ_AGENT_SECURITY_SIGNING_KEY_SEED"
	EnvSigningSeedOld   = "AGENTSHIELD_SIGNING_KEY_SEED"
	EnvRulepackPub      = "SIQ_AGENT_SECURITY_RULEPACK_PUBKEY"
	EnvRulepackPubOld   = "AGENTSHIELD_RULEPACK_PUBKEY"
	EnvAgentID          = "SIQ_AGENT_SECURITY_AGENT_ID"
	EnvAgentIDOld       = "AGENTSHIELD_AGENT_ID"
	EnvAdaptersDir      = "SIQ_AGENT_SECURITY_ADAPTERS_DIR"
	EnvAdaptersDirOld   = "AGENTSHIELD_ADAPTERS_DIR"
	EnvPort             = "SIQ_AGENT_SECURITY_PORT"
	EnvPortOld          = "AGENTSHIELD_PORT"
	EnvRequirePinned    = "SIQ_AGENT_SECURITY_REQUIRE_PINNED"
	EnvRequirePinnedOld = "AGENTSHIELD_REQUIRE_PINNED"
	EnvEndpoint         = "SIQ_AGENT_SECURITY_ENDPOINT"
	EnvEndpointOld      = "AGENTSHIELD_ENDPOINT"
	EnvMode             = "SIQ_AGENT_SECURITY_MODE"
	EnvModeOld          = "AGENTSHIELD_MODE"
)

// Env returns the first non-empty environment value among primary then legacy keys.
func Env(primary string, legacy ...string) string {
	if v := strings.TrimSpace(os.Getenv(primary)); v != "" {
		return v
	}
	for _, k := range legacy {
		if v := strings.TrimSpace(os.Getenv(k)); v != "" {
			return v
		}
	}
	return ""
}

// Mentions reports whether s refers to this product or the former public name.
func Mentions(s string) bool {
	return strings.Contains(s, Name) || strings.Contains(s, LegacyName)
}

// PluginDir is the host-side plugin folder name under ~/.hermes/plugins and
// ~/.openclaw/plugins. Status/detect also recognise LegacyName.
func PluginDir() string { return Name }

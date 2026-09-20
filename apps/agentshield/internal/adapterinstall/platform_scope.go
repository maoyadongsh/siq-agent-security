package adapterinstall

// NewIntegrationSupportedOnOS gates new adapter and Grant creation.
// Unknown and retired platforms never acquire execution authority.
func NewIntegrationSupportedOnOS(platform, goos string) bool {
	switch platform {
	case WorkBuddy:
		return goos == "darwin" || goos == "windows"
	case OpenClaw, Hermes, Trae, "claude_code", "codex", "other":
		return true
	default:
		return false
	}
}

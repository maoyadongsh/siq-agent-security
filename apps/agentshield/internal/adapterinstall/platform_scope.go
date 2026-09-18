package adapterinstall

// NewIntegrationSupportedOnOS gates new adapter and Grant creation.
// Historical configuration can still be inspected and surgically uninstalled.
func NewIntegrationSupportedOnOS(platform, goos string) bool {
	if platform == CodeBuddy {
		return false
	}
	if platform == WorkBuddy {
		return goos == "darwin" || goos == "windows"
	}
	return true
}

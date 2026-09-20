package adapterinstall

import "testing"

func TestNewIntegrationScopePreservesProductPlatforms(t *testing.T) {
	for _, tc := range []struct {
		platform, goos string
		want           bool
	}{
		{WorkBuddy, "linux", false},
		{WorkBuddy, "darwin", true},
		{WorkBuddy, "windows", true},
		{OpenClaw, "linux", true},
		{Hermes, "linux", true},
		{"codebuddy", "linux", false},
		{"codebuddy", "darwin", false},
		{"codebuddy", "windows", false},
	} {
		if got := NewIntegrationSupportedOnOS(tc.platform, tc.goos); got != tc.want {
			t.Errorf("NewIntegrationSupportedOnOS(%q, %q) = %v, want %v", tc.platform, tc.goos, got, tc.want)
		}
	}
}

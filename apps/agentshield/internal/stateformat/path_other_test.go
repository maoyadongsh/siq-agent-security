//go:build !windows

package stateformat

import "testing"

func TestNonWindowsStatePathSpellingUnchanged(t *testing.T) {
	for _, path := range []string{"", ".", "..", "target.", "target ", " ", "bad./../good", `C:\bad.\target`} {
		if err := ValidatePath(path); err != nil {
			t.Errorf("non-Windows spelling changed: %q", path)
		}
	}
}

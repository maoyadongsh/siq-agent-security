package adapterinstall

import (
	"errors"
	"testing"
)

func TestRuntimeCheckConfigRejectsUnsafeBeforeCLI(t *testing.T) {
	for _, raw := range []string{"a: &alias [x]\nb: *alias", "a: !!python/object {}", "a:\x00b"} {
		if _, err := ParseHermesConfigForRuntimeCheck("must-not-run", []byte(raw)); !errors.Is(err, ErrNativeCLI) {
			t.Fatal("unsafe native document accepted")
		}
	}
}

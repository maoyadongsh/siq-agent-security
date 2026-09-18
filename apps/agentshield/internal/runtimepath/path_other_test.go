//go:build !windows

package runtimepath

import "testing"

func TestWindowsFactsDoNotFallBackOnOtherPlatforms(t *testing.T) {
	if s, err := InspectWindows(`C:\fixture\file.txt`, true); s != nil || err != ErrUnverified {
		t.Fatal("Windows observation fabricated on another OS")
	}
}

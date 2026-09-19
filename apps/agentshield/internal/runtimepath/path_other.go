//go:build !windows

package runtimepath

func inspectWindows(string, bool) (*Snapshot, error) { return nil, ErrUnverified }

//go:build !linux

package main

import "context"

func measureServiceCapabilities(context.Context, *State) (map[string]any, error) {
	return nil, errInstalledCapabilities
}

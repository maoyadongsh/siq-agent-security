//go:build !linux

package main

import "context"

func scheduledHeartbeat(_ *State, _ *Client, heartbeat func(context.Context) error) (func(context.Context) error, error) {
	return heartbeat, nil
}

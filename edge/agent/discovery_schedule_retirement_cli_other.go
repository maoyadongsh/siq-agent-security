//go:build !linux

package main

import "context"

func cmdRetireSchedule(context.Context, []string) error { return errDiscoverySchedule }

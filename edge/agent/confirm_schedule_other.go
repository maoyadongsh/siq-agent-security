//go:build !linux

package main

import "context"

func cmdConfirmSchedule(context.Context, []string) error { return errDiscoverySchedule }

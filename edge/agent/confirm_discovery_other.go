//go:build !linux

package main

func cmdConfirmDiscovery(args []string) error { return errDiscoveryConsent }

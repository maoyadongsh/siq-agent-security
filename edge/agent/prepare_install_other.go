//go:build !linux

package main

import "errors"

func cmdPrepareInstall(args []string) error { return errors.New("install_preparation_requires_linux") }

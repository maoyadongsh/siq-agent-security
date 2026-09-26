//go:build !linux

package main

import "errors"

func cmdInspectHost([]string) error { return errors.New("host_inspection_requires_linux") }

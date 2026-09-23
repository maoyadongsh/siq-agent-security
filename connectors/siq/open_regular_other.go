//go:build !unix

package main

import "os"

func openRegular(path string) (*os.File, error) {
	return os.Open(path)
}

func validatePrivateOwner(_ os.FileInfo) error { return nil }
func validateSingleLink(_ os.FileInfo) error   { return nil }

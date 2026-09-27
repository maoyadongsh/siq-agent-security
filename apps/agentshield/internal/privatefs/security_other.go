//go:build !windows

package privatefs

import "os"

func (s *ReadSnapshot) FileSecurity(string) (string, error)  { return "", ErrPrivate }
func CreateNewWithSecurity(string, string) (*os.File, error) { return nil, ErrPrivate }

func EquivalentSecurity(a, b string) bool { return a == b }

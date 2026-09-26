//go:build !linux

package installplan

// Enterprise v1 installation is Linux-only.
func VerifyBundle(plan Plan, raw []byte, root string) error { return ErrInvalid }

func VerifyReleaseBundle(raw []byte, root string) (*Release, error) { return nil, ErrInvalid }

func VerifyStagedBundle(plan Plan, raw []byte, root string) error { return ErrInvalid }

func StageBundle(plan Plan, raw []byte, source, parent string) (string, error) {
	return "", ErrInvalid
}

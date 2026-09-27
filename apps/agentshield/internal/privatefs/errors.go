package privatefs

// ObjectError carries a non-secret, stable reason while retaining ErrPrivate
// compatibility. Never add paths, SID values or OS error strings here.
type ObjectError struct{ Code string }

func (e *ObjectError) Error() string { return "private-state: " + e.Code }
func (e *ObjectError) Unwrap() error { return ErrPrivate }

var (
	ErrMultipleLinks = &ObjectError{Code: "multiple_links"}
	ErrReparse       = &ObjectError{Code: "reparse_object"}
	ErrOwnerMismatch = &ObjectError{Code: "owner_mismatch"}
	ErrObjectChanged = &ObjectError{Code: "object_changed"}
)

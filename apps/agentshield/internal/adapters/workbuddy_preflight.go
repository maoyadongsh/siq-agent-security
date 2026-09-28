package adapters

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// WorkBuddyPreflightError exposes only a stable object category. It never wraps
// an OS error containing a path, ACL principal, or credential bytes.
type WorkBuddyPreflightError struct{ Code, ObjectCode string }

func (e *WorkBuddyPreflightError) Error() string { return "workbuddy preflight: " + e.ReasonCode() }
func (e *WorkBuddyPreflightError) ReasonCode() string {
	if e.ObjectCode != "" {
		return e.Code + "_" + e.ObjectCode
	}
	return e.Code
}
func workBuddyObjectFailure(code string, err error) error {
	reason := "unreadable"
	switch {
	case errors.Is(err, privatefs.ErrMultipleLinks):
		reason = "multiple_links"
	case errors.Is(err, privatefs.ErrReparse):
		reason = "reparse"
	case errors.Is(err, privatefs.ErrOwnerMismatch):
		reason = "owner_mismatch"
	case errors.Is(err, privatefs.ErrObjectChanged):
		reason = "object_changed"
	case errors.Is(err, os.ErrNotExist):
		reason = "missing"
	case errors.Is(err, privatefs.ErrPrivate):
		reason = "private_check_failed"
	}
	return &WorkBuddyPreflightError{Code: code, ObjectCode: reason}
}

func workBuddyPreflightError(code string) error { return &WorkBuddyPreflightError{Code: code} }

// InspectWorkBuddyManagedConfig is read-only and never reads credential bytes.
// Success is a local configuration snapshot, not online authority or execution.
func InspectWorkBuddyManagedConfig(path, dir string) (WorkBuddyManagedConfig, error) {
	cfg, _, err := workBuddyManagedPreflight(path, dir, nil, false)
	return cfg, err
}

// PreviewWorkBuddyManagedConfig checks a proposed config and the current objects.
// Only the config leaf may be absent. Existing objects are never repaired.
func PreviewWorkBuddyManagedConfig(raw []byte, path, dir string) error {
	if len(raw) == 0 {
		return workBuddyPreflightError("workbuddy_config_mismatch")
	}
	_, _, err := workBuddyManagedPreflight(path, dir, raw, false)
	return err
}

// ReadWorkBuddyManagedConnection is only for the hook. Keep the returned bearer
// in memory; it must not be logged, serialized or included in an install plan.
func ReadWorkBuddyManagedConnection(path, dir string) (WorkBuddyManagedConfig, string, error) {
	return workBuddyManagedPreflight(path, dir, nil, true)
}

func workBuddyManagedPreflight(path, dir string, proposed []byte, readCredential bool) (WorkBuddyManagedConfig, string, error) {
	var cfg WorkBuddyManagedConfig
	fail := func(code string) (WorkBuddyManagedConfig, string, error) {
		return WorkBuddyManagedConfig{}, "", workBuddyPreflightError(code)
	}
	objectFail := func(code string, err error) (WorkBuddyManagedConfig, string, error) {
		return WorkBuddyManagedConfig{}, "", workBuddyObjectFailure(code, err)
	}
	if runtime.GOOS != "windows" || !filepath.IsAbs(path) || filepath.Clean(path) != path || filepath.Base(path) != product.Name+".json" || !filepath.IsAbs(dir) || filepath.Clean(dir) != dir {
		return fail("workbuddy_config_path_invalid")
	}
	if stateformat.RequirePath(path, false) != nil || stateformat.RequirePath(dir, false) != nil {
		return fail("workbuddy_state_incompatible")
	}
	config, err := privatefs.OpenReadSnapshot(filepath.Dir(path))
	if err != nil {
		return objectFail("workbuddy_config_parent_unavailable", err)
	}
	defer config.Close()
	var raw []byte
	if proposed == nil {
		raw, err = config.ReadFile(filepath.Base(path), 16<<10)
	} else {
		err = config.CheckFile(filepath.Base(path))
		if errors.Is(err, os.ErrNotExist) {
			err = nil
		}
		raw = proposed
	}
	if err != nil {
		return objectFail("workbuddy_config_file_unavailable", err)
	}
	cfg, err = DecodeWorkBuddyManagedConfig(raw, path, dir)
	if err != nil {
		return fail("workbuddy_config_mismatch")
	}
	if stateformat.RequirePath(cfg.CredentialPath, false) != nil {
		return fail("workbuddy_state_incompatible")
	}
	credential, err := privatefs.OpenReadSnapshot(filepath.Dir(cfg.CredentialPath))
	if err != nil {
		return objectFail("workbuddy_credential_parent_unavailable", err)
	}
	defer credential.Close()
	if err := credential.CheckFile(filepath.Base(cfg.CredentialPath)); err != nil {
		return objectFail("workbuddy_credential_file_unavailable", err)
	}
	token := ""
	if readCredential {
		raw, err = credential.ReadFile(filepath.Base(cfg.CredentialPath), 4096)
		if err != nil {
			return objectFail("workbuddy_credential_file_unavailable", err)
		}
		token = strings.TrimSpace(string(raw))
		if len(token) < 32 || len(token) > 4096 || strings.ContainsAny(token, " \t\r\n") {
			return fail("workbuddy_credential_invalid")
		}
	}
	if err := config.Verify(); err != nil {
		return objectFail("workbuddy_config_file_unavailable", err)
	}
	if err := credential.Verify(); err != nil {
		return objectFail("workbuddy_credential_file_unavailable", err)
	}
	return cfg, token, nil
}

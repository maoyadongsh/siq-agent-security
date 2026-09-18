package adapterinstall

import (
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

// ParseHermesConfigForRuntimeCheck parses a bounded copy using the installed
// public CLI. Neither the actual profile nor its plugins are loaded. The result
// is private configuration material; callers must not log it or return it over HTTP.
// The caller must first validate the installed entry point and exclude external
// startup sources (including the installation's project .env). A private stage
// cannot make an arbitrary CLI program or its bootstrap environment safe.
func ParseHermesConfigForRuntimeCheck(cli string, raw []byte) (map[string]any, error) {
	if err := safeNativeInput(raw); err != nil {
		return nil, ErrNativeCLI
	}
	n, err := newNativeStage(cli)
	if err != nil {
		return nil, ErrNativeCLI
	}
	defer n.close()
	managed := filepath.Join(n.dir, "managed")
	if err := statefs.Mkdir(managed, 0700); err != nil {
		return nil, ErrNativeCLI
	}
	// The nested document is data, not effective runtime configuration. Prevent
	// an unrelated machine policy or dotenv file from changing these parse facts.
	n.env = append(n.env, "HERMES_MANAGED_DIR="+managed, "PYTHON_DOTENV_DISABLED=1")
	doc, err := n.document(raw)
	if err != nil {
		return nil, ErrNativeCLI
	}
	return doc, nil
}

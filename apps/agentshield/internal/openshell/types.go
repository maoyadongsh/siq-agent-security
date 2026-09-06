// Package openshell is the stdlib-only OpenShell CLI backend (dev-spec §3.9).
// Probe, apply, and verify stay aligned with
// apps/control-api/app/adapters/openshell/cli_backend.py: fail-closed on
// gateway info, network-only policy set, readback_verified cap,
// create_generation refused. AgentShield additionally discovers `openshell` on
// PATH and rejects non-OpenShell gateways. The Python control-plane backend
// is unchanged and still requires explicit env.
package openshell

import "fmt"

const (
	VerifyReadback = "readback_verified"
	VerifyFailed   = "failed"
	BackendName    = "openshell"
)

// AdapterError is a fail-closed CLI / gateway failure. Messages must not
// contain credentials or policy bodies.
type AdapterError struct{ Msg string }

func (e *AdapterError) Error() string { return e.Msg }

func fail(msg string) error { return &AdapterError{Msg: msg} }

func failf(format string, args ...any) error {
	return &AdapterError{Msg: fmt.Sprintf(format, args...)}
}

// RevisionConflict is a compare-and-swap miss on policy set.
type RevisionConflict struct{ Expected, Actual string }

func (e *RevisionConflict) Error() string {
	return fmt.Sprintf("openshell: revision conflict: expected %s, actual %s", e.Expected, e.Actual)
}

// CapabilityItem is one row of the versioned capability document (P1-1).
type CapabilityItem struct {
	Status    string `json:"status"`
	Semantics string `json:"semantics"`
	Basis     string `json:"basis"`
}

// Capabilities is the probe result. Boolean fields are a convenience view of
// already-measured semantics; they must not be raised just because a newer
// version string was parsed.
type Capabilities struct {
	Backend                     string                    `json:"backend"`
	SchemaVersion               string                    `json:"schema_version"`
	DynamicNetworkUpdate        bool                      `json:"dynamic_network_update"`
	StaticFilesystem            bool                      `json:"static_filesystem"`
	StaticProcess               bool                      `json:"static_process"`
	Landlock                    bool                      `json:"landlock"`
	Interceptor                 bool                      `json:"interceptor"`
	ProviderCredentialInjection bool                      `json:"provider_credential_injection"`
	RevisionSupport             bool                      `json:"revision_support"`
	MaxFilesystemPaths          int                       `json:"max_filesystem_paths"`
	Capabilities                map[string]CapabilityItem `json:"capabilities"`
}

// NetworkRule is the product-shaped allow rule submitted on apply.
type NetworkRule struct {
	Endpoint    string   `json:"endpoint"`
	Effect      string   `json:"effect,omitempty"`
	BinaryPaths []string `json:"binary_paths,omitempty"`
	RuleName    string   `json:"rule_name,omitempty"`
}

// Snapshot is a policy get --full read-back.
type Snapshot struct {
	Target          string         `json:"target"`
	Revision        string         `json:"revision"`
	Filesystem      map[string]any `json:"filesystem"`
	Network         []NetworkRule  `json:"network"`
	Process         map[string]any `json:"process"`
	EnforcementMode string         `json:"enforcement_mode"`
}

// DeploymentReceipt is the gateway's policy-set acknowledgement.
type DeploymentReceipt struct {
	BackendRevision string            `json:"backend_revision"`
	Evidence        map[string]string `json:"evidence"`
}

// Check is one config-readback assertion (not a behavioural fixture).
type Check struct {
	Endpoint string `json:"endpoint"`
	Request  string `json:"request"`
	Expected string `json:"expected"`
	Actual   string `json:"actual"`
	Result   string `json:"result"`
	Revision string `json:"revision"`
}

// VerificationReport is graded: passed implies readback_verified only.
type VerificationReport struct {
	Passed      bool     `json:"passed"`
	Level       string   `json:"level"`
	AllowChecks []Check  `json:"allow_checks"`
	DenyChecks  []Check  `json:"deny_checks"`
	Failures    []string `json:"failures"`
}

// RollbackReceipt is a successful restore.
type RollbackReceipt struct {
	RestoredRevision string            `json:"restored_revision"`
	Evidence         map[string]string `json:"evidence"`
}

// EffectiveReadback is the grant-facing proof (dev-spec §3.7 / §3.9).
type EffectiveReadback struct {
	Backend    string `json:"backend"`
	Revision   string `json:"revision"`
	VerifiedAt string `json:"verified_at"`
	EvidenceID string `json:"evidence_id"`
}

// ApplyResult is apply + verify for the CLI / HTTP surface.
type ApplyResult struct {
	Receipt  DeploymentReceipt  `json:"receipt"`
	Report   VerificationReport `json:"report"`
	Readback EffectiveReadback  `json:"effective_readback"`
}

// EventBatch is policy-list text, not a behavioural event stream.
type EventBatch struct {
	Events []map[string]string `json:"events"`
	Cursor string              `json:"cursor,omitempty"`
	Source string              `json:"source"`
}

// SandboxPage is the list_targets result.
type SandboxPage struct {
	Targets []map[string]string `json:"targets"`
	Cursor  string              `json:"cursor,omitempty"`
}

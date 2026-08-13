// Package protocol implements the v1 Connector subprocess wire contract
// (packages/contracts/connector-protocol.v1.md) and the Go projection of the
// shared object schemas (packages/contracts/candidate.schema.json and
// packages/contracts/evidence.schema.json).
//
// This package is imported by the Edge Agent and by every connector binary
// (connectors/hermes, connectors/docker). The schema JSON files are the
// source of truth: field names and required-ness in the structs below MUST
// NOT drift from them (both schemas use additionalProperties:false, so an
// extra emitted field would be a contract violation).
package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Ops defined by connector-protocol.v1.md §2.
const (
	OpDescribe      = "describe"
	OpValidateScope = "validate_scope"
	OpPlanScan      = "plan_scan"
	OpCollect       = "collect"
	OpCheckpoint    = "checkpoint"
	OpHealth        = "health"
)

// Error codes (connector-protocol.v1.md §3). Connectors return these in
// Response.Error.Code; the Edge maps them to typed errors (see connector.go).
const (
	CodeScopeInvalid     = "scope_invalid"
	CodeLimitExceeded    = "limit_exceeded"
	CodeRedactionFailure = "redaction_failure"
	CodeTimeout          = "timeout"
	CodeUnsupported      = "unsupported"
)

// RedactionProfile is the only redaction profile implemented in Phase 0
// (evidence.redaction_profile must carry this value).
const RedactionProfile = "siq.redaction.v1"

// Default limits applied by the Edge when no connector-specific limit exists.
const (
	DefaultCollectTimeoutMS = 60_000
	DefaultOutputLimitBytes = 8 * 1024 * 1024
)

// Request is one NDJSON line written by the Edge to the connector's stdin.
type Request struct {
	ID     string          `json:"id"`
	Op     string          `json:"op"`
	Params json.RawMessage `json:"params"`
}

// Response is one NDJSON line written by the connector to its stdout.
// Exactly one response per request, in order (single-turn protocol).
type Response struct {
	ID     string         `json:"id"`
	OK     bool           `json:"ok"`
	Result any            `json:"result,omitempty"`
	Error  *ProtocolError `json:"error,omitempty"`
}

// ProtocolError is the error envelope (contract README: ok:false + code).
type ProtocolError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// ConnectorCapabilities is the describe result (contract: ≤64KB per call).
type ConnectorCapabilities struct {
	Version             string   `json:"version"`
	Objects             []string `json:"objects"`
	RequiredPermissions []string `json:"required_permissions"`
	DataCategories      []string `json:"data_categories"`
	MaxOutputBytes      int64    `json:"max_output_bytes"`
	NetworkAccess       bool     `json:"network_access"`
}

// Scope is the connector-native scope. Roots are absolute paths (optionally
// "~"-prefixed); a single trailing "/*" glob segment is allowed (the hermes
// default), any other wildcard use is rejected by ValidateScopeSafety.
type Scope struct {
	Roots   []string `json:"roots"`
	Include []string `json:"include,omitempty"`
	Exclude []string `json:"exclude,omitempty"`
}

// ValidationResult is the validate_scope result.
type ValidationResult struct {
	Valid  bool     `json:"valid"`
	Errors []string `json:"errors"`
}

// CollectLimits bound a single collect op (contract §2 example defaults:
// 200 files / 16 MiB).
type CollectLimits struct {
	MaxFiles int64 `json:"max_files"`
	MaxBytes int64 `json:"max_bytes"`
}

// ScanPlan is the plan_scan result and the collect parameter.
type ScanPlan struct {
	Scope  *Scope        `json:"scope"`
	Cursor string        `json:"cursor,omitempty"`
	Limits CollectLimits `json:"limits"`
}

// EvidenceBatch is the collect result (contract §2).
type EvidenceBatch struct {
	Candidates []*Candidate `json:"candidates"`
	Evidence   []*Evidence  `json:"evidence"`
	Cursor     string       `json:"cursor,omitempty"`
	Truncated  bool         `json:"truncated,omitempty"`
}

// CursorResult is the checkpoint result.
type CursorResult struct {
	Cursor string `json:"cursor,omitempty"`
}

// DependencyHealth reports one dependency inside HealthReport.
type DependencyHealth struct {
	Name    string `json:"name"`
	OK      bool   `json:"ok"`
	Message string `json:"message,omitempty"`
}

// HealthReport is the health result (contract §2, 10s timeout at the Edge).
type HealthReport struct {
	Version      string             `json:"version"`
	Dependencies []DependencyHealth `json:"dependencies"`
}

// Candidate mirrors candidate.schema.json exactly (required: candidate_id,
// source_type, source_locator, discovered_at, name, framework, evidence_ids).
type Candidate struct {
	CandidateID    string            `json:"candidate_id"`
	SourceType     string            `json:"source_type"`
	SourceLocator  string            `json:"source_locator"`
	DiscoveredAt   string            `json:"discovered_at"`
	Name           string            `json:"name"`
	Framework      string            `json:"framework"`
	ArtifactDigest string            `json:"artifact_digest,omitempty"`
	Attributes     map[string]string `json:"attributes,omitempty"`
	EvidenceIDs    []string          `json:"evidence_ids"`
	Confidence     float64           `json:"confidence,omitempty"`
	Status         string            `json:"status,omitempty"`
}

// Evidence mirrors evidence.schema.json exactly (required: evidence_id,
// source_type, source_locator, observed_at, collected_at, collector_id,
// connector_version, content_hash, redaction_profile, classification,
// signature). Connectors emit signature/collector_id empty; the Edge fills
// them at packaging time (contract §5).
type Evidence struct {
	EvidenceID       string  `json:"evidence_id"`
	TenantID         string  `json:"tenant_id,omitempty"`
	EnvironmentID    string  `json:"environment_id,omitempty"`
	SourceType       string  `json:"source_type"`
	SourceLocator    string  `json:"source_locator"`
	SubjectRef       *string `json:"subject_ref,omitempty"`
	ObservedAt       string  `json:"observed_at"`
	CollectedAt      string  `json:"collected_at"`
	CollectorID      string  `json:"collector_id"`
	ConnectorVersion string  `json:"connector_version"`
	ContentHash      string  `json:"content_hash"`
	RedactionProfile string  `json:"redaction_profile"`
	Classification   string  `json:"classification"`
	PayloadRef       *string `json:"payload_ref,omitempty"`
	Signature        string  `json:"signature"`
	ExpiresAt        *string `json:"expires_at,omitempty"`
}

// ExpandHome expands a leading "~" to the current user's home directory.
func ExpandHome(p string) string {
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	switch {
	case p == "~":
		return home
	case strings.HasPrefix(p, "~/"):
		return filepath.Join(home, p[2:])
	default:
		return p
	}
}

// ValidateScopeSafety is the shared scope hardening check, used by every
// connector's validate_scope op AND as defense-in-depth by the Edge before a
// collect is sent (contract §4 negative tests). Security invariants:
//
//   - nil/empty scope (no roots) is rejected — "空 scope" must be refused;
//   - the filesystem root "/" is rejected;
//   - any root containing ".env" or "secret" (case-insensitive) is rejected —
//     these are privileged-content hints and must never be scanned;
//   - ambiguous wildcards are rejected: "**", "?", mid-path "*" (a single
//     trailing "/*" glob — the hermes default — is allowed and expanded);
//   - roots must be absolute after "~" expansion;
//   - at least one root must exist and resolve to a directory.
func ValidateScopeSafety(scope *Scope) error {
	if scope == nil || len(scope.Roots) == 0 {
		return errors.New("empty scope: no roots")
	}
	matched := 0
	for _, raw := range scope.Roots {
		root := strings.TrimSpace(ExpandHome(raw))
		if root == "" {
			return errors.New("scope root is empty")
		}
		lower := strings.ToLower(root)
		if lower == "/" {
			return fmt.Errorf("scope root %q rejected: filesystem root", root)
		}
		if strings.Contains(lower, ".env") {
			return fmt.Errorf("scope root %q rejected: contains %q", root, ".env")
		}
		if strings.Contains(lower, "secret") {
			return fmt.Errorf("scope root %q rejected: contains %q", root, "secret")
		}
		if err := checkGlobShape(root); err != nil {
			return fmt.Errorf("scope root %q: %w", root, err)
		}
		base := strings.TrimSuffix(root, "/*")
		if !filepath.IsAbs(base) {
			return fmt.Errorf("scope root %q must be absolute", root)
		}
		n, err := countGlobMatches(root)
		if err != nil {
			return fmt.Errorf("scope root %q: %w", root, err)
		}
		matched += n
	}
	if matched == 0 {
		return errors.New("scope resolves to no existing paths")
	}
	return nil
}

// checkGlobShape rejects every wildcard use except a single trailing "/*".
func checkGlobShape(p string) error {
	rest := p
	if strings.HasSuffix(rest, "/*") {
		rest = strings.TrimSuffix(rest, "/*")
	}
	if strings.Contains(rest, "*") {
		return errors.New("ambiguous wildcard: '*' is only allowed as a trailing '/*' segment")
	}
	if strings.ContainsAny(rest, "?[{") {
		return errors.New("ambiguous wildcard: '?', '[' and '{' are not allowed")
	}
	return nil
}

// countGlobMatches counts existing directories matched by root (glob or plain).
func countGlobMatches(root string) (int, error) {
	if strings.ContainsAny(root, "*?[{") {
		matches, err := filepath.Glob(root)
		if err != nil {
			return 0, fmt.Errorf("bad glob: %w", err)
		}
		n := 0
		for _, m := range matches {
			if fi, err := os.Stat(m); err == nil && fi.IsDir() {
				n++
			}
		}
		return n, nil
	}
	fi, err := os.Stat(root)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}
	if !fi.IsDir() {
		return 0, nil
	}
	return 1, nil
}

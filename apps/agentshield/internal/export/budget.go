package export

import (
	"encoding/json"
	"errors"
	"fmt"
)

// Default export budgets (DEV16-C). JSON byte cap is independent of disk scan.
const (
	DefaultMaxReceipts   = 10_000
	DefaultMaxAssets     = 10_000
	DefaultMaxAdmissions = 5_000
	DefaultMaxGrants     = 5_000
	DefaultMaxFindings   = 10_000
	DefaultMaxAudit      = 200
	DefaultMaxJSONBytes  = 32 << 20
)

// ErrJSONBudget is returned when marshalled export exceeds MaxJSONBytes.
var ErrJSONBudget = errors.New("export: JSON byte budget exceeded")

// Budget limits section sizes and final JSON size for share exports.
type Budget struct {
	MaxReceipts   int
	MaxAssets     int
	MaxAdmissions int
	MaxGrants     int
	MaxFindings   int
	MaxAudit      int
	MaxJSONBytes  int
}

// Truncation describes which export sections were capped (DEV16-C).
type Truncation struct {
	Incomplete          bool  `json:"incomplete"`
	ReceiptsTruncated   bool  `json:"receipts_truncated,omitempty"`
	AssetsTruncated     bool  `json:"assets_truncated,omitempty"`
	AdmissionsTruncated bool  `json:"admissions_truncated,omitempty"`
	GrantsTruncated     bool  `json:"grants_truncated,omitempty"`
	FindingsTruncated   bool  `json:"findings_truncated,omitempty"`
	AuditTruncated      bool  `json:"audit_truncated,omitempty"`
	DiskBudgetHit       bool  `json:"disk_budget_hit,omitempty"`
	BytesScanned        int64 `json:"bytes_scanned,omitempty"`
}

func normalizeBudget(b Budget) Budget {
	if b.MaxReceipts <= 0 {
		b.MaxReceipts = DefaultMaxReceipts
	}
	if b.MaxAssets <= 0 {
		b.MaxAssets = DefaultMaxAssets
	}
	if b.MaxAdmissions <= 0 {
		b.MaxAdmissions = DefaultMaxAdmissions
	}
	if b.MaxGrants <= 0 {
		b.MaxGrants = DefaultMaxGrants
	}
	if b.MaxFindings <= 0 {
		b.MaxFindings = DefaultMaxFindings
	}
	if b.MaxAudit <= 0 {
		b.MaxAudit = DefaultMaxAudit
	}
	if b.MaxJSONBytes <= 0 {
		b.MaxJSONBytes = DefaultMaxJSONBytes
	}
	return b
}

func capSlice[T any](in []T, max int) ([]T, bool) {
	if max <= 0 || len(in) <= max {
		return in, false
	}
	return in[:max], true
}

// MarshalJSONBytes encodes with indent and enforces MaxJSONBytes (fail-closed).
func MarshalJSONBytes(b Bundle) ([]byte, error) {
	return MarshalJSONBytesBudget(b, DefaultMaxJSONBytes)
}

// MarshalJSONBytesBudget fails if the encoded size exceeds maxBytes.
func MarshalJSONBytesBudget(b Bundle, maxBytes int) ([]byte, error) {
	if maxBytes <= 0 {
		maxBytes = DefaultMaxJSONBytes
	}
	raw, err := json.MarshalIndent(b, "", "  ")
	if err != nil {
		return nil, err
	}
	if len(raw) > maxBytes {
		return nil, fmt.Errorf("%w: %d > %d", ErrJSONBudget, len(raw), maxBytes)
	}
	return raw, nil
}

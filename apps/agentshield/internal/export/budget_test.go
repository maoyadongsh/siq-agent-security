package export

import (
	"errors"
	"testing"

	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestBuildMarksIncompleteFromDiskRead(t *testing.T) {
	disk := &receipt.ReadResult{
		Receipts:     nil,
		BytesScanned: 4096,
		Truncated:    true,
		DiskBudget:   true,
	}
	b := Build(Input{
		Now:      "2026-09-06T00:00:00Z",
		Mode:     "block",
		Snap:     ledger.Snapshot{},
		Audit:    []state.AuditEvent{{Event: "x"}},
		DiskRead: disk,
	})
	if !b.Incomplete || b.Truncation == nil || !b.Truncation.DiskBudgetHit || !b.Truncation.ReceiptsTruncated {
		t.Fatalf("incomplete disk truncate: %+v", b.Truncation)
	}
}

func TestBuildCapsSections(t *testing.T) {
	var assets []ledger.AssetRecord
	// Use Report candidates via empty snap + many grants
	grants := make([]struct{}, 0)
	_ = grants
	snap := ledger.Snapshot{}
	for i := 0; i < 5; i++ {
		snap.Admissions = append(snap.Admissions, snap.Admissions...)
	}
	// simpler: many audit events
	audit := make([]state.AuditEvent, 0, 10)
	for i := 0; i < 10; i++ {
		audit = append(audit, state.AuditEvent{Event: "e", Target: "t"})
	}
	b := Build(Input{
		Now:    "2026-09-06T00:00:00Z",
		Mode:   "block",
		Snap:   snap,
		Audit:  audit,
		Budget: Budget{MaxAudit: 3, MaxReceipts: 1, MaxAssets: 1, MaxAdmissions: 1, MaxGrants: 1, MaxFindings: 1},
	})
	if !b.Incomplete || b.Truncation == nil || !b.Truncation.AuditTruncated {
		t.Fatalf("audit cap: incomplete=%v trunc=%+v audit=%d", b.Incomplete, b.Truncation, len(b.Audit))
	}
	if len(b.Audit) != 3 {
		t.Fatalf("audit len %d", len(b.Audit))
	}
	_ = assets
}

func TestMarshalJSONBytesBudget(t *testing.T) {
	b := Build(Input{Now: "t", Mode: "block", Snap: ledger.Snapshot{}, Audit: nil})
	_, err := MarshalJSONBytesBudget(b, 10)
	if !errors.Is(err, ErrJSONBudget) {
		t.Fatalf("want ErrJSONBudget, got %v", err)
	}
	raw, err := MarshalJSONBytesBudget(b, DefaultMaxJSONBytes)
	if err != nil || len(raw) == 0 {
		t.Fatalf("marshal: %v", err)
	}
}

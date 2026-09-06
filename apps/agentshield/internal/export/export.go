// Package export builds the redacted judge bundle (dev-spec §3.8.1.3).
package export

import (
	"strings"

	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

const Format = "agentshield.export.v1"

// Bundle is the downloadable JSON. It must not contain tokens, seeds, private
// keys, skill bodies, or tool-call parameters.
type Bundle struct {
	Format          string   `json:"format"`
	PrivacyProfile  string   `json:"privacy_profile"`
	GeneratedAt     string   `json:"generated_at"`
	Identity        Identity `json:"identity"`
	EnforcementMode string   `json:"enforcement_mode"`
	// ChainVerified is true only when the present prefix verifies (sig/link/hash).
	// It does NOT mean full history integrity; see HistoryIntegrity (DEV15-A).
	ChainVerified        bool                `json:"chain_verified"`
	ChainPrefixValid     bool                `json:"chain_prefix_valid"`
	HistoryIntegrity     string              `json:"history_integrity"` // verified|unknown|failed
	CheckpointConsistent *bool               `json:"checkpoint_consistent,omitempty"`
	ChainVerifyError     string              `json:"chain_verify_error,omitempty"`
	Overview             ledger.Overview     `json:"overview"`
	Assets               []AssetSummary      `json:"assets"`
	Admissions           []AdmissionSummary  `json:"admissions"`
	Grants               []GrantSummary      `json:"grants"`
	Findings             []ledger.FindingRow `json:"findings"`
	Receipts             []ReceiptSummary    `json:"receipts"`
	Audit                []state.AuditEvent  `json:"audit"`
	Incomplete           bool                `json:"incomplete"`
	Truncation           *Truncation         `json:"truncation,omitempty"`
	// Derived provenance + independent seal (DEV15-D). Signature covers the
	// share projection only; it must not be confused with receipt/admission seals.
	DerivedFrom   *DerivedFrom `json:"derived_from,omitempty"`
	SigningSchema string       `json:"signing_schema,omitempty"`
	Signature     string       `json:"signature,omitempty"`
}

// DerivedFrom records that this bundle is a redacted projection with its own seal.
type DerivedFrom struct {
	Kind             string `json:"kind"` // agentshield.export.derived/v1
	AttestationScope string `json:"attestation_scope"`
	SourceTipHash    string `json:"source_tip_hash,omitempty"`
	SourceSeq        int    `json:"source_seq,omitempty"`
	SourceCount      int    `json:"source_receipt_count"`
}

// Identity is the local verification key only.
type Identity struct {
	PublicKeyBase64 string `json:"public_key_base64"`
}

// AssetSummary is a locator-safe asset row.
type AssetSummary struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	Framework     string `json:"framework"`
	SourceType    string `json:"source_type"`
	SourceLocator string `json:"source_locator"`
	Status        string `json:"status"`
	AdmissionID   string `json:"admission_id,omitempty"`
	GrantID       string `json:"grant_id,omitempty"`
}

// AdmissionSummary drops the skill card body.
type AdmissionSummary struct {
	AdmissionID string   `json:"admission_id"`
	SkillName   string   `json:"skill_name"`
	Verdict     string   `json:"verdict"`
	ContentHash string   `json:"content_hash"`
	FindingIDs  []string `json:"finding_ids,omitempty"`
}

// GrantSummary drops desired-policy blobs.
type GrantSummary struct {
	GrantID     string        `json:"grant_id"`
	Status      string        `json:"status"`
	Platform    string        `json:"platform"`
	SubjectID   string        `json:"subject_id"`
	AdmissionID string        `json:"admission_id"`
	Facts       []FactSummary `json:"facts"`
}

// FactSummary is domain/action/resource without conditions.
type FactSummary struct {
	Domain        string `json:"domain"`
	Action        string `json:"action"`
	ResourceValue string `json:"resource_value"`
	Effect        string `json:"effect"`
	State         string `json:"state"`
}

// ReceiptSummary omits params and excerpts.
type ReceiptSummary struct {
	ReceiptID string `json:"receipt_id"`
	Seq       int    `json:"seq"`
	IssuedAt  string `json:"issued_at"`
	Platform  string `json:"platform"`
	Tool      string `json:"tool"`
	Action    string `json:"action"`
	Reason    string `json:"reason"`
	Hash      string `json:"hash"`
}

// Input is everything Build needs.
type Input struct {
	Now        string
	Mode       string
	Key        *signing.Key
	Snap       ledger.Snapshot
	Audit      []state.AuditEvent
	Checkpoint *receipt.Checkpoint // optional independent tip; same-dir HEAD is not valid
	Budget     Budget
	// DiskRead carries metrics from receipt.ReadLimited (disk budget, not slice).
	DiskRead *receipt.ReadResult
}

// Build projects a redacted bundle. Verify uses the public key only.
func Build(in Input) Bundle {
	bud := normalizeBudget(in.Budget)
	tr := &Truncation{}
	if in.DiskRead != nil {
		tr.BytesScanned = in.DiskRead.BytesScanned
		if in.DiskRead.Truncated {
			tr.ReceiptsTruncated = true
			tr.Incomplete = true
		}
		if in.DiskRead.DiskBudget {
			tr.DiskBudgetHit = true
			tr.Incomplete = true
		}
	}

	b := Bundle{
		Format:           Format,
		PrivacyProfile:   PrivacyProfileID,
		GeneratedAt:      in.Now,
		EnforcementMode:  in.Mode,
		HistoryIntegrity: receipt.HistoryUnknown,
		Overview:         ledger.Counts(in.Snap),
		Audit:            in.Audit,
		Assets:           []AssetSummary{},
		Admissions:       []AdmissionSummary{},
		Grants:           []GrantSummary{},
		Receipts:         []ReceiptSummary{},
		Findings:         []ledger.FindingRow{},
	}
	if in.Key != nil {
		b.Identity.PublicKeyBase64 = in.Key.PublicBase64()
		rep := receipt.VerifyDetailed(in.Snap.Receipts, in.Key.Public(), in.Checkpoint)
		b.ChainPrefixValid = rep.PrefixValid
		b.ChainVerified = rep.PrefixValid // prefix-only; not full-history
		b.HistoryIntegrity = rep.HistoryIntegrity
		b.CheckpointConsistent = rep.CheckpointConsistent
		if rep.Error != "" {
			b.ChainVerifyError = rep.Error
		}
	}
	findings := ledger.Findings(in.Snap)
	if capped, hit := capSlice(findings, bud.MaxFindings); hit {
		tr.FindingsTruncated = true
		tr.Incomplete = true
		findings = capped
	}
	for _, f := range findings {
		f.Excerpt = nil
		b.Findings = append(b.Findings, f)
	}
	assets := ledger.Assets(in.Snap)
	if capped, hit := capSlice(assets, bud.MaxAssets); hit {
		tr.AssetsTruncated = true
		tr.Incomplete = true
		assets = capped
	}
	for _, a := range assets {
		b.Assets = append(b.Assets, AssetSummary{
			ID: a.ID, Name: a.Name, Framework: a.Framework, SourceType: a.SourceType,
			SourceLocator: NormalizeLocator(a.SourceLocator), Status: a.Status, AdmissionID: a.AdmissionID, GrantID: a.GrantID,
		})
	}
	admissions := in.Snap.Admissions
	if capped, hit := capSlice(admissions, bud.MaxAdmissions); hit {
		tr.AdmissionsTruncated = true
		tr.Incomplete = true
		admissions = capped
	}
	for _, ad := range admissions {
		ids := make([]string, 0, len(ad.Findings))
		for _, f := range ad.Findings {
			ids = append(ids, f.FindingID)
		}
		b.Admissions = append(b.Admissions, AdmissionSummary{
			AdmissionID: ad.AdmissionID, SkillName: ad.SkillName, Verdict: ad.Verdict,
			ContentHash: ad.ContentHash, FindingIDs: ids,
		})
	}
	grants := in.Snap.Grants
	if capped, hit := capSlice(grants, bud.MaxGrants); hit {
		tr.GrantsTruncated = true
		tr.Incomplete = true
		grants = capped
	}
	for _, g := range grants {
		gs := GrantSummary{
			GrantID: g.GrantID, Status: g.Status, Platform: g.Platform,
			SubjectID: g.Subject.ID, AdmissionID: g.AdmissionID, Facts: []FactSummary{},
		}
		for _, f := range g.Facts {
			gs.Facts = append(gs.Facts, FactSummary{
				Domain: f.Domain, Action: f.Action, ResourceValue: NormalizeResourceValue(f.Resource.Value),
				Effect: f.Effect, State: f.State,
			})
		}
		b.Grants = append(b.Grants, gs)
	}
	recs := in.Snap.Receipts
	if capped, hit := capSlice(recs, bud.MaxReceipts); hit {
		tr.ReceiptsTruncated = true
		tr.Incomplete = true
		recs = capped
	}
	for _, r := range recs {
		b.Receipts = append(b.Receipts, ReceiptSummary{
			ReceiptID: r.ReceiptID, Seq: r.Seq, IssuedAt: r.IssuedAt, Platform: r.Platform,
			Tool: r.Tool, Action: r.Action, Reason: SanitizeReason(r.Reason), Hash: r.Hash,
		})
	}
	if capped, hit := capSlice(b.Audit, bud.MaxAudit); hit {
		tr.AuditTruncated = true
		tr.Incomplete = true
		b.Audit = capped
	}
	b.Incomplete = tr.Incomplete
	if tr.Incomplete {
		b.Truncation = tr
	}
	return b
}

// ContainsForbidden reports whether raw looks like it leaked a secret class.
func ContainsForbidden(raw []byte, needles ...string) bool {
	s := string(raw)
	for _, n := range needles {
		if n != "" && strings.Contains(s, n) {
			return true
		}
	}
	return false
}

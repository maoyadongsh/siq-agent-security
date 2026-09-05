// Package export builds the redacted judge bundle (dev-spec §3.8.1.3).
package export

import (
	"encoding/json"
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
	Format           string              `json:"format"`
	GeneratedAt      string              `json:"generated_at"`
	Identity         Identity            `json:"identity"`
	EnforcementMode  string              `json:"enforcement_mode"`
	ChainVerified    bool                `json:"chain_verified"`
	ChainVerifyError string              `json:"chain_verify_error,omitempty"`
	Overview         ledger.Overview     `json:"overview"`
	Assets           []AssetSummary      `json:"assets"`
	Admissions       []AdmissionSummary  `json:"admissions"`
	Grants           []GrantSummary      `json:"grants"`
	Findings         []ledger.FindingRow `json:"findings"`
	Receipts         []ReceiptSummary    `json:"receipts"`
	Audit            []state.AuditEvent  `json:"audit"`
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
	Now   string
	Mode  string
	Key   *signing.Key
	Snap  ledger.Snapshot
	Audit []state.AuditEvent
}

// Build projects a redacted bundle. Verify uses the public key only.
func Build(in Input) Bundle {
	b := Bundle{
		Format:          Format,
		GeneratedAt:     in.Now,
		EnforcementMode: in.Mode,
		Overview:        ledger.Counts(in.Snap),
		Audit:           in.Audit,
		Assets:          []AssetSummary{},
		Admissions:      []AdmissionSummary{},
		Grants:          []GrantSummary{},
		Receipts:        []ReceiptSummary{},
		Findings:        []ledger.FindingRow{},
	}
	if in.Key != nil {
		b.Identity.PublicKeyBase64 = in.Key.PublicBase64()
		if err := receipt.Verify(in.Snap.Receipts, in.Key.Public()); err != nil {
			b.ChainVerified = false
			b.ChainVerifyError = err.Error()
		} else {
			b.ChainVerified = true
		}
	}
	for _, f := range ledger.Findings(in.Snap) {
		f.Excerpt = nil
		b.Findings = append(b.Findings, f)
	}
	for _, a := range ledger.Assets(in.Snap) {
		b.Assets = append(b.Assets, AssetSummary{
			ID: a.ID, Name: a.Name, Framework: a.Framework, SourceType: a.SourceType,
			SourceLocator: a.SourceLocator, Status: a.Status, AdmissionID: a.AdmissionID, GrantID: a.GrantID,
		})
	}
	for _, ad := range in.Snap.Admissions {
		ids := make([]string, 0, len(ad.Findings))
		for _, f := range ad.Findings {
			ids = append(ids, f.FindingID)
		}
		b.Admissions = append(b.Admissions, AdmissionSummary{
			AdmissionID: ad.AdmissionID, SkillName: ad.SkillName, Verdict: ad.Verdict,
			ContentHash: ad.ContentHash, FindingIDs: ids,
		})
	}
	for _, g := range in.Snap.Grants {
		gs := GrantSummary{
			GrantID: g.GrantID, Status: g.Status, Platform: g.Platform,
			SubjectID: g.Subject.ID, AdmissionID: g.AdmissionID, Facts: []FactSummary{},
		}
		for _, f := range g.Facts {
			gs.Facts = append(gs.Facts, FactSummary{
				Domain: f.Domain, Action: f.Action, ResourceValue: f.Resource.Value,
				Effect: f.Effect, State: f.State,
			})
		}
		b.Grants = append(b.Grants, gs)
	}
	for _, r := range in.Snap.Receipts {
		b.Receipts = append(b.Receipts, ReceiptSummary{
			ReceiptID: r.ReceiptID, Seq: r.Seq, IssuedAt: r.IssuedAt, Platform: r.Platform,
			Tool: r.Tool, Action: r.Action, Reason: r.Reason, Hash: r.Hash,
		})
	}
	return b
}

// MarshalJSONBytes is pretty JSON for download.
func MarshalJSONBytes(b Bundle) ([]byte, error) {
	return json.MarshalIndent(b, "", "  ")
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

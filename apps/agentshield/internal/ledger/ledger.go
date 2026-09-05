// Package ledger projects inventory, admissions, grants and receipts into the
// local-console ledger (dev-spec §3.8.1 / §3.8.1.2). Refresh may write
// assets/, findings/ and audit.jsonl for lifecycle events.
package ledger

import (
	"net/url"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

const (
	StateDeclared  = "declared"
	StateInferred  = "inferred"
	StateObserved  = "observed"
	StateEffective = "effective"
	StateUnknown   = "unknown"
)

// Snapshot is one read-only view of local state.
type Snapshot struct {
	Report         *inventory.Report
	Admissions     []admission.Admission
	Grants         []grant.Grant
	Receipts       []receipt.Receipt
	Records        []AssetRecord
	FindingRecords []FindingRecord
}

// FactRow is one permission-fact projection for GET /v1/permissions.
type FactRow struct {
	FactID            string   `json:"fact_id"`
	SubjectType       string   `json:"subject_type"`
	SubjectID         string   `json:"subject_id"`
	Domain            string   `json:"domain"`
	Action            string   `json:"action"`
	ResourceType      string   `json:"resource_type"`
	ResourceValue     string   `json:"resource_value"`
	Effect            string   `json:"effect"`
	State             string   `json:"state"`
	Authority         string   `json:"authority"`
	AuthorityRevision *string  `json:"authority_revision,omitempty"`
	EvidenceIDs       []string `json:"evidence_ids"`
	Source            string   `json:"source"`
	GrantID           string   `json:"grant_id,omitempty"`
	GrantStatus       string   `json:"grant_status,omitempty"`
	ReceiptID         string   `json:"receipt_id,omitempty"`
	AdmissionID       string   `json:"admission_id,omitempty"`
}

// Asset is a list-row projection of an inventory candidate.
type Asset struct {
	ID               string            `json:"id"`
	Name             string            `json:"name"`
	Framework        string            `json:"framework"`
	SourceType       string            `json:"source_type"`
	SourceLocator    string            `json:"source_locator"`
	Status           string            `json:"status"`
	AdmissionID      string            `json:"admission_id,omitempty"`
	AdmissionVerdict string            `json:"admission_verdict,omitempty"`
	GrantID          string            `json:"grant_id,omitempty"`
	GrantStatus      string            `json:"grant_status,omitempty"`
	DeclaredTools    []string          `json:"declared_tools,omitempty"`
	EvidenceIDs      []string          `json:"evidence_ids"`
	AdmitPath        string            `json:"admit_path,omitempty"`
	ContentHash      string            `json:"content_hash,omitempty"`
	Attributes       map[string]string `json:"attributes,omitempty"`
	UpdatedAt        string            `json:"updated_at,omitempty"`
	DismissReason    string            `json:"dismiss_reason,omitempty"`
	DismissUntil     string            `json:"dismiss_until,omitempty"`
	HookLost         bool              `json:"hook_lost,omitempty"`
	ActorID          string            `json:"actor_id,omitempty"`
}

// AssetDetail is GET /v1/assets/{id}.
type AssetDetail struct {
	Asset
	Evidence  []admission.Evidence `json:"evidence"`
	Admission *admission.Admission `json:"admission,omitempty"`
	Grants    []grant.Grant        `json:"grants,omitempty"`
}

// FindingRow is a read-only admission finding.
type FindingRow struct {
	FindingID    string   `json:"finding_id"`
	RuleID       string   `json:"rule_id"`
	Category     string   `json:"category"`
	Severity     string   `json:"severity"`
	Disposition  string   `json:"disposition"`
	Status       string   `json:"status"`
	AdmissionID  string   `json:"admission_id"`
	SkillName    string   `json:"skill_name"`
	Path         string   `json:"path,omitempty"`
	Line         *int     `json:"line,omitempty"`
	Excerpt      *string  `json:"excerpt,omitempty"`
	EvidenceIDs  []string `json:"evidence_ids"`
	Source       string   `json:"source,omitempty"`
	SubjectRef   string   `json:"subject_ref,omitempty"`
	AcceptReason string   `json:"accept_reason,omitempty"`
	AcceptUntil  string   `json:"accept_until,omitempty"`
}

// Overview counts for the console home page.
type Overview struct {
	Assets           int `json:"assets"`
	UnadmittedSkills int `json:"unadmitted_skills"`
	OpenFindings     int `json:"open_findings"`
	RecentDenies     int `json:"recent_denies"`
	GrantsDeployed   int `json:"grants_deployed"`
}

// Permissions projects five-state facts. subjectID empty = all subjects.
func Permissions(s Snapshot, subjectID string) []FactRow {
	var out []FactRow
	granted := map[string]bool{}
	for _, g := range s.Grants {
		if g.AdmissionID != "" {
			granted[g.AdmissionID] = true
		}
		if subjectID != "" && g.Subject.ID != subjectID {
			continue
		}
		static := map[string]bool{}
		if g.DesiredPolicyRef != nil {
			for _, d := range g.DesiredPolicyRef.StaticDomainsUnavailable {
				static[d] = true
			}
		}
		hasEffectiveDomain := map[string]bool{}
		for _, f := range g.Facts {
			state := coerceState(f.Domain, f.State)
			if state == StateEffective {
				hasEffectiveDomain[f.Domain] = true
			}
			out = append(out, FactRow{
				FactID: f.FactID, SubjectType: g.Subject.Type, SubjectID: g.Subject.ID,
				Domain: f.Domain, Action: f.Action, ResourceType: f.Resource.Type, ResourceValue: f.Resource.Value,
				Effect: f.Effect, State: state, Authority: f.Authority, AuthorityRevision: f.AuthorityRevision,
				EvidenceIDs: f.EvidenceIDs, Source: "grant", GrantID: g.GrantID, GrantStatus: g.Status,
				AdmissionID: g.AdmissionID,
			})
		}
		for domain := range static {
			if hasEffectiveDomain[domain] {
				continue
			}
			out = append(out, FactRow{
				FactID:      "unknown-" + g.GrantID + "-" + domain,
				SubjectType: g.Subject.Type, SubjectID: g.Subject.ID,
				Domain: domain, Action: "static_unavailable", ResourceType: "domain", ResourceValue: domain,
				Effect: "deny", State: StateUnknown, Authority: "openshell",
				Source: "grant", GrantID: g.GrantID, GrantStatus: g.Status, AdmissionID: g.AdmissionID,
			})
		}
	}
	for _, a := range s.Admissions {
		if granted[a.AdmissionID] {
			continue
		}
		subj := a.SkillID
		if subj == "" {
			subj = a.SkillName
		}
		if subjectID != "" && subj != subjectID && a.SkillName != subjectID {
			continue
		}
		for i, d := range a.DeclaredFacts {
			st := d.State
			if st == "" {
				st = StateDeclared
			}
			st = coerceState(d.Domain, st)
			out = append(out, FactRow{
				FactID:      "adm-" + a.AdmissionID + "-" + itoa(i),
				SubjectType: "agent_asset", SubjectID: subj,
				Domain: d.Domain, Action: d.Action, ResourceType: d.Resource.Type, ResourceValue: d.Resource.Value,
				Effect: d.Effect, State: st, Authority: d.Authority, EvidenceIDs: d.EvidenceIDs,
				Source: "admission", AdmissionID: a.AdmissionID,
			})
		}
	}
	if s.Report != nil {
		for i, f := range s.Report.Facts {
			if subjectID != "" && f.Subject.ID != subjectID && !strings.Contains(f.Subject.ID, subjectID) {
				continue
			}
			out = append(out, FactRow{
				FactID: "inv-" + itoa(i), SubjectType: f.Subject.Type, SubjectID: f.Subject.ID,
				Domain: f.Domain, Action: f.Action, ResourceType: f.Resource.Type, ResourceValue: f.Resource.Value,
				Effect: f.Effect, State: coerceState(f.Domain, nonempty(f.State, StateObserved)),
				Authority: f.Authority, EvidenceIDs: f.EvidenceIDs, Source: "inventory",
			})
		}
	}
	for _, r := range s.Receipts {
		agent := ""
		if r.AgentID != nil {
			agent = *r.AgentID
		}
		if subjectID != "" && agent != subjectID {
			continue
		}
		if agent == "" {
			agent = r.SessionID
		}
		out = append(out, FactRow{
			FactID: "rcp-" + r.ReceiptID, SubjectType: "agent_instance", SubjectID: agent,
			Domain: "tool", Action: r.Action, ResourceType: "tool", ResourceValue: r.Tool,
			Effect: receiptEffect(r.Action), State: StateObserved, Authority: "agentshield",
			Source: "receipt", ReceiptID: r.ReceiptID,
		})
	}
	return out
}

func coerceState(domain, state string) string {
	if state == StateEffective && (domain == "filesystem" || domain == "process") {
		return StateDeclared
	}
	return state
}

func receiptEffect(action string) string {
	if action == "allow" || action == "redact" {
		return "allow"
	}
	return "deny"
}

func nonempty(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	var b [20]byte
	n := len(b)
	for i > 0 {
		n--
		b[n] = byte('0' + i%10)
		i /= 10
	}
	return string(b[n:])
}

// Assets projects inventory candidates. idFilter empty = all.
func Assets(s Snapshot) []Asset {
	byHash := map[string]admission.Admission{}
	for _, a := range s.Admissions {
		byHash[a.ContentHash] = a
	}
	grantsByAdm := map[string]grant.Grant{}
	for _, g := range s.Grants {
		if g.Status == "revoked" || g.Status == "rejected" {
			continue
		}
		prev, ok := grantsByAdm[g.AdmissionID]
		if !ok || g.CreatedAt > prev.CreatedAt {
			grantsByAdm[g.AdmissionID] = g
		}
	}
	out := make([]Asset, 0, 8)
	seen := map[string]bool{}
	if s.Report != nil {
		out = make([]Asset, 0, len(s.Report.Candidates)+len(s.Records))
		for _, c := range s.Report.Candidates {
			row := projectAsset(c, byHash, grantsByAdm, s.Report.GeneratedAt)
			row = applyRecord(row, s.Records)
			seen[row.ID] = true
			out = append(out, row)
		}
	}
	for _, rec := range s.Records {
		if seen[rec.CandidateID] {
			continue
		}
		out = append(out, assetFromRecord(rec))
	}
	return out
}

func applyRecord(row Asset, recs []AssetRecord) Asset {
	now := time.Now().UTC()
	for _, rec := range recs {
		if rec.CandidateID != row.ID && !(rec.SourceType == row.SourceType && rec.SourceLocator == row.SourceLocator && rec.SourceLocator != "") {
			continue
		}
		if rec.CandidateID != row.ID && rec.SourceLocator != row.SourceLocator {
			continue
		}
		status := rec.Status
		if status == "dismissed" {
			if until, ok := parseUntil(rec.DismissUntil); !ok || now.After(until) {
				status = row.Status
			} else {
				row.DismissReason = rec.DismissReason
				row.DismissUntil = rec.DismissUntil
			}
		}
		if status != "" && status != "stale" {
			row.Status = status
		}
		if rec.HookLost {
			row.HookLost = true
			if row.Attributes == nil {
				row.Attributes = map[string]string{}
			}
			row.Attributes["hook_lost"] = "true"
		}
		row.ActorID = rec.ActorID
		if rec.UpdatedAt != "" {
			row.UpdatedAt = rec.UpdatedAt
		}
		break
	}
	return row
}

func assetFromRecord(rec AssetRecord) Asset {
	return Asset{
		ID: rec.CandidateID, Name: rec.Name, Framework: rec.Framework, SourceType: rec.SourceType,
		SourceLocator: rec.SourceLocator, Status: rec.Status, AdmissionID: rec.AdmissionID,
		GrantID: rec.GrantID, EvidenceIDs: rec.EvidenceIDs, ContentHash: rec.ContentHash,
		UpdatedAt: rec.UpdatedAt, DismissReason: rec.DismissReason, DismissUntil: rec.DismissUntil,
		HookLost: rec.HookLost, ActorID: rec.ActorID,
	}
}

func projectAsset(c inventory.Candidate, byHash map[string]admission.Admission, grantsByAdm map[string]grant.Grant, generatedAt string) Asset {
	row := Asset{
		ID: c.CandidateID, Name: c.Name, Framework: c.Framework, SourceType: c.SourceType,
		SourceLocator: c.SourceLocator, EvidenceIDs: c.EvidenceIDs, ContentHash: c.ArtifactDigest,
		Attributes: c.Attributes, UpdatedAt: firstNonEmpty(c.DiscoveredAt, generatedAt),
		AdmitPath: admitPath(c.SourceLocator),
	}
	if tools := c.Attributes["allowed_tools"]; tools != "" {
		row.DeclaredTools = splitTools(tools)
	}
	if ts := c.Attributes["toolsets"]; ts != "" {
		row.DeclaredTools = appendUniqueTools(row.DeclaredTools, splitTools(ts))
	}
	if ts := c.Attributes["platform_toolsets"]; ts != "" {
		row.DeclaredTools = appendUniqueTools(row.DeclaredTools, splitTools(ts))
	}
	if adm, ok := byHash[c.ArtifactDigest]; ok {
		row.AdmissionID = adm.AdmissionID
		row.AdmissionVerdict = adm.Verdict
		if g, ok := grantsByAdm[adm.AdmissionID]; ok {
			row.GrantID = g.GrantID
			row.GrantStatus = g.Status
		}
	} else if v := c.Attributes["admission_verdict"]; v != "" && v != "none" {
		row.AdmissionVerdict = v
	}
	row.Status = assetStatus(c.SourceType, row.AdmissionVerdict)
	return row
}

func assetStatus(sourceType, verdict string) string {
	if sourceType != "skill_dir" {
		return "candidate"
	}
	switch verdict {
	case "", "none":
		return "unadmitted"
	case "quarantine":
		return "quarantined"
	default:
		return "admitted"
	}
}

func admitPath(locator string) string {
	_, rest, ok := strings.Cut(locator, "://skills/")
	if !ok {
		return ""
	}
	if strings.HasPrefix(rest, "~") || strings.HasPrefix(rest, "/") {
		return rest
	}
	return ""
}

func splitTools(s string) []string {
	fields := strings.FieldsFunc(s, func(r rune) bool {
		return r == ',' || r == ' ' || r == '\t'
	})
	var out []string
	for _, f := range fields {
		if f != "" {
			out = append(out, f)
		}
	}
	return out
}

func appendUniqueTools(dst, extra []string) []string {
	seen := map[string]bool{}
	for _, t := range dst {
		seen[t] = true
	}
	for _, t := range extra {
		if t == "" || seen[t] {
			continue
		}
		seen[t] = true
		dst = append(dst, t)
	}
	return dst
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// AssetByID returns one asset with evidence and linked admission/grants.
func AssetByID(s Snapshot, id string) (AssetDetail, bool) {
	if decoded, err := url.PathUnescape(id); err == nil {
		id = decoded
	}
	for _, row := range Assets(s) {
		if row.ID != id {
			continue
		}
		d := AssetDetail{Asset: row}
		if s.Report != nil {
			want := map[string]bool{}
			for _, e := range row.EvidenceIDs {
				want[e] = true
			}
			for _, ev := range s.Report.Evidence {
				if want[ev.EvidenceID] {
					d.Evidence = append(d.Evidence, ev)
				}
			}
		}
		if row.AdmissionID != "" {
			for i := range s.Admissions {
				if s.Admissions[i].AdmissionID == row.AdmissionID {
					a := s.Admissions[i]
					d.Admission = &a
					if len(row.DeclaredTools) == 0 {
						d.DeclaredTools = toolsFromAdmission(a)
					}
					break
				}
			}
		}
		for _, g := range s.Grants {
			if row.AdmissionID != "" && g.AdmissionID == row.AdmissionID {
				d.Grants = append(d.Grants, g)
			}
		}
		return d, true
	}
	return AssetDetail{}, false
}

func toolsFromAdmission(a admission.Admission) []string {
	seen := map[string]bool{}
	var out []string
	for _, f := range a.DeclaredFacts {
		if f.Domain != "tool" {
			continue
		}
		v := f.Resource.Value
		if v == "" || seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	return out
}

// Findings flattens admission findings plus persisted drift/accept overlays.
func Findings(s Snapshot) []FindingRow {
	var out []FindingRow
	seen := map[string]bool{}
	for _, a := range s.Admissions {
		for _, f := range a.Findings {
			out = append(out, FindingRow{
				FindingID: f.FindingID, RuleID: f.RuleID, Category: f.Category,
				Severity: f.Severity, Disposition: f.Disposition, Status: "open",
				AdmissionID: a.AdmissionID, SkillName: a.SkillName,
				Path: f.Location.Path, Line: f.Location.Line, Excerpt: f.Excerpt,
				EvidenceIDs: f.EvidenceIDs, Source: "admission",
			})
			seen[f.FindingID] = true
		}
	}
	now := time.Now().UTC()
	byID := map[string]FindingRecord{}
	for _, rec := range s.FindingRecords {
		byID[rec.FindingID] = rec
		if rec.Source == "drift" && !seen[rec.FindingID] {
			st := rec.Status
			if st == "accepted" {
				if until, ok := parseUntil(rec.AcceptUntil); !ok || now.After(until) {
					st = "open"
				}
			}
			if st == "" {
				st = "open"
			}
			out = append(out, FindingRow{
				FindingID: rec.FindingID, RuleID: rec.RuleID, Category: rec.Category,
				Severity: rec.Severity, Disposition: rec.Disposition, Status: st,
				AdmissionID: rec.AdmissionID, SkillName: rec.SkillName,
				EvidenceIDs: rec.EvidenceIDs, Source: "drift", SubjectRef: rec.SubjectRef,
				AcceptReason: rec.AcceptReason, AcceptUntil: rec.AcceptUntil,
			})
			seen[rec.FindingID] = true
		}
	}
	for i := range out {
		rec, ok := byID[out[i].FindingID]
		if !ok {
			continue
		}
		if rec.Status == "accepted" {
			if until, ok := parseUntil(rec.AcceptUntil); ok && !now.After(until) {
				out[i].Status = "accepted"
				out[i].AcceptReason = rec.AcceptReason
				out[i].AcceptUntil = rec.AcceptUntil
			} else {
				out[i].Status = "open"
			}
		}
	}
	return out
}

// Counts returns overview KPIs.
func Counts(s Snapshot) Overview {
	assets := Assets(s)
	o := Overview{Assets: len(assets)}
	for _, a := range assets {
		if a.Status == "unadmitted" {
			o.UnadmittedSkills++
		}
	}
	for _, f := range Findings(s) {
		if f.Status == "accepted" {
			continue
		}
		if f.Disposition == "quarantine" || f.Severity == "critical" || f.Severity == "high" {
			o.OpenFindings++
		}
	}
	for _, r := range s.Receipts {
		if r.Action == "deny" {
			o.RecentDenies++
		}
	}
	for _, g := range s.Grants {
		if g.Status == "deployed" || g.Status == "effective" {
			o.GrantsDeployed++
		}
	}
	return o
}

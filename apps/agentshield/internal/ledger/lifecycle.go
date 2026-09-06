package ledger

import (
	"encoding/json"
	"errors"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// AssetRecord is the versioned <state>/assets document (dev-spec §3.8.1.2).
type AssetRecord struct {
	AssetID       string   `json:"asset_id"`
	CandidateID   string   `json:"candidate_id"`
	SourceType    string   `json:"source_type"`
	SourceLocator string   `json:"source_locator"`
	Framework     string   `json:"framework"`
	Name          string   `json:"name"`
	Status        string   `json:"status"`
	EvidenceIDs   []string `json:"evidence_ids"`
	AdmissionID   string   `json:"admission_id,omitempty"`
	GrantID       string   `json:"grant_id,omitempty"`
	DismissReason string   `json:"dismiss_reason,omitempty"`
	DismissUntil  string   `json:"dismiss_until,omitempty"`
	ContentHash   string   `json:"content_hash,omitempty"`
	HookLost      bool     `json:"hook_lost,omitempty"`
	ActorID       string   `json:"actor_id,omitempty"`
	ToolHook      string   `json:"tool_hook,omitempty"`
	UpdatedAt     string   `json:"updated_at"`
	Signature     string   `json:"signature"`
}

// FindingRecord is a persisted finding or accept overlay.
type FindingRecord struct {
	FindingID    string   `json:"finding_id"`
	RuleID       string   `json:"rule_id"`
	Category     string   `json:"category"`
	Severity     string   `json:"severity"`
	Disposition  string   `json:"disposition"`
	Status       string   `json:"status"`
	Source       string   `json:"source"`
	SubjectRef   string   `json:"subject_ref,omitempty"`
	AdmissionID  string   `json:"admission_id,omitempty"`
	SkillName    string   `json:"skill_name,omitempty"`
	AcceptReason string   `json:"accept_reason,omitempty"`
	AcceptUntil  string   `json:"accept_until,omitempty"`
	ActorID      string   `json:"actor_id,omitempty"`
	EvidenceIDs  []string `json:"evidence_ids,omitempty"`
	UpdatedAt    string   `json:"updated_at"`
	Signature    string   `json:"signature"`
}

func signRecord(key *signing.Key, v any) string {
	if key == nil {
		return ""
	}
	raw, _ := json.Marshal(v)
	dec, err := canon.Decode(raw)
	if err != nil {
		return ""
	}
	m, _ := dec.(map[string]any)
	delete(m, "signature")
	sig, _ := key.SignCanonical(m)
	return sig
}

func loadAssetRecords(st *state.Store) ([]AssetRecord, error) {
	raws, err := st.LatestVersioned("assets")
	if err != nil {
		return nil, err
	}
	var out []AssetRecord
	for _, raw := range raws {
		var rec AssetRecord
		if json.Unmarshal(raw, &rec) != nil || rec.CandidateID == "" {
			return nil, errors.New("ledger: malformed asset record")
		}
		out = append(out, rec)
	}
	return out, nil
}

func loadFindingRecords(st *state.Store) ([]FindingRecord, error) {
	raws, err := st.LatestVersioned("findings")
	if err != nil {
		return nil, err
	}
	var out []FindingRecord
	for _, raw := range raws {
		var rec FindingRecord
		if json.Unmarshal(raw, &rec) != nil || rec.FindingID == "" {
			return nil, errors.New("ledger: malformed finding record")
		}
		out = append(out, rec)
	}
	return out, nil
}

func putAsset(st *state.Store, key *signing.Key, rec AssetRecord) error {
	rec.Signature = ""
	rec.Signature = signRecord(key, rec)
	return st.PutVersioned("assets", state.FileID("ast-", rec.CandidateID), rec)
}

func putFinding(st *state.Store, key *signing.Key, rec FindingRecord) error {
	rec.Signature = ""
	rec.Signature = signRecord(key, rec)
	return st.PutVersioned("findings", state.FileID("fnd-", rec.FindingID), rec)
}

func recordsEqual(a, b AssetRecord) bool {
	return a.Status == b.Status && a.ContentHash == b.ContentHash && a.HookLost == b.HookLost &&
		a.DismissReason == b.DismissReason && a.DismissUntil == b.DismissUntil &&
		a.AdmissionID == b.AdmissionID && a.GrantID == b.GrantID && a.ToolHook == b.ToolHook &&
		a.Name == b.Name && a.SourceLocator == b.SourceLocator && a.CandidateID == b.CandidateID
}

func needsPersist(rec AssetRecord) bool {
	switch rec.Status {
	case "confirmed", "dismissed", "needs_review", "stale":
		return true
	}
	return rec.HookLost
}

func stableKey(sourceType, locator, id string) string {
	if locator != "" && (sourceType == "skill_dir" || sourceType == "hermes_profile" || sourceType == "openclaw_agent" || sourceType == "platform_config") {
		return sourceType + "|" + locator
	}
	return id
}

func parseUntil(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		t, err = time.Parse(time.RFC3339Nano, s)
	}
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

func revokeLinked(st *state.Store, key *signing.Key, grants []grant.Grant, admissionID, grantID, now, actor string) ([]grant.Grant, error) {
	if admissionID == "" && grantID == "" {
		return grants, nil
	}
	out := make([]grant.Grant, 0, len(grants))
	for _, g := range grants {
		match := (admissionID != "" && g.AdmissionID == admissionID) || (grantID != "" && g.GrantID == grantID)
		if !match || g.Status == "revoked" || g.Status == "rejected" {
			out = append(out, g)
			continue
		}
		ng, err := grant.Revoke(g, key)
		if err != nil {
			return nil, err
		}
		if err := st.PutGrant(ng); err != nil {
			return nil, err
		}
		if err := st.AppendAudit(state.AuditEvent{At: now, Event: "grant_revoke", ActorID: actor, Target: ng.GrantID, Note: "lifecycle"}); err != nil {
			return nil, err
		}
		out = append(out, ng)
	}
	return out, nil
}

func attr(c inventory.Candidate, k string) string {
	if c.Attributes == nil {
		return ""
	}
	return c.Attributes[k]
}

func overlayLive(row Asset, stored AssetRecord, hasStored bool, c inventory.Candidate, now time.Time) (AssetRecord, bool) {
	rec := AssetRecord{
		AssetID: c.CandidateID, CandidateID: c.CandidateID, SourceType: c.SourceType,
		SourceLocator: c.SourceLocator, Framework: c.Framework, Name: c.Name,
		Status: row.Status, EvidenceIDs: c.EvidenceIDs, AdmissionID: row.AdmissionID,
		GrantID: row.GrantID, ContentHash: c.ArtifactDigest, UpdatedAt: now.Format(time.RFC3339),
		ToolHook: attr(c, "agentshield_tool_hook"),
	}
	revoke := false
	if !hasStored {
		return rec, false
	}
	rec.ActorID = stored.ActorID
	if stored.Status == "dismissed" {
		until, has := parseUntil(stored.DismissUntil)
		if has && !until.IsZero() && !now.After(until) {
			rec.Status = "dismissed"
			rec.DismissReason = stored.DismissReason
			rec.DismissUntil = stored.DismissUntil
		}
	}
	if row.Status == "quarantined" {
		rec.Status = "quarantined"
	} else if stored.Status == "confirmed" && rec.Status != "needs_review" && rec.Status != "dismissed" {
		rec.Status = "confirmed"
	}
	if c.SourceType == "skill_dir" && stored.ContentHash != "" && stored.ContentHash != c.ArtifactDigest {
		rec.Status = "needs_review"
		revoke = true
	}
	if stored.CandidateID != c.CandidateID && stored.SourceType == "skill_dir" {
		rec.Status = "needs_review"
		revoke = true
	}
	if stored.ToolHook == "true" && rec.ToolHook != "true" {
		rec.Status = "needs_review"
		rec.HookLost = true
	}
	return rec, revoke
}

// Refresh applies G7 transitions, writes dirty asset records, revokes grants.
func Refresh(st *state.Store, key *signing.Key, snap *Snapshot, now time.Time) error {
	if st == nil || snap == nil {
		return nil
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	nowS := now.Format(time.RFC3339)
	prev, err := loadAssetRecords(st)
	if err != nil {
		return err
	}
	findings, err := loadFindingRecords(st)
	if err != nil {
		return err
	}
	byID := map[string]AssetRecord{}
	byStable := map[string]AssetRecord{}
	for _, rec := range prev {
		byID[rec.CandidateID] = rec
		byStable[stableKey(rec.SourceType, rec.SourceLocator, rec.CandidateID)] = rec
	}
	liveIDs := map[string]bool{}
	var next []AssetRecord
	grants := snap.Grants
	byHash := map[string]admission.Admission{}
	for _, a := range snap.Admissions {
		byHash[a.ContentHash] = a
	}
	grantsByAdm := map[string]grant.Grant{}
	for _, g := range snap.Grants {
		if g.Status == "revoked" || g.Status == "rejected" {
			continue
		}
		prevG, ok := grantsByAdm[g.AdmissionID]
		if !ok || g.CreatedAt > prevG.CreatedAt {
			grantsByAdm[g.AdmissionID] = g
		}
	}

	if snap.Report != nil {
		for _, c := range snap.Report.Candidates {
			liveIDs[c.CandidateID] = true
			row := projectAsset(c, byHash, grantsByAdm, snap.Report.GeneratedAt)
			stored, ok := byID[c.CandidateID]
			if !ok {
				stored, ok = byStable[stableKey(c.SourceType, c.SourceLocator, c.CandidateID)]
			}
			rec, revoke := overlayLive(row, stored, ok, c, now)
			if revoke {
				grants, err = revokeLinked(st, key, grants, stored.AdmissionID, stored.GrantID, nowS, "lifecycle")
				if err != nil {
					return err
				}
			}
			if needsPersist(rec) {
				var prevPtr *AssetRecord
				if ok && stored.CandidateID == rec.CandidateID {
					p := stored
					prevPtr = &p
				}
				if prevPtr == nil || !recordsEqual(*prevPtr, rec) {
					rec.UpdatedAt = nowS
					if err := putAsset(st, key, rec); err != nil {
						return err
					}
				}
			}
			next = append(next, rec)
		}
	}

	for _, stored := range prev {
		if liveIDs[stored.CandidateID] {
			continue
		}
		rec := stored
		if rec.Status != "stale" {
			rec.Status = "stale"
			rec.UpdatedAt = nowS
			if err := putAsset(st, key, rec); err != nil {
				return err
			}
			if err := st.AppendAudit(state.AuditEvent{At: nowS, Event: "asset_stale", Target: rec.CandidateID, Note: "source gone"}); err != nil {
				return err
			}
			grants, err = revokeLinked(st, key, grants, rec.AdmissionID, rec.GrantID, nowS, "lifecycle")
			if err != nil {
				return err
			}
		}
		next = append(next, rec)
	}

	snap.Records = next
	snap.FindingRecords = findings
	snap.Grants = grants
	return nil
}

func WriteFinding(st *state.Store, key *signing.Key, rec FindingRecord) error {
	if rec.UpdatedAt == "" {
		rec.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	}
	return putFinding(st, key, rec)
}

// Confirm writes a confirmed asset record.
func Confirm(st *state.Store, key *signing.Key, snap Snapshot, id, actor string, now time.Time) (AssetRecord, error) {
	if actor == "" {
		return AssetRecord{}, errActor
	}
	row, ok := AssetByID(snap, id)
	if !ok {
		return AssetRecord{}, errNotFound
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	rec := recordFromAsset(row.Asset, actor, now)
	rec.Status = "confirmed"
	rec.DismissReason = ""
	rec.DismissUntil = ""
	if err := putAsset(st, key, rec); err != nil {
		return rec, err
	}
	_ = st.AppendAudit(state.AuditEvent{At: rec.UpdatedAt, Event: "asset_confirm", ActorID: actor, Target: rec.CandidateID})
	return rec, nil
}

// Dismiss writes a dismissed record; reason and until required.
func Dismiss(st *state.Store, key *signing.Key, snap Snapshot, id, actor, reason, until string, now time.Time) (AssetRecord, error) {
	if actor == "" || strings.TrimSpace(reason) == "" || strings.TrimSpace(until) == "" {
		return AssetRecord{}, errDismiss
	}
	if _, ok := parseUntil(until); !ok {
		return AssetRecord{}, errDismiss
	}
	row, ok := AssetByID(snap, id)
	if !ok {
		return AssetRecord{}, errNotFound
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	rec := recordFromAsset(row.Asset, actor, now)
	rec.Status = "dismissed"
	rec.DismissReason = reason
	rec.DismissUntil = until
	if err := putAsset(st, key, rec); err != nil {
		return rec, err
	}
	_ = st.AppendAudit(state.AuditEvent{At: rec.UpdatedAt, Event: "asset_dismiss", ActorID: actor, Target: rec.CandidateID, Note: "until"})
	return rec, nil
}

// AcceptFinding writes an accept overlay; reason and until required.
func AcceptFinding(st *state.Store, key *signing.Key, snap Snapshot, id, actor, reason, until string, now time.Time) (FindingRecord, error) {
	if actor == "" || strings.TrimSpace(reason) == "" || strings.TrimSpace(until) == "" {
		return FindingRecord{}, errDismiss
	}
	if _, ok := parseUntil(until); !ok {
		return FindingRecord{}, errDismiss
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	base := FindingRecord{FindingID: id, Status: "accepted", Source: "admission"}
	for _, f := range Findings(snap) {
		if f.FindingID == id {
			base.RuleID = f.RuleID
			base.Category = f.Category
			base.Severity = f.Severity
			base.Disposition = f.Disposition
			base.AdmissionID = f.AdmissionID
			base.SkillName = f.SkillName
			base.EvidenceIDs = f.EvidenceIDs
			base.Source = nonempty(f.Source, "admission")
			break
		}
	}
	base.AcceptReason = reason
	base.AcceptUntil = until
	base.ActorID = actor
	base.UpdatedAt = now.Format(time.RFC3339)
	base.Status = "accepted"
	if err := putFinding(st, key, base); err != nil {
		return base, err
	}
	_ = st.AppendAudit(state.AuditEvent{At: base.UpdatedAt, Event: "finding_accept", ActorID: actor, Target: id, Note: "until"})
	return base, nil
}

func recordFromAsset(a Asset, actor string, now time.Time) AssetRecord {
	hook := ""
	if a.Attributes != nil {
		hook = a.Attributes["agentshield_tool_hook"]
	}
	return AssetRecord{
		AssetID: a.ID, CandidateID: a.ID, SourceType: a.SourceType, SourceLocator: a.SourceLocator,
		Framework: a.Framework, Name: a.Name, Status: a.Status, EvidenceIDs: a.EvidenceIDs,
		AdmissionID: a.AdmissionID, GrantID: a.GrantID, ContentHash: a.ContentHash,
		ToolHook: hook, ActorID: actor, UpdatedAt: now.Format(time.RFC3339),
	}
}

var (
	errActor    = errText("actor_id required")
	errNotFound = errText("asset not found")
	errDismiss  = errText("actor_id, reason and until (RFC3339) required")
)

type errText string

func (e errText) Error() string { return string(e) }

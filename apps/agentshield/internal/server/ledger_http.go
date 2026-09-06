package server

import (
	"errors"
	"net/http"
	"strings"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/state"
)

// ProjectionMeta describes the cached ledger read view (DEV16-B).
type ProjectionMeta struct {
	Revision    uint64 `json:"revision"`
	GeneratedAt string `json:"generated_at,omitempty"`
	Health      string `json:"health"` // ok | stale | unavailable
	LastError   string `json:"last_error,omitempty"`
	AgeMS       int64  `json:"age_ms"`
}

type projectionCache struct {
	mu     sync.RWMutex
	snap   ledger.Snapshot
	cwd    string
	rev    uint64
	at     time.Time
	health string
	err    string
}

var errProjectionUnavailable = errors.New("projection unavailable")

func truncateProjErr(err error) string {
	if err == nil {
		return ""
	}
	msg := err.Error()
	if len(msg) > 240 {
		return msg[:240]
	}
	return msg
}

// buildSnapshot runs inventory + lifecycle write path (not for plain GET).
func (s *Server) buildSnapshot(cwd string) (ledger.Snapshot, error) {
	rep, err := s.runInventory(cwd)
	if err != nil {
		return ledger.Snapshot{}, err
	}
	admissions, err := s.d.Store.ListAdmissions()
	if err != nil {
		return ledger.Snapshot{}, err
	}
	grants, err := s.d.Store.ListGrants()
	if err != nil {
		return ledger.Snapshot{}, err
	}
	receipts, err := s.d.Chain.Read()
	if err != nil {
		return ledger.Snapshot{}, err
	}
	snap := ledger.Snapshot{Report: rep, Admissions: admissions, Grants: grants, Receipts: receipts}
	if err := ledger.Refresh(s.d.Store, s.d.Key, &snap, time.Now().UTC()); err != nil {
		return ledger.Snapshot{}, err
	}
	return snap, nil
}

func (s *Server) publishProjection(cwd string, snap ledger.Snapshot, buildErr error) {
	s.proj.mu.Lock()
	defer s.proj.mu.Unlock()
	if buildErr != nil {
		s.proj.err = truncateProjErr(buildErr)
		if s.proj.rev > 0 {
			s.proj.health = "stale"
			return
		}
		s.proj.health = "unavailable"
		return
	}
	s.proj.snap = snap
	s.proj.cwd = cwd
	s.proj.rev++
	s.proj.at = time.Now().UTC()
	s.proj.health = "ok"
	s.proj.err = ""
}

// Refresh rebuilds the projection (serve ticker, tests, explicit rebuild).
func (s *Server) Refresh(cwd string) error {
	snap, err := s.buildSnapshot(cwd)
	s.publishProjection(cwd, snap, err)
	return err
}

// invalidateProjection marks a prior view stale so the next GET rebuilds once
// (grant/decide/admit mutations). Does not drop the last good snap.
func (s *Server) invalidateProjection(note string) {
	s.proj.mu.Lock()
	defer s.proj.mu.Unlock()
	if s.proj.rev == 0 {
		return
	}
	s.proj.health = "stale"
	if note != "" {
		s.proj.err = note
	}
}

func (s *Server) projectionMetaLocked() ProjectionMeta {
	m := ProjectionMeta{Revision: s.proj.rev, Health: s.proj.health, LastError: s.proj.err}
	if m.Health == "" {
		m.Health = "unavailable"
	}
	if !s.proj.at.IsZero() {
		m.GeneratedAt = s.proj.at.UTC().Format(time.RFC3339)
		m.AgeMS = time.Since(s.proj.at).Milliseconds()
		if m.AgeMS < 0 {
			m.AgeMS = 0
		}
	}
	return m
}

// readProjection returns the cached GET view. Bootstraps when empty; rebuilds
// at most once when health=stale. On rebuild failure with a prior revision,
// returns the old snap with health=stale (never a fabricated empty success).
func (s *Server) readProjection(cwd string) (ledger.Snapshot, ProjectionMeta, error) {
	s.proj.mu.RLock()
	need := s.proj.rev == 0 || s.proj.health == "stale" || s.proj.health == ""
	s.proj.mu.RUnlock()
	if need {
		if err := s.Refresh(cwd); err != nil {
			s.proj.mu.RLock()
			meta := s.projectionMetaLocked()
			snap := s.proj.snap
			rev := s.proj.rev
			health := s.proj.health
			s.proj.mu.RUnlock()
			if rev > 0 && health == "stale" {
				return snap, meta, nil
			}
			return ledger.Snapshot{}, meta, err
		}
	}
	s.proj.mu.RLock()
	defer s.proj.mu.RUnlock()
	meta := s.projectionMetaLocked()
	if s.proj.rev == 0 || s.proj.health == "unavailable" {
		return ledger.Snapshot{}, meta, errProjectionUnavailable
	}
	return s.proj.snap, meta, nil
}

// snapshotForWrite rebuilds for mutations (confirm/dismiss/accept) and publishes.
func (s *Server) snapshotForWrite(cwd string) (ledger.Snapshot, error) {
	snap, err := s.buildSnapshot(cwd)
	s.publishProjection(cwd, snap, err)
	return snap, err
}

func (s *Server) assets(w http.ResponseWriter, r *http.Request) {
	rest := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/assets"), "/")
	parts := splitPath(rest)
	if r.Method == http.MethodGet && len(parts) == 0 {
		snap, meta, err := s.readProjection(r.URL.Query().Get("cwd"))
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "inventory failed", "projection": meta})
			return
		}
		writeJSON(w, 200, map[string]any{"assets": ledger.Assets(snap), "overview": ledger.Counts(snap), "projection": meta})
		return
	}
	if r.Method == http.MethodGet && len(parts) == 1 {
		snap, meta, err := s.readProjection(r.URL.Query().Get("cwd"))
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "inventory failed", "projection": meta})
			return
		}
		detail, ok := ledger.AssetByID(snap, parts[0])
		if !ok {
			writeJSON(w, 404, map[string]any{"error": "asset not found", "projection": meta})
			return
		}
		writeJSON(w, 200, detail)
		return
	}
	if r.Method == http.MethodPost && len(parts) == 2 {
		s.assetAction(w, r, parts[0], parts[1])
		return
	}
	writeJSON(w, 405, map[string]any{"error": "method or path not allowed"})
}

func (s *Server) assetAction(w http.ResponseWriter, r *http.Request, id, action string) {
	var body struct {
		ActorID string `json:"actor_id"`
		Reason  string `json:"reason"`
		Until   string `json:"until"`
	}
	_ = readJSON(r, &body, 64<<10)
	snap, err := s.snapshotForWrite(r.URL.Query().Get("cwd"))
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "inventory failed"})
		return
	}
	now := time.Now().UTC()
	switch action {
	case "confirm":
		rec, err := ledger.Confirm(s.d.Store, s.d.Key, snap, id, body.ActorID, now)
		if err != nil {
			code := 400
			if err.Error() == "asset not found" {
				code = 404
			}
			writeJSON(w, code, map[string]any{"error": err.Error()})
			return
		}
		_ = s.Refresh(r.URL.Query().Get("cwd"))
		writeJSON(w, 200, map[string]any{"asset": rec})
	case "dismiss":
		rec, err := ledger.Dismiss(s.d.Store, s.d.Key, snap, id, body.ActorID, body.Reason, body.Until, now)
		if err != nil {
			code := 400
			if err.Error() == "asset not found" {
				code = 404
			}
			writeJSON(w, code, map[string]any{"error": err.Error()})
			return
		}
		_ = s.Refresh(r.URL.Query().Get("cwd"))
		writeJSON(w, 200, map[string]any{"asset": rec})
	default:
		writeJSON(w, 404, map[string]any{"error": "unknown action"})
	}
}

func (s *Server) permissions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	snap, meta, err := s.readProjection(r.URL.Query().Get("cwd"))
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "inventory failed", "projection": meta})
		return
	}
	writeJSON(w, 200, map[string]any{"facts": ledger.Permissions(snap, r.URL.Query().Get("subject_id")), "projection": meta})
}

func (s *Server) findings(w http.ResponseWriter, r *http.Request) {
	rest := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/findings"), "/")
	parts := splitPath(rest)
	if r.Method == http.MethodGet && len(parts) == 0 {
		snap, meta, err := s.readProjection("")
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "snapshot unavailable", "projection": meta})
			return
		}
		writeJSON(w, 200, map[string]any{"findings": ledger.Findings(snap), "projection": meta})
		return
	}
	if r.Method == http.MethodPost && len(parts) == 2 && parts[1] == "accept" {
		var body struct {
			ActorID string `json:"actor_id"`
			Reason  string `json:"reason"`
			Until   string `json:"until"`
		}
		if err := readJSON(r, &body, 16<<10); err != nil {
			writeJSON(w, 400, map[string]any{"error": "invalid json"})
			return
		}
		snap, err := s.snapshotForWrite("")
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "snapshot unavailable"})
			return
		}
		rec, err := ledger.AcceptFinding(s.d.Store, s.d.Key, snap, parts[0], body.ActorID, body.Reason, body.Until, time.Now().UTC())
		if err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
		_ = s.Refresh("")
		writeJSON(w, 200, map[string]any{"finding": rec})
		return
	}
	writeJSON(w, 405, map[string]any{"error": "method or path not allowed"})
}

func (s *Server) auditLog(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	evs, err := s.d.Store.TailAudit(200)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "audit unreadable"})
		return
	}
	writeJSON(w, 200, map[string]any{"events": evs})
}

func (s *Server) openshellDriftCheck(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	if s.d.Openshell == nil {
		writeJSON(w, 503, map[string]any{"error": "OpenShell CLI 未配置"})
		return
	}
	row := s.openshellPlatform(true)
	if row.Tier != "L3" {
		writeJSON(w, 503, map[string]any{"error": "OpenShell L3 不可用: " + row.Note})
		return
	}
	grants, err := s.d.Store.ListGrants()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "store unreadable"})
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	var written []string
	for _, g := range grants {
		if g.Status != "deployed" && g.Status != "effective" {
			continue
		}
		want := grantNetwork(g)
		if len(want) == 0 {
			continue
		}
		snap, err := s.d.Openshell.ReadEffective(g.Subject.ID)
		if err != nil {
			writeJSON(w, 502, map[string]any{"error": "OpenShell 读回失败，未写入无漂移结论: " + sanitizeOpenshellErr(err)})
			return
		}
		got := map[string]bool{}
		for _, nr := range snap.Network {
			got[strings.ToLower(nr.Endpoint)] = true
		}
		var missing []string
		for ep := range want {
			if !got[strings.ToLower(ep)] {
				missing = append(missing, ep)
			}
		}
		if len(missing) == 0 {
			continue
		}
		fid := "drift-" + g.GrantID
		rec := ledger.FindingRecord{
			FindingID: fid, RuleID: "openshell.network_drift", Category: "drift",
			Severity: "medium", Disposition: "review", Status: "open", Source: "drift",
			SubjectRef: g.Subject.ID, SkillName: g.GrantID, UpdatedAt: now,
		}
		if err := ledger.WriteFinding(s.d.Store, s.d.Key, rec); err != nil {
			writeJSON(w, 500, map[string]any{"error": "finding store failed"})
			return
		}
		_ = s.d.Store.AppendAudit(state.AuditEvent{At: now, Event: "drift_finding", Target: g.GrantID, Note: "network"})
		written = append(written, fid)
	}
	writeJSON(w, 200, map[string]any{"ok": true, "findings_written": written})
}

func grantNetwork(g grant.Grant) map[string]bool {
	out := map[string]bool{}
	for _, f := range g.Facts {
		if f.Domain == "network" && f.Effect == "allow" && f.Resource.Value != "" {
			out[f.Resource.Value] = true
		}
	}
	return out
}

func splitPath(rest string) []string {
	if rest == "" {
		return nil
	}
	var parts []string
	for _, p := range strings.Split(rest, "/") {
		if p != "" {
			parts = append(parts, p)
		}
	}
	return parts
}

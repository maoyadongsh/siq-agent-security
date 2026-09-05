package server

import (
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/state"
)

func (s *Server) snapshot(cwd string) (ledger.Snapshot, error) {
	rep, err := s.runInventory(cwd)
	if err != nil {
		return ledger.Snapshot{}, err
	}
	admissions, _ := s.d.Store.ListAdmissions()
	grants, _ := s.d.Store.ListGrants()
	receipts, _ := s.d.Chain.Read()
	snap := ledger.Snapshot{Report: rep, Admissions: admissions, Grants: grants, Receipts: receipts}
	_ = ledger.Refresh(s.d.Store, s.d.Key, &snap, time.Now().UTC())
	return snap, nil
}

// Refresh runs inventory + G7 lifecycle (serve ticker and tests).
func (s *Server) Refresh(cwd string) error {
	_, err := s.snapshot(cwd)
	return err
}

func (s *Server) assets(w http.ResponseWriter, r *http.Request) {
	rest := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/assets"), "/")
	parts := splitPath(rest)
	if r.Method == http.MethodGet && len(parts) == 0 {
		snap, err := s.snapshot(r.URL.Query().Get("cwd"))
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "inventory failed"})
			return
		}
		writeJSON(w, 200, map[string]any{"assets": ledger.Assets(snap), "overview": ledger.Counts(snap)})
		return
	}
	if r.Method == http.MethodGet && len(parts) == 1 {
		snap, err := s.snapshot(r.URL.Query().Get("cwd"))
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "inventory failed"})
			return
		}
		detail, ok := ledger.AssetByID(snap, parts[0])
		if !ok {
			writeJSON(w, 404, map[string]any{"error": "asset not found"})
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
	snap, err := s.snapshot(r.URL.Query().Get("cwd"))
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
	snap, err := s.snapshot(r.URL.Query().Get("cwd"))
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "inventory failed"})
		return
	}
	writeJSON(w, 200, map[string]any{"facts": ledger.Permissions(snap, r.URL.Query().Get("subject_id"))})
}

func (s *Server) findings(w http.ResponseWriter, r *http.Request) {
	rest := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/findings"), "/")
	parts := splitPath(rest)
	if r.Method == http.MethodGet && len(parts) == 0 {
		snap, err := s.snapshot("")
		if err != nil {
			admissions, _ := s.d.Store.ListAdmissions()
			writeJSON(w, 200, map[string]any{"findings": ledger.Findings(ledger.Snapshot{Admissions: admissions})})
			return
		}
		writeJSON(w, 200, map[string]any{"findings": ledger.Findings(snap)})
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
		snap, _ := s.snapshot("")
		rec, err := ledger.AcceptFinding(s.d.Store, s.d.Key, snap, parts[0], body.ActorID, body.Reason, body.Until, time.Now().UTC())
		if err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
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

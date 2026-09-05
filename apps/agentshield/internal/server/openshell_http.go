package server

import (
	"errors"
	"net/http"
	"runtime"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
)

func (s *Server) openshellPlatform(refresh bool) PlatformInfo {
	row := PlatformInfo{Name: "openshell", Detected: false, Adapter: "unconfigured", Tier: "L0", Note: "未配置 CLI/网关"}
	if s.d.Openshell == nil {
		s.osMu.Lock()
		s.osDiag = openshell.UnconfiguredDiagnosis()
		s.osMu.Unlock()
		return row
	}
	s.osMu.Lock()
	defer s.osMu.Unlock()
	if !refresh && !s.osAt.IsZero() && time.Since(s.osAt) < 15*time.Second {
		return s.osRow
	}
	d := s.d.Openshell.Diagnose()
	s.osDiag = d
	if !d.ProbeOK || d.Capabilities == nil {
		row.Note = d.HumanNext
		if row.Note == "" {
			row.Note = sanitizeOpenshellNote(d.Note)
		}
		if runtime.GOOS != "linux" && !strings.Contains(row.Note, "未配置") && !strings.Contains(row.Note, "未在 PATH") {
			row.Note += "；非 Linux 无 Docker/WSL2 时 L3 不可用"
		}
		s.osRow, s.osAt, s.osOK = row, time.Now(), false
		return row
	}
	caps := *d.Capabilities
	row.Detected = true
	row.Adapter = "cli"
	row.Tier = "L3"
	row.Note = d.Note
	s.osRow, s.osAt, s.osOK, s.osCaps = row, time.Now(), true, &caps
	return row
}

func (s *Server) openshellProbe(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	row := s.openshellPlatform(true)
	out := map[string]any{
		"ok": row.Tier == "L3", "tier": row.Tier, "backend": "openshell",
		"detected": row.Detected, "adapter": row.Adapter, "note": row.Note,
	}
	s.osMu.Lock()
	out["doctor"] = s.osDiag
	if s.osOK && s.osCaps != nil {
		out["schema_version"] = s.osCaps.SchemaVersion
		out["dynamic_network_update"] = s.osCaps.DynamicNetworkUpdate
		out["revision_support"] = s.osCaps.RevisionSupport
		out["capabilities"] = s.osCaps.Capabilities
	}
	s.osMu.Unlock()
	writeJSON(w, 200, out)
}

func (s *Server) openshellDoctor(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	if s.d.Openshell == nil {
		writeJSON(w, 200, openshell.UnconfiguredDiagnosis())
		return
	}
	writeJSON(w, 200, s.d.Openshell.Diagnose())
}

func (s *Server) openshellApply(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	if s.d.Openshell == nil {
		writeJSON(w, 503, map[string]any{"error": "OpenShell CLI 未配置"})
		return
	}
	var body struct {
		Target           string                  `json:"target"`
		Network          []openshell.NetworkRule `json:"network"`
		ExpectedRevision string                  `json:"expected_revision"`
		ExpectAllow      []string                `json:"expect_allow"`
		ExpectDeny       []string                `json:"expect_deny"`
	}
	if err := readJSON(r, &body, 64<<10); err != nil || strings.TrimSpace(body.Target) == "" {
		writeJSON(w, 400, map[string]any{"error": "target required"})
		return
	}
	result, err := s.d.Openshell.ApplyAndVerify(body.Target, body.Network, body.ExpectedRevision, body.ExpectAllow, body.ExpectDeny)
	if err != nil {
		var conflict *openshell.RevisionConflict
		if errors.As(err, &conflict) {
			writeJSON(w, 409, map[string]any{"error": "revision conflict", "expected": conflict.Expected, "actual": conflict.Actual})
			return
		}
		if result.Receipt.BackendRevision != "" {
			writeJSON(w, 409, map[string]any{
				"error":              sanitizeOpenshellErr(err),
				"passed":             false,
				"verify_level":       result.Report.Level,
				"failures":           result.Report.Failures,
				"receipt":            result.Receipt,
				"effective_readback": result.Readback,
			})
			return
		}
		writeJSON(w, 400, map[string]any{"error": sanitizeOpenshellErr(err)})
		return
	}
	ev := map[string]any{
		"backend": "openshell", "revision": result.Receipt.BackendRevision,
		"snapshot_hash": result.Receipt.Evidence["snapshot_hash"],
		"verify_level":  result.Report.Level, "target": body.Target,
	}
	_ = s.d.Store.PutEvidence(result.Readback.EvidenceID, ev)
	writeJSON(w, 200, map[string]any{
		"ok": true, "passed": true, "verify_level": result.Report.Level,
		"receipt": result.Receipt, "report": result.Report,
		"effective_readback": result.Readback,
	})
}

func sanitizeOpenshellErr(err error) string {
	if err == nil {
		return ""
	}
	return sanitizeOpenshellNote(err.Error())
}

func sanitizeOpenshellNote(msg string) string {
	if len(msg) > 240 {
		msg = msg[:240]
	}
	return msg
}

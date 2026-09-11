package server

import (
	"errors"
	"net/http"
	"reflect"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/state"
)

type DiscoveryRun struct {
	RunID      string   `json:"run_id,omitempty"`
	State      string   `json:"state"`
	StartedAt  string   `json:"started_at,omitempty"`
	FinishedAt string   `json:"finished_at,omitempty"`
	AssetCount int      `json:"asset_count"`
	SkillCount int      `json:"skill_count"`
	IssueCount int      `json:"issue_count"`
	Issues     []string `json:"issues,omitempty"`
	Error      string   `json:"error,omitempty"`
}

type discoveryRequest struct {
	ProjectDir string `json:"project_dir"`
	SkillDir   string `json:"skill_dir"`
}

func (s *Server) discoveryRoots(r *http.Request) (state.DiscoveryRoots, int, error) {
	roots, revision, err := s.d.Store.LoadDiscoveryRoots()
	if err != nil {
		return roots, revision, errors.New("无法读取已保存的扫描范围")
	}
	var input discoveryRequest
	if err := readJSONStrict(r, &input, 16<<10); err != nil {
		return roots, revision, errors.New("扫描请求格式无效")
	}
	for _, item := range []struct {
		raw   string
		paths *[]string
	}{{input.ProjectDir, &roots.ProjectDirs}, {input.SkillDir, &roots.SkillDirs}} {
		if strings.TrimSpace(item.raw) == "" {
			continue
		}
		path, err := inventory.NormalizeDirectory(s.d.Home, strings.TrimSpace(item.raw))
		if err != nil {
			return roots, revision, err
		}
		found := false
		for _, existing := range *item.paths {
			if path == existing {
				found = true
			}
		}
		if !found {
			*item.paths = append(*item.paths, path)
		}
	}
	if len(roots.ProjectDirs)+len(roots.SkillDirs) > 16 {
		return roots, revision, errors.New("手动扫描目录最多登记 16 个")
	}
	return roots, revision, nil
}

func (s *Server) previewDiscovery(roots state.DiscoveryRoots) []inventory.ScanRoot {
	return inventory.Preview(inventory.Options{Home: s.d.Home, HermesHome: s.d.HermesHome, LocalAppData: s.d.LocalAppData, ProjectDirs: roots.ProjectDirs, SkillDirs: roots.SkillDirs})
}

func (s *Server) discoveryStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	roots, _, err := s.d.Store.LoadDiscoveryRoots()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "discovery scope unreadable"})
		return
	}
	s.discoveryMu.Lock()
	job := s.discoveryRun
	s.discoveryMu.Unlock()
	if job.State == "" {
		job.State = "idle"
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"schema_version": "local-discovery/v1", "run": job, "roots": s.previewDiscovery(roots), "platform_changes": false})
}

func (s *Server) discoveryPreview(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	roots, _, err := s.discoveryRoots(r)
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"schema_version": "local-discovery-preview/v1", "roots": s.previewDiscovery(roots), "platform_changes": false})
}

func (s *Server) discoveryScan(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	s.discoveryMu.Lock()
	defer s.discoveryMu.Unlock()
	if s.discoveryRun.State == "running" {
		writeJSON(w, 409, map[string]any{"error": "已有扫描正在进行，请等待结果"})
		return
	}
	roots, revision, err := s.discoveryRoots(r)
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	current, _, err := s.d.Store.LoadDiscoveryRoots()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "discovery scope unreadable"})
		return
	}
	if !reflect.DeepEqual(current, roots) {
		if err := s.d.Store.SaveDiscoveryRoots(roots, revision); err != nil {
			writeJSON(w, 409, map[string]any{"error": "扫描范围保存失败，请重新预览后重试"})
			return
		}
	}
	id, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "无法创建扫描任务"})
		return
	}
	job := DiscoveryRun{RunID: "scan-" + id[:16], State: "running", StartedAt: time.Now().UTC().Format(time.RFC3339)}
	s.discoveryRun = job
	go s.completeDiscovery(job)
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 202, map[string]any{"schema_version": "local-discovery/v1", "run": job, "roots": s.previewDiscovery(roots), "platform_changes": false})
}

func (s *Server) completeDiscovery(job DiscoveryRun) {
	if err := s.Refresh(""); err != nil {
		job.State, job.Error = "failed", "扫描失败，保留上次结果；请检查状态目录与扫描范围后重试"
	} else {
		s.proj.mu.RLock()
		snap := s.proj.snap
		s.proj.mu.RUnlock()
		job.State = "succeeded"
		job.AssetCount = len(ledger.Assets(snap))
		if snap.Report != nil {
			job.IssueCount = len(snap.Report.Skipped)
			limit := job.IssueCount
			if limit > 100 {
				limit = 100
			}
			job.Issues = append([]string{}, snap.Report.Skipped[:limit]...)
			if job.IssueCount > 0 {
				job.State = "partial"
			}
			for _, candidate := range snap.Report.Candidates {
				if candidate.SourceType == "skill_dir" {
					job.SkillCount++
				}
			}
		}
	}
	job.FinishedAt = time.Now().UTC().Format(time.RFC3339)
	if err := s.d.Store.AppendAudit(state.AuditEvent{At: job.FinishedAt, Event: "discovery_completed", ActorID: "local-admin", Target: job.RunID, Note: job.State}); err != nil {
		job.State, job.Error = "failed", "扫描结果已刷新，但审计记录保存失败；请检查状态目录"
	}
	s.discoveryMu.Lock()
	s.discoveryRun = job
	s.discoveryMu.Unlock()
}

package server

import (
	"context"
	"errors"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/skillimport"
)

func skillImportError(w http.ResponseWriter, err error) {
	status, code := 503, "skill_import_unavailable"
	switch {
	case errors.Is(err, importsource.ErrInvalid):
		status, code = 409, "skill_import_permission_source_invalid"
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		status, code = 408, "skill_import_interrupted"
	case errors.Is(err, skillimport.ErrURLBlocked):
		status, code = 400, "skill_import_url_blocked"
	case errors.Is(err, skillimport.ErrDownloadFailed):
		status, code = 502, "skill_import_download_failed"
	case errors.Is(err, skillimport.ErrArchiveMismatch):
		status, code = 409, "skill_import_archive_mismatch"
	case errors.Is(err, skillimport.ErrInvalid):
		status, code = 400, "skill_import_invalid"
	case errors.Is(err, skillimport.ErrLimit):
		status, code = 413, "skill_import_limit"
	case errors.Is(err, skillimport.ErrNotFound):
		status, code = 404, "skill_import_not_found"
	case errors.Is(err, skillimport.ErrConflict):
		status, code = 409, "skill_import_conflict"
	case errors.Is(err, skillimport.ErrChanged):
		status, code = 409, "skill_import_changed"
	}
	writeJSON(w, status, map[string]string{"error": code})
}
func (s *Server) skillImportSlot(w http.ResponseWriter) bool {
	if !s.skillImportMu.TryLock() {
		w.Header().Set("Retry-After", "1")
		writeJSON(w, 429, map[string]string{"error": "skill_import_busy"})
		return false
	}
	// The server-wide 15s write deadline is shorter than bounded import work.
	if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(65 * time.Second)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		s.skillImportMu.Unlock()
		skillImportError(w, skillimport.ErrUnavailable)
		return false
	}
	return true
}
func (s *Server) skillImportCreate(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		s.skillImportList(w, r)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req skillimport.CreateRequest
	if !readStrictFlatRequest(w, r, &req, "skill_import_invalid", "schema_version", "import_id", "source_kind", "path", "actor_id") {
		return
	}
	if !filepath.IsAbs(req.Path) {
		skillImportError(w, skillimport.ErrInvalid)
		return
	}
	if !s.skillImportSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	record, analysis, reused, err := s.skillImports.Create(ctx, req)
	if err != nil {
		skillImportError(w, err)
		return
	}
	status := 201
	if reused {
		status = 200
	}
	writeJSON(w, status, skillimport.NewResult(record, analysis, reused))
}
func (s *Server) skillImportRead(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/skill-imports/"), "/")
	if len(parts) == 2 && parts[1] == "permissions" {
		s.skillImportPermissions(w, r, parts[0])
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/skill-imports/")
	if id == "" || strings.Contains(id, "/") {
		w.WriteHeader(404)
		return
	}
	if !s.skillImportSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	record, analysis, err := s.skillImports.Load(ctx, id)
	if err != nil {
		skillImportError(w, err)
		return
	}
	writeJSON(w, 200, skillimport.NewResult(record, analysis, true))
}

func (s *Server) skillImportList(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if !s.skillImportSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	result, err := s.skillImports.List(ctx)
	if err != nil {
		skillImportError(w, err)
		return
	}
	writeJSON(w, 200, result)
}

func (s *Server) skillImportRemoteCreate(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req skillimport.RemoteCreateRequest
	if !readStrictFlatRequest(w, r, &req, "skill_import_invalid", "schema_version", "import_id", "url", "archive_path", "expected_sha256", "actor_id") {
		return
	}
	if !s.skillImportSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	record, analysis, reused, err := s.skillImports.CreateRemote(ctx, req)
	if err != nil {
		skillImportError(w, err)
		return
	}
	status := 201
	if reused {
		status = 200
	}
	writeJSON(w, status, skillimport.NewResult(record, analysis, reused))
}

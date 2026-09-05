// Package server exposes the decision API (dev-spec §3.8.1) over loopback HTTP
// with a bearer token. It holds no policy logic of its own: every decision is
// delegated to receipt.Engine, admissions to admission.Admit and grants to the
// grant state machine. Handlers never log request bodies.
package server

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Deps wires the server.
type Deps struct {
	Store     *state.Store
	Engine    *receipt.Engine
	Chain     *receipt.Chain
	Pack      *rulepack.Pack
	Key       *signing.Key
	Token     string
	Version   string
	Mode      string
	UI        http.Handler // optional embedded console
	Home      string       // override os.UserHomeDir (tests + adapter HTTP)
	Binary    string       // agentshield path written into adapter configs
	Endpoint  string       // decision API URL written into adapter configs
	Openshell *openshell.Client
}

// Server is the HTTP handler set.
type Server struct {
	d      Deps
	mux    *http.ServeMux
	osMu   sync.Mutex
	osAt   time.Time
	osRow  PlatformInfo
	osOK   bool
	osCaps *openshell.Capabilities
	osDiag openshell.Diagnosis
}

// New builds the handler.
func New(d Deps) (*Server, error) {
	if d.Store == nil || d.Engine == nil || d.Chain == nil || d.Pack == nil || d.Key == nil || len(d.Token) < 32 {
		return nil, errors.New("server: incomplete dependencies")
	}
	s := &Server{d: d, mux: http.NewServeMux()}
	s.mux.HandleFunc("/v1/status", s.auth(s.status))
	s.mux.HandleFunc("/v1/decide", s.auth(s.decide))
	s.mux.HandleFunc("/v1/observe", s.auth(s.observe))
	s.mux.HandleFunc("/v1/hold/", s.auth(s.hold))
	s.mux.HandleFunc("/v1/receipts", s.auth(s.receipts))
	s.mux.HandleFunc("/v1/admit", s.auth(s.admit))
	s.mux.HandleFunc("/v1/admissions", s.auth(s.admissions))
	s.mux.HandleFunc("/v1/admissions/", s.auth(s.admissionOne))
	s.mux.HandleFunc("/v1/inventory", s.auth(s.inventory))
	s.mux.HandleFunc("/v1/grants", s.auth(s.grants))
	s.mux.HandleFunc("/v1/grants/", s.auth(s.grantAction))
	s.mux.HandleFunc("/v1/config", s.auth(s.config))
	s.mux.HandleFunc("/v1/adapter/status", s.auth(s.adapterStatus))
	s.mux.HandleFunc("/v1/adapter/install", s.auth(s.adapterInstall))
	s.mux.HandleFunc("/v1/adapter/uninstall", s.auth(s.adapterUninstall))
	s.mux.HandleFunc("/v1/openshell/probe", s.auth(s.openshellProbe))
	s.mux.HandleFunc("/v1/openshell/doctor", s.auth(s.openshellDoctor))
	s.mux.HandleFunc("/v1/openshell/apply", s.auth(s.openshellApply))
	s.mux.HandleFunc("/v1/openshell/drift-check", s.auth(s.openshellDriftCheck))
	s.mux.HandleFunc("/v1/assets", s.auth(s.assets))
	s.mux.HandleFunc("/v1/assets/", s.auth(s.assets))
	s.mux.HandleFunc("/v1/permissions", s.auth(s.permissions))
	s.mux.HandleFunc("/v1/findings", s.auth(s.findings))
	s.mux.HandleFunc("/v1/findings/", s.auth(s.findings))
	s.mux.HandleFunc("/v1/audit", s.auth(s.auditLog))
	s.mux.HandleFunc("/v1/export", s.auth(s.exportBundle))
	s.mux.HandleFunc("/ui-config.json", s.uiConfig)
	if d.UI != nil {
		s.mux.Handle("/", d.UI)
	} else {
		s.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			fmt.Fprintf(w, "agentshield %s — local mode · single user · %s\nAPI: /v1/status (bearer token required)\n", d.Version, d.Mode)
		})
	}
	return s, nil
}

// Handler returns the http.Handler (loopback check + mux).
func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if err != nil || !isLoopback(host) {
			http.Error(w, "loopback only", http.StatusForbidden)
			return
		}
		s.mux.ServeHTTP(w, r)
	})
}

func isLoopback(host string) bool {
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		if !strings.HasPrefix(h, "Bearer ") || subtle.ConstantTimeCompare([]byte(strings.TrimPrefix(h, "Bearer ")), []byte(s.d.Token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
			return
		}
		next(w, r)
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func readJSON(r *http.Request, v any, limit int64) error {
	dec := json.NewDecoder(http.MaxBytesReader(nil, r.Body, limit))
	dec.UseNumber()
	return dec.Decode(v)
}

func (s *Server) currentMode() string {
	if s.d.Engine != nil {
		if m := s.d.Engine.Mode(); m != "" {
			return m
		}
	}
	return s.d.Mode
}

func (s *Server) status(w http.ResponseWriter, _ *http.Request) {
	seq, head := s.d.Chain.Head()
	writeJSON(w, 200, map[string]any{
		"version": s.d.Version, "enforcement_mode": s.currentMode(), "local_mode": true, "single_user": true,
		"rulepack_version": s.d.Pack.Version, "rulepack_source": s.d.Pack.Source,
		"chain":              map[string]any{"id": "local", "head_seq": seq, "head_hash": head},
		"signing_public_key": s.d.Key.PublicBase64(),
		"platforms":          s.platforms(),
	})
}

// uiConfig is loopback-only (enforced by Handler) and unauthenticated: the
// same user can already read <state>/token. The browser keeps the value in
// memory; it must not be written to localStorage.
func (s *Server) uiConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{
		"token":            s.d.Token,
		"version":          s.d.Version,
		"enforcement_mode": s.currentMode(),
		"local_mode":       true,
		"single_user":      true,
	})
}

func (s *Server) config(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		cfg, err := s.d.Store.LoadConfig()
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "config unreadable"})
			return
		}
		cfg.EnforcementMode = s.currentMode()
		writeJSON(w, 200, cfg)
	case http.MethodPut, http.MethodPost:
		var body struct {
			EnforcementMode string `json:"enforcement_mode"`
		}
		if err := readJSON(r, &body, 16<<10); err != nil || body.EnforcementMode == "" {
			writeJSON(w, 400, map[string]any{"error": "enforcement_mode required"})
			return
		}
		if err := s.d.Engine.SetMode(body.EnforcementMode); err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
		cfg, err := s.d.Store.LoadConfig()
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "config unreadable"})
			return
		}
		cfg.EnforcementMode = body.EnforcementMode
		if err := s.d.Store.SaveConfig(cfg); err != nil {
			writeJSON(w, 500, map[string]any{"error": "config write failed"})
			return
		}
		s.d.Mode = body.EnforcementMode
		writeJSON(w, 200, cfg)
	default:
		writeJSON(w, 405, map[string]any{"error": "GET or PUT"})
	}
}

func (s *Server) decide(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var req receipt.Request
	if err := readJSON(r, &req, 4<<20); err != nil || req.Tool == "" || req.SessionID == "" || req.Platform == "" {
		writeJSON(w, 400, map[string]any{"error": "invalid request: platform, session_id and tool are required"})
		return
	}
	d, err := s.d.Engine.Decide(req)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "decision failed"})
		return
	}
	resp := map[string]any{"action": d.Action, "reason": d.Reason, "receipt_id": d.Receipt.ReceiptID}
	if d.Params != nil {
		resp["params"] = d.Params
	}
	if d.Hold != nil {
		resp["hold"] = d.Hold
	}
	writeJSON(w, 200, resp)
}

func (s *Server) observe(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		receipt.Request
		Result string `json:"result"`
	}
	if err := readJSON(r, &body, 4<<20); err != nil || body.Tool == "" || body.SessionID == "" {
		writeJSON(w, 400, map[string]any{"error": "invalid request"})
		return
	}
	if len(body.Result) > 64<<10 {
		body.Result = body.Result[:64<<10]
	}
	rec, err := s.d.Engine.Observe(body.Request, body.Result)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "observe failed"})
		return
	}
	writeJSON(w, 200, map[string]any{"receipt_id": rec.ReceiptID, "taint_labels": rec.TaintLabels})
}

func (s *Server) hold(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/hold/")
	var body struct {
		Approve bool   `json:"approve"`
		ActorID string `json:"actor_id"`
	}
	if err := readJSON(r, &body, 64<<10); err != nil || body.ActorID == "" {
		writeJSON(w, 400, map[string]any{"error": "actor_id required"})
		return
	}
	all, err := s.d.Chain.Read()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "chain unreadable"})
		return
	}
	for i := len(all) - 1; i >= 0; i-- {
		if all[i].ReceiptID == id && all[i].Action == receipt.ActionHold {
			rec, err := s.d.Engine.ResolveHold(all[i], body.Approve, body.ActorID)
			if err != nil {
				writeJSON(w, 400, map[string]any{"error": err.Error()})
				return
			}
			writeJSON(w, 200, map[string]any{"receipt_id": rec.ReceiptID, "action": rec.Action})
			return
		}
	}
	writeJSON(w, 404, map[string]any{"error": "held receipt not found"})
}

func (s *Server) receipts(w http.ResponseWriter, r *http.Request) {
	all, err := s.d.Chain.Read()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "chain unreadable"})
		return
	}
	since := -1
	if q := r.URL.Query().Get("since_seq"); q != "" {
		fmt.Sscanf(q, "%d", &since)
	}
	out := make([]receipt.Receipt, 0)
	for _, rc := range all {
		if rc.Seq > since {
			out = append(out, rc)
		}
		if len(out) >= 500 {
			break
		}
	}
	verified := receipt.Verify(all, s.d.Key.Public()) == nil
	writeJSON(w, 200, map[string]any{"receipts": out, "verified": verified})
}

func (s *Server) admit(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Path       string `json:"path"`
		TrustLevel string `json:"trust_level"`
	}
	if err := readJSON(r, &body, 64<<10); err != nil || body.Path == "" {
		writeJSON(w, 400, map[string]any{"error": "path required"})
		return
	}
	if body.TrustLevel == "" {
		body.TrustLevel = "unknown"
	}
	body.Path = expandHome(body.Path, s.d.Home)
	if st, err := os.Stat(body.Path); err != nil || !st.IsDir() {
		writeJSON(w, 400, map[string]any{"error": "path is not a readable directory"})
		return
	}
	res, err := admission.Admit(body.Path, admission.Options{
		Source:  admission.Source{Type: "local_dir", Locator: body.Path, TrustLevel: body.TrustLevel},
		Version: s.d.Version, Key: s.d.Key, Pack: s.d.Pack,
	})
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "admission failed"})
		return
	}
	if err := s.d.Store.PutAdmission(res); err != nil {
		writeJSON(w, 500, map[string]any{"error": "store failed"})
		return
	}
	_ = s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "admit", Target: res.Admission.AdmissionID, Note: res.Admission.Verdict})
	writeJSON(w, 200, map[string]any{"admission": res.Admission, "skill_card": res.SkillCard})
}

func (s *Server) runInventory(cwd string) (*inventory.Report, error) {
	if cwd != "" {
		cwd = expandHome(cwd, s.d.Home)
	}
	admissions, _ := s.d.Store.ListAdmissions()
	byHash := map[string]string{}
	for _, a := range admissions {
		byHash[a.ContentHash] = a.Verdict
	}
	return inventory.Run(inventory.Options{Home: s.d.Home, Cwd: cwd, Version: s.d.Version, Key: s.d.Key,
		ConnectorsDir: strings.TrimSpace(os.Getenv("SIQ_AS_CONNECTORS_DIR")),
		HasAdmission:  func(h string) (string, bool) { v, ok := byHash[h]; return v, ok }})
}

func (s *Server) exportBundle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	snap, err := s.snapshot("")
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "export failed"})
		return
	}
	audit, err := s.d.Store.TailAudit(200)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "audit unreadable"})
		return
	}
	bundle := export.Build(export.Input{
		Now:   time.Now().UTC().Format(time.RFC3339),
		Mode:  s.currentMode(),
		Key:   s.d.Key,
		Snap:  snap,
		Audit: audit,
	})
	raw, err := export.MarshalJSONBytes(bundle)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "export marshal failed"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Disposition", `attachment; filename="agentshield-export.json"`)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(append(raw, '\n'))
}

func (s *Server) inventory(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost && r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET or POST"})
		return
	}
	cwd := r.URL.Query().Get("cwd")
	if r.Method == http.MethodPost {
		var body struct {
			Cwd string `json:"cwd"`
		}
		_ = readJSON(r, &body, 64<<10)
		if body.Cwd != "" {
			cwd = body.Cwd
		}
	}
	rep, err := s.runInventory(cwd)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "inventory failed"})
		return
	}
	writeJSON(w, 200, rep)
}

func (s *Server) admissions(w http.ResponseWriter, r *http.Request) {
	list, err := s.d.Store.ListAdmissions()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "store unreadable"})
		return
	}
	writeJSON(w, 200, map[string]any{"admissions": list})
}

// grants: GET list; POST create from admission.
func (s *Server) grants(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		list, err := s.d.Store.ListGrants()
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "store unreadable"})
			return
		}
		writeJSON(w, 200, map[string]any{"grants": list})
	case http.MethodPost:
		var body struct {
			AdmissionID string `json:"admission_id"`
			Platform    string `json:"platform"`
			SubjectType string `json:"subject_type"`
			SubjectID   string `json:"subject_id"`
			Redact      bool   `json:"redact_secrets"`
		}
		if err := readJSON(r, &body, 64<<10); err != nil || body.AdmissionID == "" || body.Platform == "" || body.SubjectID == "" {
			writeJSON(w, 400, map[string]any{"error": "admission_id, platform, subject_id required"})
			return
		}
		if body.SubjectType == "" {
			body.SubjectType = "agent_instance"
		}
		adm, err := s.d.Store.GetAdmission(body.AdmissionID)
		if err != nil {
			writeJSON(w, 404, map[string]any{"error": "admission not found"})
			return
		}
		res, err := grant.Build(*adm, grant.Options{Subject: grant.Subject{Type: body.SubjectType, ID: body.SubjectID},
			Platform: body.Platform, EnforcementMode: s.currentMode(), Key: s.d.Key, RedactSecrets: body.Redact})
		if err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
		if existing, err := s.d.Store.GetGrant(res.Grant.GrantID); err == nil && grant.IsLiveStatus(existing.Status) {
			writeJSON(w, 200, map[string]any{"grant": existing, "reused": true})
			return
		}
		if err := s.d.Store.PutGrant(res.Grant); err != nil {
			writeJSON(w, 500, map[string]any{"error": "store failed"})
			return
		}
		_ = s.d.Store.PutDesiredPolicy(res.DesiredPolicy)
		_ = s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "grant_create", Target: res.Grant.GrantID})
		writeJSON(w, 200, map[string]any{"grant": res.Grant, "desired_policy": res.DesiredPolicy})
	default:
		writeJSON(w, 405, map[string]any{"error": "GET or POST"})
	}
}

// grantAction: POST /v1/grants/{id}/{approve|reject|deploy|revoke|resolve-overlap|effective|patch-desired}
func (s *Server) grantAction(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/grants/"), "/")
	if len(parts) != 2 {
		writeJSON(w, 404, map[string]any{"error": "not found"})
		return
	}
	g, err := s.d.Store.GetGrant(parts[0])
	if err != nil {
		writeJSON(w, 404, map[string]any{"error": "grant not found"})
		return
	}
	var body struct {
		ActorID    string                 `json:"actor_id"`
		Channel    string                 `json:"channel"`
		Index      int                    `json:"index"`
		Readback   *grant.Readback        `json:"readback"`
		Facts      map[string]string      `json:"fact_readbacks"`
		Tools      *[]string              `json:"tools"`
		Network    *[]grant.NetworkPatch  `json:"network"`
		Filesystem *grant.FilesystemPatch `json:"filesystem"`
		Process    *grant.ProcessPatch    `json:"process"`
		Models     *[]string              `json:"models"`
	}
	_ = readJSON(r, &body, 64<<10)
	actor := grant.Approval{ActorType: "human", ActorID: body.ActorID, ApprovedAt: time.Now().UTC().Format(time.RFC3339), Channel: body.Channel}
	if actor.Channel == "" {
		actor.Channel = "console"
	}
	var out grant.Grant
	var dp grant.DesiredPolicy
	switch parts[1] {
	case "approve":
		out, err = grant.Approve(*g, actor, s.d.Key)
	case "reject":
		out, err = grant.Reject(*g, s.d.Key)
	case "revoke":
		out, err = grant.Revoke(*g, s.d.Key)
	case "deploy":
		out, err = grant.MarkDeployed(*g, s.d.Key)
	case "resolve-overlap":
		out, err = grant.ResolveOverlap(*g, body.Index, actor, s.d.Key)
	case "effective":
		if body.Readback == nil {
			err = errors.New("readback required")
		} else {
			out, err = grant.MarkEffective(*g, *body.Readback, body.Facts, s.d.Key)
		}
	case "patch-desired":
		patch := grant.DesiredPatch{
			HasTools: body.Tools != nil, HasNetwork: body.Network != nil,
			HasFilesystem: body.Filesystem != nil, HasProcess: body.Process != nil, HasModels: body.Models != nil,
		}
		if body.Tools != nil {
			patch.Tools = *body.Tools
		}
		if body.Network != nil {
			patch.Network = *body.Network
		}
		patch.Filesystem = body.Filesystem
		patch.Process = body.Process
		if body.Models != nil {
			patch.Models = *body.Models
		}
		out, dp, err = grant.PatchDesired(*g, patch, s.d.Key)
	default:
		writeJSON(w, 404, map[string]any{"error": "unknown action"})
		return
	}
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	if err := s.d.Store.PutGrant(out); err != nil {
		writeJSON(w, 500, map[string]any{"error": "store failed"})
		return
	}
	if dp != nil {
		_ = s.d.Store.PutDesiredPolicy(dp)
	}
	switch parts[1] {
	case "approve", "revoke", "reject", "deploy":
		_ = s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "grant_" + parts[1], ActorID: body.ActorID, Target: out.GrantID})
	case "patch-desired":
		_ = s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "grant_patch", ActorID: body.ActorID, Target: out.GrantID})
		writeJSON(w, 200, map[string]any{"grant": out, "desired_policy": dp})
		return
	}
	writeJSON(w, 200, map[string]any{"grant": out})
}

func (s *Server) admissionOne(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	id := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/admissions/"), "/")
	if id == "" {
		s.admissions(w, r)
		return
	}
	adm, err := s.d.Store.GetAdmission(id)
	if err != nil {
		writeJSON(w, 404, map[string]any{"error": "admission not found"})
		return
	}
	card, _ := s.d.Store.SkillCard(id)
	writeJSON(w, 200, map[string]any{"admission": adm, "skill_card": card})
}

func expandHome(p, home string) string {
	if p == "~" || p == "~/" {
		if home != "" {
			return home
		}
		h, err := os.UserHomeDir()
		if err == nil {
			return h
		}
		return p
	}
	if strings.HasPrefix(p, "~/") || strings.HasPrefix(p, "~\\") {
		base := home
		if base == "" {
			base, _ = os.UserHomeDir()
		}
		if base != "" {
			return filepath.Join(base, p[2:])
		}
	}
	return p
}

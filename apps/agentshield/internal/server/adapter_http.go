package server

import (
	"crypto/sha256"
	"errors"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

type pendingAdapterPlan struct {
	plan     *adapterinstall.Plan
	owner    [32]byte
	mode     string
	endpoint string
	expires  time.Time
}

func (s *Server) adapterStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"detected": adapterinstall.Detect(s.d.Home), "platforms": s.platforms()})
}

func (s *Server) adapterPreview(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		RuntimeIdentityID string `json:"runtime_identity_id"`
		ActorID           string `json:"actor_id"`
		InstanceID        string `json:"instance_id"`
		NativeEnable      bool   `json:"native_enable"`
		Platform          string `json:"platform"`
		Action            string `json:"action"`
	}
	if err := readJSON(r, &body, 16<<10); err != nil {
		writeJSON(w, 400, map[string]any{"error": "invalid preview request"})
		return
	}
	s.adapterPlanMu.Lock()
	defer s.adapterPlanMu.Unlock()
	if s.adapterPlans == nil {
		s.adapterPlans = map[string]pendingAdapterPlan{}
	}
	owner := sha256.Sum256([]byte(r.Header.Get("Authorization")))
	for id, item := range s.adapterPlans {
		old := item.plan.View()
		if !time.Now().Before(item.expires) || item.owner == owner && old.Platform == body.Platform && old.InstanceID == body.InstanceID && old.Action == body.Action {
			delete(s.adapterPlans, id)
		}
	}
	if len(s.adapterPlans) >= 8 {
		writeJSON(w, 429, map[string]any{"error": "预览数量已达上限，请稍后重试。"})
		return
	}
	opts, err := s.resolveAdapterOptions(body.Platform, body.InstanceID)
	if err != nil {
		adapterError(w, err)
		return
	}
	if body.NativeEnable && body.InstanceID == "" {
		writeJSON(w, 400, map[string]any{"error": "原生启用需要明确选择实例"})
		return
	}
	opts.RuntimeIdentityID = body.RuntimeIdentityID
	opts.NativeEnable = body.NativeEnable
	opts.NativeCLI = s.d.HermesCLI
	plan, err := adapterinstall.Prepare(opts, body.Action)
	if err != nil {
		adapterError(w, err)
		return
	}
	view := plan.View()
	if view.RuntimeIdentityID != "" && view.Action == "install" {
		if err := s.validateManagedSelection(view.RuntimeIdentityID, view.InstanceID); err != nil {
			adapterError(w, err)
			return
		}
	}
	expires, _ := time.Parse(time.RFC3339, view.ExpiresAt)
	s.adapterPlans[view.PlanID] = pendingAdapterPlan{plan: plan, owner: sha256.Sum256([]byte(r.Header.Get("Authorization"))), mode: opts.Mode, endpoint: opts.Endpoint, expires: expires}
	writeJSON(w, 200, view)
}

func adapterError(w http.ResponseWriter, err error) {
	code, message := 400, "无法准备或完成配置操作，请检查平台配置、文件权限和本地恢复记录。"
	if errors.Is(err, adapterinstall.ErrPlanChanged) {
		code, message = 409, "平台配置已变化，请重新预览后确认。"
	}
	if errors.Is(err, adapterinstall.ErrRecoveryRequired) {
		code, message = 409, "上次操作尚未恢复；已保留外部修改，请先检查配置并恢复中断操作。"
	}
	if errors.Is(err, adapterinstall.ErrNativeCLI) {
		message = "Hermes 原生命令不可用、超时或版本不兼容；平台配置未继续应用，请检查 Hermes CLI。"
	}
	var recovery *adapterinstall.RecoveryPlan
	if errors.As(err, &recovery) {
		code, message = 409, "配置与安装记录有冲突，已保留现有文件，请检查恢复副本。"
	}
	// Never return filesystem / decoder errors that may contain private paths
	// or configuration contents. Durable recovery records stay on this machine.
	writeJSON(w, code, map[string]any{"error": message, "recovery_required": errors.Is(err, adapterinstall.ErrRecoveryRequired)})
}

func (s *Server) adapterInstall(w http.ResponseWriter, r *http.Request) {
	s.adapterMutate(w, r, "install")
}
func (s *Server) adapterUninstall(w http.ResponseWriter, r *http.Request) {
	s.adapterMutate(w, r, "uninstall")
}
func (s *Server) adapterMutate(w http.ResponseWriter, r *http.Request, action string) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		RuntimeIdentityID string `json:"runtime_identity_id"`
		ActorID           string `json:"actor_id"`
		InstanceID        string `json:"instance_id"`
		Platform          string `json:"platform"`
		PlanID            string `json:"plan_id"`
		PlanDigest        string `json:"plan_digest"`
	}
	if err := readJSON(r, &body, 16<<10); err != nil || body.PlanID == "" || body.PlanDigest == "" {
		writeJSON(w, 400, map[string]any{"error": "请先预览配置变更，再确认应用。"})
		return
	}
	s.adapterPlanMu.Lock()
	defer s.adapterPlanMu.Unlock()
	pending, ok := s.adapterPlans[body.PlanID]
	if !ok || pending.owner != sha256.Sum256([]byte(r.Header.Get("Authorization"))) {
		writeJSON(w, 409, map[string]any{"error": "当前会话没有此预览，请重新预览。"})
		return
	}
	view := pending.plan.View()
	opts, err := s.resolveAdapterOptions(body.Platform, body.InstanceID)
	if err != nil {
		adapterError(w, err)
		return
	}
	if view.InstanceID != body.InstanceID || view.Platform != body.Platform || view.Action != action || view.PlanDigest != body.PlanDigest || !time.Now().Before(pending.expires) || pending.mode != opts.Mode || pending.endpoint != opts.Endpoint {
		adapterError(w, adapterinstall.ErrPlanChanged)
		return
	}
	if view.RuntimeIdentityID != body.RuntimeIdentityID {
		adapterError(w, adapterinstall.ErrPlanChanged)
		return
	}
	revoked := false
	if view.RuntimeIdentityID != "" {
		if action == "install" {
			if err := s.validateManagedSelection(view.RuntimeIdentityID, view.InstanceID); err != nil {
				adapterError(w, err)
				return
			}
		} else {
			actor := strings.TrimSpace(body.ActorID)
			if actor == "" {
				actor = "local-console"
			}
			if _, err := s.runtimeIdentities.Revoke(view.RuntimeIdentityID, actor); err != nil {
				runtimeIdentityError(w, err)
				return
			}
			revoked = true
		}
	}
	res, err := adapterinstall.Apply(pending.plan)
	if err != nil {
		delete(s.adapterPlans, body.PlanID)
		if revoked {
			writeJSON(w, 409, map[string]any{"error": "实例授权已停用，但接入配置尚未完整移除。请检查文件变化；如有中断记录，可恢复后重新预览。恢复不会重新启用旧授权。", "runtime_identity_revoked": true, "recovery_required": errors.Is(err, adapterinstall.ErrRecoveryRequired)})
			return
		}
		adapterError(w, err)
		return
	}
	// Keep the successful plan until expiry so network retries are idempotent.
	writeJSON(w, 200, res)
}

func (s *Server) adapterRecover(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Platform   string `json:"platform"`
		InstanceID string `json:"instance_id"`
	}
	if err := readJSON(r, &body, 16<<10); err != nil {
		writeJSON(w, 400, map[string]any{"error": "invalid recovery request"})
		return
	}
	switch body.Platform {
	case adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy:
	default:
		writeJSON(w, 400, map[string]any{"error": "unsupported recovery platform"})
		return
	}
	s.adapterPlanMu.Lock()
	defer s.adapterPlanMu.Unlock()
	opts, err := s.resolveAdapterOptions(body.Platform, body.InstanceID)
	if err != nil {
		adapterError(w, err)
		return
	}
	res, err := adapterinstall.RecoverInstance(opts)
	if err != nil {
		adapterError(w, err)
		return
	}
	writeJSON(w, 200, res)
}

func (s *Server) validateManagedSelection(id, instance string) error {
	summary, err := s.runtimeIdentities.Summary(id)
	if err != nil || summary.Status != "issued" || summary.InstanceID != instance || summary.Platform != adapterinstall.Hermes {
		return adapterinstall.ErrPlanChanged
	}
	return nil
}

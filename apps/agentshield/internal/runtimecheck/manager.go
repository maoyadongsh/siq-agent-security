package runtimecheck

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/state"
)

// New recovers interrupted probes. The caller holds state.AcquireWriter for
// this state directory for the manager lifetime, as the serve command does.
func New(o Options) (*Manager, error) {
	if o.Store == nil || o.Intents == nil || o.Key == nil || o.Pack == nil || o.Chain == nil || o.Snapshot == nil || o.Endpoint == "" {
		return nil, errors.New("runtime_check_dependencies_missing")
	}
	m := &Manager{o: o, plans: map[string]pendingPlan{}}
	m.launchHost = m.launch
	for _, dir := range []string{m.dir(), filepath.Dir(m.materials("unused"))} {
		if err := os.Mkdir(dir, 0700); err != nil && !errors.Is(err, os.ErrExist) {
			return nil, errors.New("runtime_check_storage_unavailable")
		}
		info, err := os.Lstat(dir)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("runtime_check_storage_unavailable")
		}
	}
	records, err := m.records()
	if err != nil {
		return nil, err
	}
	for _, r := range records {
		if terminal(r.Result.Status) && r.Result.Cleanup == "complete" {
			continue
		}
		m.cleanup(&r)
		r.Result.Status, r.Result.Reason = "failed", "runtime_check_interrupted"
		now := time.Now().UTC().Format(time.RFC3339Nano)
		r.Result.FinishedAt = &now
		if err := m.persist(&r); err != nil {
			return nil, err
		}
	}
	return m, nil
}
func (m *Manager) snapshot(id string) (adapterinstall.RuntimeTarget, error) {
	target, err := m.o.Snapshot(id)
	if err != nil {
		return target, err
	}
	target.Digest, err = digest(map[string]any{"target": target.Digest, "service_public_key": m.o.Key.PublicBase64(), "method": "hermes-native-read-deny-read/v1"})
	return target, err
}
func (m *Manager) Preview(instanceID, owner string) (Plan, error) {
	if !instancePattern.MatchString(instanceID) || owner == "" {
		return Plan{}, errors.New("runtime_check_invalid_request")
	}
	target, err := m.snapshot(instanceID)
	if err != nil {
		return Plan{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now().UTC()
	for id, p := range m.plans {
		deadline, _ := time.Parse(time.RFC3339Nano, p.view.ExpiresAt)
		if !now.Before(deadline) || p.view.InstanceID == instanceID && p.owner == sha256.Sum256([]byte(owner)) {
			delete(m.plans, id)
		}
	}
	if len(m.plans) >= 8 {
		return Plan{}, errors.New("runtime_check_preview_capacity")
	}
	id, err := randomHex(16)
	if err != nil {
		return Plan{}, err
	}
	p := Plan{SchemaVersion: "local-runtime-check-plan/v1", ID: "rc-" + id, InstanceID: instanceID, Snapshot: target.Digest, ExpiresAt: now.Add(5 * time.Minute).Format(time.RFC3339Nano), DurationSeconds: int(Duration / time.Second),
		Effects: []string{"以当前实例配置启动一个新的 Hermes 测试会话。", "仅允许读取本次生成的两份临时文件；测试一次越权写入拒绝。", "最长 120 秒；结束后撤销临时 Grant/Intent 并清理测试材料。"}, Limitations: limitations()}
	p.Digest, err = digest(p)
	if err != nil {
		return Plan{}, err
	}
	m.plans[p.ID] = pendingPlan{view: p, owner: sha256.Sum256([]byte(owner))}
	return p, nil
}
func (m *Manager) Start(id, planDigest, owner, actor string) (Result, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.plans[id]
	if !ok {
		return Result{}, ErrNotFound
	}
	if p.owner != sha256.Sum256([]byte(owner)) || p.view.Digest != planDigest {
		return Result{}, ErrCredential
	}
	expires, _ := time.Parse(time.RFC3339Nano, p.view.ExpiresAt)
	if !time.Now().Before(expires) {
		delete(m.plans, id)
		return Result{}, ErrConflict
	}
	if m.active != nil {
		return Result{}, ErrConflict
	}
	if strings.TrimSpace(actor) == "" || utf8.RuneCountInString(actor) > 128 {
		return Result{}, errors.New("runtime_check_invalid_actor")
	}
	target, err := m.snapshot(p.view.InstanceID)
	if err != nil || target.Digest != p.view.Snapshot {
		return Result{}, errors.New("runtime_check_snapshot_changed")
	}
	history, err := m.records()
	if err != nil {
		return Result{}, err
	}
	if len(history) >= 128 {
		return Result{}, errors.New("runtime_check_history_capacity")
	}
	for _, r := range history {
		if r.Result.Cleanup != "complete" {
			return Result{}, errors.New("runtime_check_cleanup_required")
		}
	}
	nonce, err := randomHex(32)
	if err != nil {
		return Result{}, err
	}
	now := time.Now().UTC()
	ctx, cancel := context.WithDeadline(context.Background(), now.Add(Duration))
	r := &run{id: id, record: record{Revision: -1, Actor: actor, IntentID: "rci-" + strings.TrimPrefix(id, "rc-"), Result: Result{SchemaVersion: "local-runtime-check-result/v1", ID: id, InstanceID: p.view.InstanceID, Status: "preparing", Reason: "runtime_check_preparing", StartedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(Duration).Format(time.RFC3339Nano), Snapshot: target.Digest, Cleanup: "pending", ReceiptIDs: []string{}, Checks: map[string]bool{}, Limitations: limitations()}}, credential: sha256.Sum256([]byte(nonce)), cancel: cancel, done: make(chan struct{})}
	if err = m.persist(&r.record); err != nil {
		cancel()
		return Result{}, err
	}
	if err = m.o.Store.AppendAudit(state.AuditEvent{At: now.Format(time.RFC3339Nano), Event: "runtime_check_start", ActorID: actor, Target: id}); err != nil {
		cancel()
		r.record.Result.Status = "failed"
		r.record.Result.Reason = "runtime_check_audit_failed"
		finished := time.Now().UTC().Format(time.RFC3339Nano)
		r.record.Result.FinishedAt = &finished
		m.cleanup(&r.record)
		_ = m.persist(&r.record)
		return Result{}, errors.New("runtime_check_audit_failed")
	}
	delete(m.plans, id)
	m.active = r
	go m.execute(ctx, r, target, nonce)
	return copyResult(r.record.Result), nil
}
func (m *Manager) Attach(input Attach, credential string) (Attached, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r := m.active
	if r == nil || r.record.Result.ID != input.ID {
		return Attached{}, ErrCredential
	}
	got := sha256.Sum256([]byte(credential))
	if len(credential) != 64 || subtle.ConstantTimeCompare(got[:], r.credential[:]) != 1 || input.SchemaVersion != "local-runtime-check-attach/v1" || input.InstanceID != r.record.Result.InstanceID || input.AgentID != agentID(input.ID) || strings.TrimSpace(input.SessionID) == "" || utf8.RuneCountInString(input.SessionID) > 256 {
		return Attached{}, ErrCredential
	}
	expires, err := time.Parse(time.RFC3339Nano, r.record.Result.ExpiresAt)
	if err != nil || !time.Now().Before(expires) || r.record.Result.Reason == "runtime_check_cancelling" || (r.record.Result.Status != "waiting_host" && r.record.Result.Status != "running") {
		return Attached{}, ErrCredential
	}
	if r.session != "" && r.session != input.SessionID {
		return Attached{}, ErrConflict
	}
	if r.session == "" {
		_, revision, err := m.o.Store.GetGrantWithSeq(r.record.GrantID)
		if err != nil {
			return Attached{}, errors.New("runtime_check_authority_unavailable")
		}
		binding, err := m.o.Intents.BindWithGrant(intent.Binding{Platform: "hermes", SessionID: input.SessionID, AgentID: input.AgentID, IntentID: r.record.IntentID}, r.record.GrantID, revision)
		if err != nil {
			return Attached{}, errors.New("runtime_check_binding_failed")
		}
		r.session = input.SessionID
		r.record.BindingID = binding.BindingID
		r.record.Result.Status = "running"
		r.record.Result.Reason = "runtime_check_running"
		if err = m.persist(&r.record); err != nil {
			r.record.Result.Reason = "runtime_check_cancelling"
			r.cancel()
			return Attached{}, err
		}
	}
	return Attached{SchemaVersion: "local-runtime-check-attached/v1", ID: input.ID, SessionID: input.SessionID, Attached: true}, nil
}
func (m *Manager) Get(id string) (Result, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !idPattern.MatchString(id) {
		return Result{}, ErrNotFound
	}
	if m.active != nil && m.active.record.Result.ID == id {
		return copyResult(m.active.record.Result), nil
	}
	all, err := m.records()
	if err != nil {
		return Result{}, err
	}
	r, ok := all[id]
	if !ok {
		return Result{}, ErrNotFound
	}
	if r.Result.Status == "passed" {
		current, err := m.snapshot(r.Result.InstanceID)
		if err != nil || current.Digest != r.Result.Snapshot {
			r.Result.Status = "invalidated"
			r.Result.Reason = "runtime_check_snapshot_changed"
			if err = m.persist(&r); err != nil {
				return Result{}, err
			}
		}
	}
	return copyResult(r.Result), nil
}
func (m *Manager) Cancel(id string) (Result, error) {
	m.mu.Lock()
	if m.active == nil || m.active.record.Result.ID != id {
		m.mu.Unlock()
		return m.Get(id)
	}
	r := m.active
	if r.record.Result.Reason == "runtime_check_cancelling" {
		out := copyResult(r.record.Result)
		m.mu.Unlock()
		return out, nil
	}
	r.cancel()
	r.record.Result.Reason = "runtime_check_cancelling"
	err := m.persist(&r.record)
	out := copyResult(r.record.Result)
	m.mu.Unlock()
	return out, err
}
func agentID(id string) string { return "rca-" + strings.TrimPrefix(id, "rc-") }

func (m *Manager) Latest(instanceID string) ([]Result, error) {
	if !instancePattern.MatchString(instanceID) {
		return nil, errors.New("runtime_check_invalid_request")
	}
	m.mu.Lock()
	if m.active != nil && m.active.record.Result.InstanceID == instanceID {
		out := copyResult(m.active.record.Result)
		m.mu.Unlock()
		return []Result{out}, nil
	}
	all, err := m.records()
	if err != nil {
		m.mu.Unlock()
		return nil, err
	}
	var latest Result
	for _, r := range all {
		if r.Result.InstanceID == instanceID && (r.Result.StartedAt > latest.StartedAt || r.Result.StartedAt == latest.StartedAt && r.Result.ID > latest.ID) {
			latest = r.Result
		}
	}
	m.mu.Unlock()
	if latest.ID == "" {
		return []Result{}, nil
	}
	result, err := m.Get(latest.ID)
	if err != nil {
		return nil, err
	}
	return []Result{result}, nil
}

func (m *Manager) RetryCleanup(id string) (Result, error) {
	m.mu.Lock()
	if m.active != nil {
		m.mu.Unlock()
		return Result{}, ErrConflict
	}
	all, err := m.records()
	if err != nil {
		m.mu.Unlock()
		return Result{}, err
	}
	r, ok := all[id]
	if !ok {
		m.mu.Unlock()
		return Result{}, ErrNotFound
	}
	if r.Result.Cleanup == "complete" {
		m.mu.Unlock()
		return m.Get(id)
	}
	m.cleanup(&r)
	r.Result.Status, r.Result.Reason = "failed", "runtime_check_cleanup_failed"
	if r.Result.Cleanup == "complete" {
		r.Result.Reason = "runtime_check_cleanup_recovered"
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	r.Result.FinishedAt = &now
	err = m.persist(&r)
	m.mu.Unlock()
	return copyResult(r.Result), err
}

func (m *Manager) Close(ctx context.Context) error {
	m.mu.Lock()
	r := m.active
	if r != nil {
		r.cancel()
	}
	m.mu.Unlock()
	if r == nil {
		return nil
	}
	select {
	case <-r.done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// AuthorizeDecision scopes the short-lived launch capability to the check's
// durably attached native session. It grants no management authority.
func (m *Manager) AuthorizeDecision(credential, platform, agent, session string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	r := m.active
	if r == nil || len(credential) != 64 || platform != "hermes" || agent != agentID(r.id) || session == "" || session != r.session || r.record.Result.Status != "running" || r.record.Result.Reason == "runtime_check_cancelling" {
		return false
	}
	got := sha256.Sum256([]byte(credential))
	expires, err := time.Parse(time.RFC3339Nano, r.record.Result.ExpiresAt)
	if err != nil || !time.Now().Before(expires) || subtle.ConstantTimeCompare(got[:], r.credential[:]) != 1 {
		return false
	}
	c, b, err := m.o.Intents.ResolveBinding(platform, session, agent)
	return err == nil && c != nil && b != nil && b.BindingID == r.record.BindingID && c.IntentID == r.record.IntentID && b.GrantRef != nil && b.GrantRef.GrantID == r.record.GrantID
}

// HasDecisionCredential permits rejecting unrelated credentials before parsing
// their body. AuthorizeDecision must still validate the exact native tuple.
func (m *Manager) HasDecisionCredential(credential string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	r := m.active
	if r == nil || len(credential) != 64 || r.record.Result.Status != "running" || r.record.Result.Reason == "runtime_check_cancelling" {
		return false
	}
	expires, err := time.Parse(time.RFC3339Nano, r.record.Result.ExpiresAt)
	got := sha256.Sum256([]byte(credential))
	return err == nil && time.Now().Before(expires) && subtle.ConstantTimeCompare(got[:], r.credential[:]) == 1
}

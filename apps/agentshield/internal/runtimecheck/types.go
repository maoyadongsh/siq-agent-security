// Package runtimecheck orchestrates explicit, temporary native host probes. It
// delegates authority and decisions to the existing Grant/Intent/receipt stack.
package runtimecheck

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"regexp"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

const Duration = 120 * time.Second

var idPattern = regexp.MustCompile(`^rc-[a-f0-9]{32}$`)
var instancePattern = regexp.MustCompile(`^hi-[a-f0-9]{32}$`)
var ErrNotFound = errors.New("runtime_check_not_found")
var ErrConflict = errors.New("runtime_check_conflict")
var ErrCredential = errors.New("runtime_check_launch_credential_invalid")

type Plan struct {
	SchemaVersion   string   `json:"schema_version"`
	ID              string   `json:"check_id"`
	InstanceID      string   `json:"instance_id"`
	Digest          string   `json:"plan_digest"`
	Snapshot        string   `json:"snapshot_digest"`
	ExpiresAt       string   `json:"expires_at"`
	DurationSeconds int      `json:"duration_seconds"`
	Effects         []string `json:"effects"`
	Limitations     []string `json:"limitations"`
}
type Result struct {
	SchemaVersion string          `json:"schema_version"`
	ID            string          `json:"check_id"`
	InstanceID    string          `json:"instance_id"`
	Status        string          `json:"status"`
	Reason        string          `json:"reason_code"`
	StartedAt     string          `json:"started_at"`
	FinishedAt    *string         `json:"finished_at"`
	ExpiresAt     string          `json:"expires_at"`
	Snapshot      string          `json:"snapshot_digest"`
	Cleanup       string          `json:"cleanup"`
	ReceiptIDs    []string        `json:"receipt_ids"`
	Checks        map[string]bool `json:"checks"`
	Limitations   []string        `json:"limitations"`
}
type Attach struct {
	SchemaVersion string `json:"schema_version"`
	ID            string `json:"check_id"`
	InstanceID    string `json:"instance_id"`
	AgentID       string `json:"agent_id"`
	SessionID     string `json:"session_id"`
}
type Attached struct {
	SchemaVersion string `json:"schema_version"`
	ID            string `json:"check_id"`
	SessionID     string `json:"session_id"`
	Attached      bool   `json:"attached"`
}
type Options struct {
	Store    *state.Store
	Intents  *intent.Store
	Key      *signing.Key
	Pack     *rulepack.Pack
	Chain    *receipt.Chain
	Endpoint string
	Snapshot func(string) (adapterinstall.RuntimeTarget, error)
}
type pendingPlan struct {
	view  Plan
	owner [32]byte
}
type record struct {
	Result       Result `json:"result"`
	Revision     int    `json:"revision"`
	Actor        string `json:"actor_id"`
	GrantID      string `json:"grant_id"`
	IntentID     string `json:"intent_id"`
	IntentDigest string `json:"intent_digest"`
	BindingID    string `json:"binding_id"`
	Signature    string `json:"signature"`
}
type run struct {
	id         string // immutable while record revisions are published
	record     record
	credential [32]byte
	session    string
	cancel     context.CancelFunc
	done       chan struct{}
}
type Manager struct {
	mu         sync.Mutex
	o          Options
	plans      map[string]pendingPlan
	active     *run
	launchHost func(context.Context, *run, adapterinstall.RuntimeTarget, string, probes) error
}

func randomHex(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", errors.New("runtime_check_random_failed")
	}
	return hex.EncodeToString(b), nil
}
func digest(v any) (string, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	decoded, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	raw, err = canon.Marshal(decoded)
	if err != nil {
		return "", err
	}
	h := sha256.Sum256(raw)
	return hex.EncodeToString(h[:]), nil
}
func limitations() []string {
	return []string{"检查新的合成测试会话，不覆盖已运行会话或可信 Skill 归属。", "宿主可能写入自身历史、缓存并运行已配置插件；不声明网络或操作系统隔离。", "摘要仅覆盖被核对的配置、适配器、CLI 入口和 SIQ 服务，不代表完整 Python 依赖身份。"}
}
func copyResult(r Result) Result {
	r.ReceiptIDs = append([]string{}, r.ReceiptIDs...)
	r.Limitations = append([]string{}, r.Limitations...)
	checks := map[string]bool{}
	for k, v := range r.Checks {
		checks[k] = v
	}
	r.Checks = checks
	return r
}
func terminal(status string) bool {
	return status == "passed" || status == "failed" || status == "cancelled" || status == "invalidated"
}

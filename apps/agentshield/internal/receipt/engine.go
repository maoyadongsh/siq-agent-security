// Package receipt implements runtime-receipt (dev-spec §3.8): the per-tool-call
// decision engine (default-deny against a grant, taint tracking, lethal
// trifecta), the append-only hash-linked receipt chain and its verifier.
// Output conforms to packages/contracts/receipt.schema.json. Platform
// adapters and the model never hold the signing key; the HTTP surface that
// exposes Decide/Observe lives in the serve command (W2).
package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/threat"
)

const (
	ActionAllow  = "allow"
	ActionDeny   = "deny"
	ActionHold   = "hold"
	ActionRedact = "redact"

	taintSecret    = "secret"
	taintPII       = "pii"
	taintUntrusted = "untrusted_content"
	taintPrivate   = "private_mount"

	excerptMax = 512

	// Session capacity defaults (DEV16-A / M-G6a). Tainted sessions are never
	// LRU-evicted to free slots — capacity pressure refuses new session IDs.
	defaultMaxSessions = 4096
	minMaxSessions     = 1
	maxMaxSessions     = 1_000_000

	// Untainted idle TTL (DEV16-E). Options 0 → default; negative → disabled.
	defaultSessionIdleTTL = 30 * time.Minute
	minSessionIdleTTL     = time.Second
	maxSessionIdleTTL     = 24 * time.Hour
)

// ErrSessionCapacity is returned when a new session_id would exceed MaxSessions.
var ErrSessionCapacity = errors.New("receipt: session capacity exhausted")

// Request is one tool call awaiting a decision.
type Request struct {
	Platform   string         `json:"platform"`
	SessionID  string         `json:"session_id"`
	AgentID    string         `json:"agent_id"`
	Tool       string         `json:"tool"`
	ToolCallID string         `json:"tool_call_id"`
	Params     map[string]any `json:"params"`
	Context    map[string]any `json:"context"`
}

// Trifecta flags for the session.
type Trifecta struct {
	PrivateData    bool `json:"private_data"`
	UntrustedInput bool `json:"untrusted_input"`
	Egress         bool `json:"egress"`
}

// Hold describes a pending human sign-off.
type Hold struct {
	Channel             string  `json:"channel"`
	TimeoutMS           int     `json:"timeout_ms"`
	ResolvedByReceiptID *string `json:"resolved_by_receipt_id"`
}

// EngineInfo identifies the deciding engine.
type EngineInfo struct {
	Version         string `json:"version"`
	RulepackVersion int    `json:"rulepack_version"`
}

// Receipt is the signed, chained record (receipt.schema.json).
type Receipt struct {
	ReceiptID         string     `json:"receipt_id"`
	ChainID           string     `json:"chain_id"`
	Seq               int        `json:"seq"`
	PrevHash          string     `json:"prev_hash"`
	Hash              string     `json:"hash"`
	Sig               string     `json:"sig"`
	IssuedAt          string     `json:"issued_at"`
	Platform          string     `json:"platform"`
	SessionID         string     `json:"session_id"`
	AgentID           *string    `json:"agent_id"`
	Tool              string     `json:"tool"`
	ToolCallID        *string    `json:"tool_call_id"`
	ParamsDigest      string     `json:"params_digest"`
	ParamsExcerpt     *string    `json:"params_excerpt"`
	Action            string     `json:"action"`
	AdvisoryAction    *string    `json:"advisory_action"`
	Reason            string     `json:"reason"`
	MatchedGrantID    *string    `json:"matched_grant_id"`
	MatchedFactIDs    []string   `json:"matched_fact_ids"`
	MatchedRuleIDs    []string   `json:"matched_rule_ids"`
	TaintLabels       []string   `json:"taint_labels"`
	Trifecta          *Trifecta  `json:"trifecta"`
	EnforcementMode   string     `json:"enforcement_mode"`
	PolicyRevision    *string    `json:"policy_revision"`
	SandboxID         *string    `json:"sandbox_id"`
	ModelKey          *string    `json:"model_key"`
	Engine            EngineInfo `json:"engine"`
	DecisionLatencyMS *int       `json:"decision_latency_ms"`
	Hold              *Hold      `json:"hold"`
}

// Decision is what the adapter acts on.
type Decision struct {
	Action  string         `json:"action"`
	Reason  string         `json:"reason"`
	Receipt Receipt        `json:"receipt"`
	Params  map[string]any `json:"params,omitempty"` // only for redact
	Hold    *Hold          `json:"hold,omitempty"`
}

// GrantLookup returns the current deployed/effective grant for an agent, or nil.
type GrantLookup func(platform, agentID string) *grant.Grant

// Options configure the engine.
type Options struct {
	Pack            *rulepack.Pack
	Chain           *Chain
	Grants          GrantLookup
	EnforcementMode string // audit_only | warn | block
	Version         string
	HoldChannel     string // console | openclaw_approval | hermes_cli | codebuddy_prompt | other
	HoldTimeoutMS   int
	// MaxSessions caps distinct in-memory session IDs (0 → defaultMaxSessions).
	// Out of range values are rejected at New.
	MaxSessions int
	// SessionIdleTTL expires only sessions with no taint/trifecta memory after
	// idle (DEV16-E). 0 → default 30m; negative → disabled; positive must be in
	// [1s, 24h]. Tainted / trifecta sessions never idle-expire (would fake clean).
	SessionIdleTTL time.Duration
	Now            func() time.Time
	// UntrustedSkillLoaded reports whether the session has a non-admit skill
	// loaded (sets trifecta.untrusted_input).
	UntrustedSkillLoaded func(sessionID string) bool
}

type session struct {
	taints   map[string]bool
	trifecta Trifecta
	lastUsed time.Time
}

// SessionStats is a point-in-time view of session capacity (DEV16-A/E).
type SessionStats struct {
	Active         int    `json:"active"`
	Max            int    `json:"max"`
	Refusals       uint64 `json:"capacity_refusals"`
	IdleExpired    uint64 `json:"idle_expired"`
	IdleTTLSeconds int    `json:"idle_ttl_seconds"` // 0 means idle expiry disabled
}

// Engine decides tool calls.
type Engine struct {
	opts               Options
	analyzer           *threat.Analyzer
	mu                 sync.Mutex
	sessions           map[string]*session
	maxSessions        int
	sessionIdleTTL     time.Duration // <=0 disabled
	sessionCapRefusals uint64
	sessionIdleExpired uint64
}

// New builds an engine.
func New(opts Options) (*Engine, error) {
	if opts.Pack == nil || opts.Chain == nil {
		return nil, errors.New("receipt: rulepack and chain are required")
	}
	if opts.EnforcementMode == "" {
		opts.EnforcementMode = "block"
	}
	if opts.HoldChannel == "" {
		opts.HoldChannel = "console"
	}
	if opts.HoldTimeoutMS == 0 {
		opts.HoldTimeoutMS = 60000
	}
	if opts.Now == nil {
		opts.Now = func() time.Time { return time.Now().UTC() }
	}
	maxSess := opts.MaxSessions
	if maxSess == 0 {
		maxSess = defaultMaxSessions
	}
	if maxSess < minMaxSessions || maxSess > maxMaxSessions {
		return nil, fmt.Errorf("receipt: MaxSessions %d out of range [%d,%d]", maxSess, minMaxSessions, maxMaxSessions)
	}
	idleTTL := opts.SessionIdleTTL
	switch {
	case idleTTL < 0:
		idleTTL = 0 // disabled
	case idleTTL == 0:
		idleTTL = defaultSessionIdleTTL
	default:
		if idleTTL < minSessionIdleTTL || idleTTL > maxSessionIdleTTL {
			return nil, fmt.Errorf("receipt: SessionIdleTTL %s out of range [%s,%s]", idleTTL, minSessionIdleTTL, maxSessionIdleTTL)
		}
	}
	return &Engine{
		opts:           opts,
		analyzer:       threat.New(opts.Pack),
		sessions:       map[string]*session{},
		maxSessions:    maxSess,
		sessionIdleTTL: idleTTL,
	}, nil
}

// SessionStats returns live session capacity counters (no secrets / IDs).
func (e *Engine) SessionStats() SessionStats {
	e.mu.Lock()
	defer e.mu.Unlock()
	ttlSec := 0
	if e.sessionIdleTTL > 0 {
		ttlSec = int(e.sessionIdleTTL / time.Second)
	}
	return SessionStats{
		Active: len(e.sessions), Max: e.maxSessions, Refusals: e.sessionCapRefusals,
		IdleExpired: e.sessionIdleExpired, IdleTTLSeconds: ttlSec,
	}
}

// SetMode updates enforcement_mode for subsequent Decide calls (settings UI).
func (e *Engine) SetMode(mode string) error {
	switch mode {
	case "audit_only", "warn", "block":
	default:
		return fmt.Errorf("receipt: invalid enforcement_mode %q", mode)
	}
	e.mu.Lock()
	e.opts.EnforcementMode = mode
	e.mu.Unlock()
	return nil
}

// Mode returns the live enforcement_mode.
func (e *Engine) Mode() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.opts.EnforcementMode
}

var (
	egressTools = map[string]bool{"web_fetch": true, "web_extract": true, "web_search": true, "http": true, "http_request": true,
		"fetch": true, "send_message": true, "browser_navigate": true, "WebFetch": true, "WebSearch": true, "browser": true, "message": true}
	shellTools = map[string]bool{"exec": true, "terminal": true, "Bash": true, "shell": true, "bash": true, "process": true}
	fileTools  = map[string]bool{"read_file": true, "write_file": true, "Read": true, "Write": true, "Edit": true, "patch": true, "search_files": true}

	netCmdRe   = regexp.MustCompile(`(?i)\b(curl|wget|nc|ncat|netcat|ssh|scp|rsync|ftp|telnet|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b`)
	urlRe      = regexp.MustCompile(`https?://([A-Za-z0-9.-]+)(?::(\d+))?`)
	hostArgRe  = regexp.MustCompile(`\b(?:nc|ncat|netcat|ssh|scp|telnet)\s+(?:-\w+\s+)*([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})`)
	pathRe     = regexp.MustCompile(`(?:^|[\s"'=(,])((?:~|\$HOME|/)[A-Za-z0-9_./~-]+)`)
	credPathRe = regexp.MustCompile(`(?i)(?:^|/)(\.env(?:\.[a-z]+)?|\.ssh|\.aws|\.gnupg|\.netrc|\.docker/config\.json|\.kube/config|id_rsa|id_ed25519|credentials|auth\.json|\.npmrc|\.pypirc)(?:/|$)`)
	piiRe      = regexp.MustCompile(`\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,16}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`)
)

// Decide evaluates a tool call (spec §3.8.2) and appends a receipt.
func (e *Engine) Decide(req Request) (*Decision, error) {
	start := e.opts.Now()
	e.mu.Lock()
	defer e.mu.Unlock()
	s, err := e.sessionOrReject(req.SessionID, start)
	if err != nil {
		return nil, err
	}

	paramsJSON, _ := json.Marshal(req.Params)
	// scan the raw string values, not the JSON encoding (which escapes quotes
	// and > < & and would hide `token="..."` or `> /etc/...` from the rules)
	paramsText := flattenStrings(req.Params)
	digest := sha256.Sum256(paramsJSON)

	rec := Receipt{
		ReceiptID: "rcp-" + hex.EncodeToString(digest[:])[:12] + "-" + start.Format("150405.000000"),
		IssuedAt:  start.Format(time.RFC3339),
		Platform:  req.Platform, SessionID: req.SessionID, Tool: req.Tool,
		ParamsDigest:    hex.EncodeToString(digest[:]),
		MatchedFactIDs:  []string{},
		MatchedRuleIDs:  []string{},
		TaintLabels:     []string{},
		EnforcementMode: e.opts.EnforcementMode,
		Engine:          EngineInfo{Version: e.opts.Version, RulepackVersion: e.opts.Pack.Version},
	}
	if req.AgentID != "" {
		a := req.AgentID
		rec.AgentID = &a
	}
	if req.ToolCallID != "" {
		t := req.ToolCallID
		rec.ToolCallID = &t
	}
	excerpt := truncate(e.analyzer.Redact(paramsText), excerptMax)
	rec.ParamsExcerpt = &excerpt

	// step 4a: taint scan of params (updates session before the decision so
	// a secret passed to an egress tool in the same call is caught)
	newTaints, ruleIDs := e.scanTaints(paramsText)
	for _, t := range newTaints {
		s.taints[t] = true
	}
	rec.MatchedRuleIDs = ruleIDs
	if isEgress(req.Tool, paramsText) {
		s.trifecta.Egress = true
	}
	if e.opts.UntrustedSkillLoaded != nil && e.opts.UntrustedSkillLoaded(req.SessionID) {
		s.trifecta.UntrustedInput = true
	}
	hosts := extractHosts(req.Tool, paramsText)
	paths := extractPaths(req.Tool, paramsText)
	for _, p := range paths {
		if credPathRe.MatchString(p) {
			s.taints[taintPrivate] = true
			s.trifecta.PrivateData = true
		}
	}
	rec.TaintLabels = sortedKeys(s.taints)
	tf := s.trifecta
	rec.Trifecta = &tf

	action, reason := e.evaluate(req, s, hosts, paths, &rec)

	// step 6: redact — only when the grant permits and a secret literal is in params
	var redacted map[string]any
	if action == ActionDeny && strings.HasPrefix(reason, "tainted egress") && e.redactAllowed(req) && containsSecretLiteral(e.analyzer, paramsText) {
		redacted = redactParams(e.analyzer, req.Params)
		action, reason = ActionRedact, "secret literal removed from params before egress (grant permits redaction)"
	}

	// step 7: enforcement mode
	var hold *Hold
	switch e.opts.EnforcementMode {
	case "audit_only", "warn":
		if action != ActionAllow {
			adv := action
			rec.AdvisoryAction = &adv
			if e.opts.EnforcementMode == "warn" {
				reason = "WARN: " + reason
			}
			action = ActionAllow
			redacted = nil
		}
	default:
		if action == ActionHold {
			hold = &Hold{Channel: e.opts.HoldChannel, TimeoutMS: e.opts.HoldTimeoutMS}
			rec.Hold = hold
		}
	}
	rec.Action = action
	rec.Reason = reason
	lat := int(e.opts.Now().Sub(start).Milliseconds())
	rec.DecisionLatencyMS = &lat

	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	return &Decision{Action: action, Reason: reason, Receipt: rec, Params: redacted, Hold: hold}, nil
}

// evaluate performs steps 2–5 and returns the raw (pre-mode) action.
func (e *Engine) evaluate(req Request, s *session, hosts, paths []string, rec *Receipt) (string, string) {
	var g *grant.Grant
	if e.opts.Grants != nil {
		g = e.opts.Grants(req.Platform, req.AgentID)
	}
	if g == nil || (g.Status != "deployed" && g.Status != "effective") {
		return ActionDeny, "no deployed grant for agent (default deny)"
	}
	gid := g.GrantID
	rec.MatchedGrantID = &gid

	allow, requireApproval := toolSets(g)
	switch {
	case requireApproval[req.Tool]:
		// still run data checks below; hold is the floor, deny can override
	case allow[req.Tool]:
	default:
		return ActionDeny, "tool " + req.Tool + " not granted (default deny)"
	}

	// step 5 first: taint / trifecta rules override everything for egress
	if isEgress(req.Tool, "") || len(hosts) > 0 {
		if s.taints[taintSecret] || s.taints[taintPII] {
			return ActionDeny, "tainted egress: session carries " + strings.Join(sortedKeys(s.taints), ",") + " taint"
		}
		if s.trifecta.PrivateData && s.trifecta.UntrustedInput {
			return ActionDeny, "lethal trifecta: private data + untrusted input + egress in one session"
		}
	}

	// step 4b: hosts must be granted
	for _, h := range hosts {
		fid, ok := hostGranted(g, h)
		if !ok {
			return ActionDeny, "network egress to " + h + " not in grant " + g.GrantID + " (default deny)"
		}
		rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
	}
	if shellTools[req.Tool] && netCmdRe.MatchString(paramsTextOf(req)) && len(hosts) == 0 {
		return ActionDeny, "egress exec requires granted host"
	}
	// step 4c: paths must be granted or inside cwd
	cwd, _ := req.Context["cwd"].(string)
	for _, p := range paths {
		if fid, ok := pathGranted(g, p, cwd); ok {
			if fid != "" {
				rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
			}
			continue
		}
		if credPathRe.MatchString(p) {
			return ActionDeny, "credential path " + p + " denied (credential facts are never allow)"
		}
		if isWrite(req.Tool, paramsTextOf(req)) {
			return ActionDeny, "write to " + p + " outside granted paths and cwd (default deny)"
		}
	}
	if requireApproval[req.Tool] {
		return ActionHold, "tool " + req.Tool + " requires human approval per grant " + g.GrantID
	}
	for _, f := range g.Facts {
		if f.Domain == "tool" && f.Resource.Value == req.Tool && f.Effect == "allow" {
			rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, f.FactID)
		}
	}
	return ActionAllow, "granted by " + g.GrantID
}

// Observe records a tool result (spec §3.8.2 /v1/observe): taint update only.
func (e *Engine) Observe(req Request, result string) (*Receipt, error) {
	now := e.opts.Now()
	e.mu.Lock()
	defer e.mu.Unlock()
	s, err := e.sessionOrReject(req.SessionID, now)
	if err != nil {
		return nil, err
	}
	newTaints, ruleIDs := e.scanTaints(result)
	for _, t := range newTaints {
		s.taints[t] = true
	}
	if isEgress(req.Tool, "") || egressTools[req.Tool] {
		s.trifecta.UntrustedInput = true
		s.taints[taintUntrusted] = true
	}
	digest := sha256.Sum256([]byte(result))
	excerpt := truncate(e.analyzer.Redact(result), excerptMax)
	tf := s.trifecta
	rec := Receipt{
		ReceiptID: "rcp-" + hex.EncodeToString(digest[:])[:12] + "-" + now.Format("150405.000000") + "-obs",
		IssuedAt:  now.Format(time.RFC3339), Platform: req.Platform, SessionID: req.SessionID, Tool: req.Tool,
		ParamsDigest: hex.EncodeToString(digest[:]), ParamsExcerpt: &excerpt,
		Action: ActionAllow, Reason: "observation of tool result", MatchedFactIDs: []string{}, MatchedRuleIDs: ruleIDs,
		TaintLabels: sortedKeys(s.taints), Trifecta: &tf, EnforcementMode: e.opts.EnforcementMode,
		Engine: EngineInfo{Version: e.opts.Version, RulepackVersion: e.opts.Pack.Version},
	}
	if req.AgentID != "" {
		a := req.AgentID
		rec.AgentID = &a
	}
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	return &rec, nil
}

// AppendPendingObserved promotes one unsigned pending_decision/v1 line into a
// signed hash-chain receipt (DEV07-D / spec §3.8.4). Outcome deny→action deny;
// allow→action allow. Does not update session taint state.
func (e *Engine) AppendPendingObserved(p pending.Record) (*Receipt, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	action := ActionDeny
	if p.Outcome == "allow" {
		action = ActionAllow
	} else if p.Outcome != "" && p.Outcome != "deny" {
		return nil, fmt.Errorf("receipt: pending outcome %q not deny|allow", p.Outcome)
	}
	seed := p.RecordedAt + "|" + p.Platform + "|" + p.Tool + "|" + p.SessionID + "|" + p.Outcome + "|" + p.Reason
	digest := sha256.Sum256([]byte(seed))
	now := e.opts.Now()
	issued := p.RecordedAt
	if issued == "" {
		issued = now.Format(time.RFC3339)
	}
	mode := p.EnforcementMode
	if mode == "" {
		mode = e.opts.EnforcementMode
	}
	platform := p.Platform
	if platform == "" {
		platform = "other"
	}
	session := p.SessionID
	if session == "" {
		session = "pending-unknown"
	}
	tool := p.Tool
	if tool == "" {
		tool = "pending.fail_closed"
	}
	reason := "promoted pending fail-closed: " + p.Reason
	if p.Reason == "" {
		reason = "promoted pending fail-closed"
	}
	tf := Trifecta{}
	rec := Receipt{
		ReceiptID:       "rcp-" + hex.EncodeToString(digest[:])[:12] + "-pending",
		IssuedAt:        issued,
		Platform:        platform,
		SessionID:       session,
		Tool:            tool,
		ParamsDigest:    hex.EncodeToString(digest[:]),
		Action:          action,
		Reason:          reason,
		MatchedFactIDs:  []string{},
		MatchedRuleIDs:  []string{"pending.fail_closed"},
		TaintLabels:     []string{},
		Trifecta:        &tf,
		EnforcementMode: mode,
		Engine:          EngineInfo{Version: e.opts.Version, RulepackVersion: e.opts.Pack.Version},
	}
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	return &rec, nil
}

// ResolveHold records a human decision on a held call as a new receipt.
// Same decision is idempotent; opposite decision conflicts; expired holds refuse.
func (e *Engine) ResolveHold(held Receipt, approve bool, actorID string) (*Receipt, error) {
	if actorID == "" {
		return nil, errors.New("receipt: actor required to resolve hold")
	}
	if held.Action != ActionHold {
		return nil, errors.New("receipt: not a held call")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	now := e.opts.Now()
	if err := holdExpired(held, now); err != nil {
		return nil, err
	}
	want := ActionDeny
	if approve {
		want = ActionAllow
	}
	if existing, err := e.findHoldResolution(held.ReceiptID); err != nil {
		return nil, err
	} else if existing != nil {
		if existing.Action == want {
			return existing, nil
		}
		return nil, fmt.Errorf("%w: hold already resolved as %s", ErrHoldConflict, existing.Action)
	}
	action, reason := ActionDeny, "hold rejected by "+actorID
	if approve {
		action, reason = ActionAllow, "hold approved by "+actorID
	}
	resID := holdResolutionID(held.ReceiptID)
	rec := held
	rec.ReceiptID = resID
	rec.IssuedAt = now.Format(time.RFC3339)
	rec.Action, rec.Reason = action, reason
	rec.Hold = nil
	rec.AdvisoryAction = nil
	rec.DecisionLatencyMS = nil
	rec.Hash, rec.Sig = "", ""
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	return &rec, nil
}

// ErrHoldConflict means a hold was already resolved with a different decision.
var ErrHoldConflict = errors.New("receipt: hold resolution conflict")

// ErrHoldExpired means the hold timeout elapsed before resolution.
var ErrHoldExpired = errors.New("receipt: hold expired")

func holdResolutionID(heldID string) string {
	return heldID + "-res"
}

func (e *Engine) findHoldResolution(heldID string) (*Receipt, error) {
	all, err := e.opts.Chain.Read()
	if err != nil {
		return nil, err
	}
	want := holdResolutionID(heldID)
	for i := len(all) - 1; i >= 0; i-- {
		if all[i].ReceiptID == want && (all[i].Action == ActionAllow || all[i].Action == ActionDeny) {
			r := all[i]
			return &r, nil
		}
	}
	return nil, nil
}

func holdExpired(held Receipt, now time.Time) error {
	if held.Hold == nil || held.Hold.TimeoutMS <= 0 {
		return nil
	}
	issued, err := time.Parse(time.RFC3339, held.IssuedAt)
	if err != nil {
		issued, err = time.Parse(time.RFC3339Nano, held.IssuedAt)
	}
	if err != nil {
		return fmt.Errorf("receipt: held issued_at unreadable: %w", err)
	}
	deadline := issued.Add(time.Duration(held.Hold.TimeoutMS) * time.Millisecond)
	if now.After(deadline) {
		return fmt.Errorf("%w at %s", ErrHoldExpired, deadline.UTC().Format(time.RFC3339))
	}
	return nil
}

// sessionOrReject returns an existing session, or allocates one if under
// capacity. Never evicts tainted/trifecta sessions to free slots (DEV16-A/E).
// Untainted idle sessions may expire (lazy + sweep) before allocation.
// Caller must pass a single now for this request (avoid extra clock ticks).
func (e *Engine) sessionOrReject(id string, now time.Time) (*session, error) {
	if id == "" {
		return nil, errors.New("receipt: session_id required")
	}
	if s, ok := e.sessions[id]; ok {
		if e.idleExpiredLocked(s, now) {
			delete(e.sessions, id)
			e.sessionIdleExpired++
		} else {
			s.lastUsed = now
			return s, nil
		}
	}
	e.sweepIdleLocked(now)
	if len(e.sessions) >= e.maxSessions {
		e.sessionCapRefusals++
		return nil, ErrSessionCapacity
	}
	s := &session{taints: map[string]bool{}, lastUsed: now}
	e.sessions[id] = s
	return s, nil
}

func (s *session) retainsSecurityState() bool {
	if len(s.taints) > 0 {
		return true
	}
	return s.trifecta.PrivateData || s.trifecta.UntrustedInput || s.trifecta.Egress
}

func (e *Engine) idleExpiredLocked(s *session, now time.Time) bool {
	if e.sessionIdleTTL <= 0 || s == nil {
		return false
	}
	if s.retainsSecurityState() {
		return false
	}
	if s.lastUsed.IsZero() {
		return false
	}
	return !now.Before(s.lastUsed.Add(e.sessionIdleTTL))
}

func (e *Engine) sweepIdleLocked(now time.Time) {
	if e.sessionIdleTTL <= 0 {
		return
	}
	for id, s := range e.sessions {
		if e.idleExpiredLocked(s, now) {
			delete(e.sessions, id)
			e.sessionIdleExpired++
		}
	}
}

func (e *Engine) scanTaints(text string) ([]string, []string) {
	var taints, rules []string
	if containsSecretLiteral(e.analyzer, text) {
		taints = append(taints, taintSecret)
		rules = append(rules, "redaction:secret")
	}
	if piiRe.MatchString(text) {
		taints = append(taints, taintPII)
		rules = append(rules, "taint:pii")
	}
	res := e.analyzer.Analyze([]byte(text), "", "")
	for _, m := range res.Matches {
		rules = append(rules, m.RuleID)
	}
	if rules == nil {
		rules = []string{}
	}
	return taints, rules
}

func containsSecretLiteral(a *threat.Analyzer, text string) bool { return a.Redact(text) != text }

func (e *Engine) redactAllowed(req Request) bool {
	if e.opts.Grants == nil {
		return false
	}
	g := e.opts.Grants(req.Platform, req.AgentID)
	if g == nil {
		return false
	}
	for _, f := range g.Facts {
		if f.Domain == "credential" {
			if v, ok := f.Conditions["redact_secrets"].(bool); ok && v {
				return true
			}
		}
	}
	return false
}

// redactParams applies the redaction rules to every string leaf.
func redactParams(a *threat.Analyzer, params map[string]any) map[string]any {
	var walk func(x any) any
	walk = func(x any) any {
		switch t := x.(type) {
		case string:
			return a.Redact(t)
		case []any:
			out := make([]any, len(t))
			for i, e := range t {
				out[i] = walk(e)
			}
			return out
		case map[string]any:
			out := make(map[string]any, len(t))
			for k, e := range t {
				out[k] = walk(e)
			}
			return out
		}
		return x
	}
	if params == nil {
		return nil
	}
	return walk(params).(map[string]any)
}

func toolSets(g *grant.Grant) (allow, requireApproval map[string]bool) {
	allow, requireApproval = map[string]bool{}, map[string]bool{}
	if g.HermesToolsetAllowlist != nil {
		for _, t := range *g.HermesToolsetAllowlist {
			allow[t] = true
		}
	}
	if g.OpenClawToolPolicy != nil {
		for _, t := range g.OpenClawToolPolicy.Allow {
			allow[t] = true
		}
		for _, t := range g.OpenClawToolPolicy.RequireApproval {
			requireApproval[t] = true
		}
		for _, t := range g.OpenClawToolPolicy.Deny {
			delete(allow, t)
		}
	}
	// facts are the ground truth for platforms without a list output
	for _, f := range g.Facts {
		if f.Domain == "tool" && f.Effect == "allow" && (f.State == "declared" || f.State == "effective") {
			allow[f.Resource.Value] = true
		}
	}
	return allow, requireApproval
}

func hostGranted(g *grant.Grant, hostPort string) (string, bool) {
	host := hostPort
	if i := strings.LastIndex(host, ":"); i >= 0 {
		host = host[:i]
	}
	for _, f := range g.Facts {
		if f.Domain != "network" || f.Effect != "allow" {
			continue
		}
		v := f.Resource.Value
		vh := v
		if i := strings.LastIndex(vh, ":"); i >= 0 {
			vh = vh[:i]
		}
		switch {
		case v == hostPort, vh == host:
			return f.FactID, true
		case strings.HasPrefix(vh, "*.") && strings.HasSuffix(host, vh[1:]):
			return f.FactID, true
		}
	}
	return "", false
}

func pathGranted(g *grant.Grant, p, cwd string) (string, bool) {
	if cwd != "" && strings.HasPrefix(p, strings.TrimSuffix(cwd, "/")+"/") && !credPathRe.MatchString(p) {
		return "", true
	}
	for _, f := range g.Facts {
		if f.Domain != "filesystem" || f.Effect != "allow" {
			continue
		}
		v := strings.TrimSuffix(f.Resource.Value, "/")
		if p == v || strings.HasPrefix(p, v+"/") {
			return f.FactID, true
		}
	}
	return "", false
}

func isEgress(tool, paramsText string) bool {
	if egressTools[tool] {
		return true
	}
	if shellTools[tool] && paramsText != "" && (netCmdRe.MatchString(paramsText) || urlRe.MatchString(paramsText)) {
		return true
	}
	return false
}

var writeCmdRe = regexp.MustCompile(`(>>?|\b(cp|mv|tee|rm|chmod|install|mkdir)\b)`)

func isWrite(tool, paramsText string) bool {
	switch tool {
	case "write_file", "Write", "Edit", "patch":
		return true
	}
	return shellTools[tool] && writeCmdRe.MatchString(paramsText)
}

func paramsTextOf(req Request) string { return flattenStrings(req.Params) }

// flattenStrings joins every string leaf of params (depth-first, keys sorted)
// with newlines so line-oriented rules see the original text.
func flattenStrings(v any) string {
	var parts []string
	var walk func(x any)
	walk = func(x any) {
		switch t := x.(type) {
		case string:
			parts = append(parts, t)
		case []any:
			for _, e := range t {
				walk(e)
			}
		case map[string]any:
			keys := make([]string, 0, len(t))
			for k := range t {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				walk(t[k])
			}
		case json.Number:
			parts = append(parts, string(t))
		}
	}
	walk(v)
	return strings.Join(parts, "\n")
}

func extractHosts(tool, paramsText string) []string {
	if !isEgress(tool, paramsText) && !fileTools[tool] {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	for _, m := range urlRe.FindAllStringSubmatch(paramsText, -1) {
		host := strings.ToLower(m[1])
		port := m[2]
		if port == "" {
			port = "80"
			if strings.HasPrefix(strings.ToLower(m[0]), "https") {
				port = "443"
			}
		}
		hp := host + ":" + port
		if !seen[hp] {
			seen[hp] = true
			out = append(out, hp)
		}
	}
	for _, m := range hostArgRe.FindAllStringSubmatch(paramsText, -1) {
		hp := strings.ToLower(m[1]) + ":0"
		if !seen[hp] {
			seen[hp] = true
			out = append(out, hp)
		}
	}
	return out
}

func extractPaths(tool, paramsText string) []string {
	if !fileTools[tool] && !shellTools[tool] {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	for _, m := range pathRe.FindAllStringSubmatch(paramsText, -1) {
		p := strings.TrimRight(m[1], ".,;)")
		if p == "/" || seen[p] {
			continue
		}
		seen[p] = true
		out = append(out, p)
	}
	return out
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func appendUnique(list []string, s string) []string {
	for _, x := range list {
		if x == s {
			return list
		}
	}
	return append(list, s)
}

func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}

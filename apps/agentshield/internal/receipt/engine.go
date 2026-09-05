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
)

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
	Now             func() time.Time
	// UntrustedSkillLoaded reports whether the session has a non-admit skill
	// loaded (sets trifecta.untrusted_input).
	UntrustedSkillLoaded func(sessionID string) bool
}

type session struct {
	taints   map[string]bool
	trifecta Trifecta
}

// Engine decides tool calls.
type Engine struct {
	opts     Options
	analyzer *threat.Analyzer
	mu       sync.Mutex
	sessions map[string]*session
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
	return &Engine{opts: opts, analyzer: threat.New(opts.Pack), sessions: map[string]*session{}}, nil
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
	s := e.session(req.SessionID)

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
	e.mu.Lock()
	defer e.mu.Unlock()
	s := e.session(req.SessionID)
	newTaints, ruleIDs := e.scanTaints(result)
	for _, t := range newTaints {
		s.taints[t] = true
	}
	if isEgress(req.Tool, "") || egressTools[req.Tool] {
		s.trifecta.UntrustedInput = true
		s.taints[taintUntrusted] = true
	}
	digest := sha256.Sum256([]byte(result))
	now := e.opts.Now()
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

// ResolveHold records a human decision on a held call as a new receipt.
func (e *Engine) ResolveHold(held Receipt, approve bool, actorID string) (*Receipt, error) {
	if actorID == "" {
		return nil, errors.New("receipt: actor required to resolve hold")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	now := e.opts.Now()
	action, reason := ActionDeny, "hold rejected by "+actorID
	if approve {
		action, reason = ActionAllow, "hold approved by "+actorID
	}
	rec := held
	rec.ReceiptID = held.ReceiptID + "-res"
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

func (e *Engine) session(id string) *session {
	s, ok := e.sessions[id]
	if !ok {
		s = &session{taints: map[string]bool{}}
		e.sessions[id] = s
	}
	return s
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

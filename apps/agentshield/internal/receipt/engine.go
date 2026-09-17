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
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimeauthz"
	"siq-agent-security/apps/agentshield/internal/threat"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
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
	selectedGrant       *grant.Grant                  // resolved internally; never accepted from JSON
	ParameterProvenance []provenance.ParameterBinding `json:"parameter_provenance,omitempty"`
	ContextAssertionID  string                        `json:"context_assertion_id,omitempty"`
	ActionID            string                        `json:"action_id,omitempty"`
	DecisionReceiptID   string                        `json:"decision_receipt_id,omitempty"`
	Platform            string                        `json:"platform"`
	SessionID           string                        `json:"session_id"`
	AgentID             string                        `json:"agent_id"`
	Tool                string                        `json:"tool"`
	ToolCallID          string                        `json:"tool_call_id"`
	Params              map[string]any                `json:"params"`
	Context             map[string]any                `json:"context"`
	TaskID              string                        `json:"task_id,omitempty"`
	// RuntimeTaskID is the host runtime's per-task identity. TaskID remains an
	// optional hint for the trusted Intent task and must never be overloaded by
	// adapters with a host-local routing ID. SEC and native retry boundaries use
	// RuntimeTaskID, falling back to TaskID for pre-R01 clients.
	RuntimeTaskID string          `json:"runtime_task_id,omitempty"`
	IntentID      string          `json:"intent_id,omitempty"`
	Principal     string          `json:"principal,omitempty"`
	Intent        *IntentContract `json:"intent,omitempty"`
	// Skill is the runtime's claim about which skill version produced this
	// call. It is untrusted input: it never grants anything by itself and is
	// only resolved to a verified attribution through the trusted lookup.
	Skill *SkillClaim `json:"skill,omitempty"`
}

// SkillClaim is a runtime-declared skill identity (untrusted).
type SkillClaim struct {
	SkillID     string `json:"skill_id"`
	Version     string `json:"version,omitempty"`
	ContentHash string `json:"content_hash,omitempty"`
}

// Skill attribution statuses. verified requires an exact match against trusted
// local state; unknown/mismatch never authorize a skill-scoped grant and are
// never displayed as verified.
const (
	SkillAttributionUnclaimed = "unclaimed"
	SkillAttributionVerified  = "verified"
	SkillAttributionMismatch  = "mismatch"
	SkillAttributionUnknown   = "unknown"
)

// SkillAttribution is the engine's trusted resolution of a runtime skill claim,
// signed into the receipt chain.
type SkillAttribution struct {
	SkillID     string `json:"skill_id,omitempty"`
	Version     string `json:"version,omitempty"`
	ContentHash string `json:"content_hash,omitempty"`
	Status      string `json:"status"`
	// EvidenceLevel and ContextID exist only on verified attributions produced
	// by a skill execution context (N05/R01); CallBinding is the sha256 over the
	// canonical (platform, session, agent, task, tool, tool_call_id, params) of
	// the decided call, so the receipt alone re-proves the binding.
	EvidenceLevel string `json:"evidence_level,omitempty"`
	ContextID     string `json:"context_id,omitempty"`
	CallBinding   string `json:"call_binding,omitempty"`
}

// SkillAttributionLookup resolves a runtime skill claim against trusted local
// state (approved skill version records). Returning nil means the claim cannot
// be attributed. Implementations must derive the result from trusted state,
// never from the claim alone.
type SkillAttributionLookup func(platform, sessionID, agentID string, claim *SkillClaim) *SkillAttribution

// SkillContextVerification is the outcome of resolving daemon-issued skill
// execution contexts (SEC) for the request subject (N05/R01).
//
// A nil verification means no SEC covers the subject: the request follows the
// pre-SEC claim path unchanged. Invalid reports a SEC that matched the subject
// but failed verification; the engine must deny (authority class) and never
// fall back to a baseline grant.
type SkillContextVerification struct {
	// Valid SEC fields (Invalid=false):
	ContextID     string
	EvidenceLevel string
	SkillID       string
	Version       string
	ContentHash   string
	Grant         *grant.Grant
	// Invalid SEC (Invalid=true): ReasonCode is a stable skill_context_* code.
	Invalid    bool
	ReasonCode string
}

// SkillContextLookup returns the SEC verification for one request subject.
// It runs entirely against trusted server-side state; the request contributes
// lookup keys only. Implementations must re-verify signature, expiry,
// revocation and every live dependency (grant digest, install record) on each
// call. The claim is already shape-validated by the engine; a claim that
// conflicts with the SEC skill identity must yield Invalid.
type SkillContextLookup func(platform, agentID, sessionID, taskID string, claim *SkillClaim) *SkillContextVerification

// IntentLookup resolves authority from trusted local state. Implementations
// must verify the stored digest/signature before returning an intent.
type IntentLookup func(platform, sessionID, agentID string) (*IntentContract, error)

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
	ParameterProvenance []provenance.ParameterBinding `json:"parameter_provenance,omitempty"`
	ContextAssertionID  string                        `json:"context_assertion_id,omitempty"`
	AuthorityStatus     string                        `json:"authority_status,omitempty"`
	AuthorityReasonCode string                        `json:"authority_reason_code,omitempty"`
	PolicyAction        string                        `json:"policy_action,omitempty"`
	EffectiveAction     string                        `json:"effective_action,omitempty"`
	Principal           *runtimeaction.Principal      `json:"principal,omitempty"`
	ResourceRefs        []runtimeaction.ResourceRef   `json:"resource_refs,omitempty"`
	ProvenanceRefs      []string                      `json:"provenance_refs,omitempty"`
	RecordType          string                        `json:"record_type,omitempty"`
	DecisionReceiptID   string                        `json:"decision_receipt_id,omitempty"`
	ParentActionID      string                        `json:"parent_action_id,omitempty"`
	TaskSeq             int                           `json:"task_seq,omitempty"`
	ReceiptID           string                        `json:"receipt_id"`
	ChainID             string                        `json:"chain_id"`
	Seq                 int                           `json:"seq"`
	PrevHash            string                        `json:"prev_hash"`
	Hash                string                        `json:"hash"`
	Sig                 string                        `json:"sig"`
	IssuedAt            string                        `json:"issued_at"`
	Platform            string                        `json:"platform"`
	SessionID           string                        `json:"session_id"`
	ActionID            string                        `json:"action_id,omitempty"`
	AgentID             *string                       `json:"agent_id"`
	TaskID              string                        `json:"task_id,omitempty"`
	RuntimeTaskID       string                        `json:"runtime_task_id,omitempty"`
	IntentID            string                        `json:"intent_id,omitempty"`
	IntentDigest        string                        `json:"intent_digest,omitempty"`
	IntentBinding       string                        `json:"intent_binding,omitempty"`
	AuthorityRevision   string                        `json:"authority_revision,omitempty"`
	Tool                string                        `json:"tool"`
	ToolCallID          *string                       `json:"tool_call_id"`
	Operation           string                        `json:"operation,omitempty"`
	Effects             []string                      `json:"effects,omitempty"`
	ParamsDigest        string                        `json:"params_digest"`
	ParamsExcerpt       *string                       `json:"params_excerpt"`
	Action              string                        `json:"action"`
	AdvisoryAction      *string                       `json:"advisory_action"`
	Reason              string                        `json:"reason"`
	ReasonCode          string                        `json:"reason_code,omitempty"`
	MatchedGrantID      *string                       `json:"matched_grant_id"`
	MatchedFactIDs      []string                      `json:"matched_fact_ids"`
	MatchedRuleIDs      []string                      `json:"matched_rule_ids"`
	TaintLabels         []string                      `json:"taint_labels"`
	Trifecta            *Trifecta                     `json:"trifecta"`
	EnforcementMode     string                        `json:"enforcement_mode"`
	PolicyRevision      *string                       `json:"policy_revision"`
	SandboxID           *string                       `json:"sandbox_id"`
	ModelKey            *string                       `json:"model_key"`
	Engine              EngineInfo                    `json:"engine"`
	DecisionLatencyMS   *int                          `json:"decision_latency_ms"`
	Hold                *Hold                         `json:"hold"`
	SkillAttribution    *SkillAttribution             `json:"skill_attribution,omitempty"`
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
	// StageTiming is a trusted, nonblocking, non-reentrant benchmark observer.
	StageTiming     func(stage string, elapsed time.Duration)
	ProvenanceCheck func(map[string]any, []provenance.ParameterBinding, []provenance.Constraint, provenance.Scope, time.Time) error
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
	// SkillAttribution resolves runtime skill claims against trusted state.
	// nil → every claim stays unknown (fail closed for skill-scoped grants).
	SkillAttribution SkillAttributionLookup
	// SkillAttributionEnforced turns on the skill-scoped grant gate (UX-007).
	// Off (default) skill-scoped grants behave as baseline: platform adapters
	// do not yet attach runtime skill claims, so enforcing now would deny
	// every call. Claims are still resolved and signed into receipts either
	// way, and are never displayed as verified unless the lookup confirms.
	SkillAttributionEnforced bool
	// SkillContexts resolves daemon-issued skill execution contexts (N05/R01).
	// nil → no SEC ever applies and behavior is identical to pre-SEC builds.
	// A matched-but-invalid SEC denies regardless of enforcement mode.
	SkillContexts SkillContextLookup
	// BaselineGrants returns the newest live grant without a skill scope for
	// the agent; it is the second leg of the SEC permission intersection.
	BaselineGrants    GrantLookup
	IntentLookup      IntentLookup
	ContextLookup     func(string) (*trustedcontext.Assertion, error)
	IntentEnforcement string // optional (legacy) or required (fail closed)
}

type session struct {
	boundPrincipal         *runtimeaction.Principal
	boundProvenanceRefs    []string
	taskSeq                int
	parentActionID         string
	taints                 map[string]bool
	trifecta               Trifecta
	lastUsed               time.Time
	boundIntentID          string
	boundTaskID            string
	boundIntentDigest      string
	boundAuthorityRevision string
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
	actions            map[string]*actionRecord
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
	if opts.IntentEnforcement == "" {
		opts.IntentEnforcement = "optional"
	}
	if opts.IntentEnforcement != "optional" && opts.IntentEnforcement != "required" {
		return nil, fmt.Errorf("receipt: invalid intent_enforcement %q", opts.IntentEnforcement)
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
	eng := &Engine{
		opts:           opts,
		analyzer:       threat.New(opts.Pack),
		sessions:       map[string]*session{},
		actions:        map[string]*actionRecord{},
		maxSessions:    maxSess,
		sessionIdleTTL: idleTTL,
	}
	if err := eng.restoreActionState(); err != nil {
		return nil, err
	}
	return eng, nil
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
	credPathRe = regexp.MustCompile(`(?i)(?:^|/)(\.env(?:\.[a-z]+)?|\.ssh|\.aws|\.gnupg|\.netrc|\.docker/config\.json|\.kube/config|id_rsa|id_ed25519|credentials|auth\.json|\.npmrc|\.pypirc)(?:/|$)`)
	piiRe      = regexp.MustCompile(`\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,16}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`)
)

// Decide evaluates a tool call (spec §3.8.2) and appends a receipt.
func (e *Engine) Decide(req Request) (*Decision, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	start := e.opts.Now()
	req.selectedGrant = nil
	parameterErr := runtimeaction.ValidateParameters(req.Params)
	runtimeTaskID := requestRuntimeTaskID(req)
	runtimeTaskInvalid := !validExecutionText(runtimeTaskID, 256, true)
	// Intent authority is resolved from trusted state; a decision client may
	// never mint or replace it inline.
	if req.Intent != nil {
		return nil, fmt.Errorf("inline intent is not accepted; use a trusted session binding")
	}
	s, err := e.sessionOrReject(req.SessionID, start)
	if err != nil {
		return nil, err
	}
	skillAttribution := e.resolveSkillAttribution(req)
	// SEC resolution (N05/R01): a valid skill execution context overrides the
	// claim-derived attribution with a verified one; a matched-but-invalid SEC
	// hard denies later via the authority path, regardless of mode.
	var sec *SkillContextVerification
	if !runtimeTaskInvalid {
		sec = e.resolveSkillContext(req)
	}
	var resolvedIntent *IntentContract
	var authorityErr error
	if e.opts.IntentLookup != nil {
		finish := e.stageTimer("intent_lookup")
		resolvedIntent, authorityErr = e.opts.IntentLookup(req.Platform, req.SessionID, req.AgentID)
		if resolvedIntent != nil {
			req.selectedGrant = resolvedIntent.SelectedGrant
		}
		finish()
	}
	if sec != nil && !sec.Invalid {
		// The SEC grant is server-selected authority; a trusted intent binding
		// that pins a different grant conflicts and invalidates the context.
		if req.selectedGrant != nil && req.selectedGrant.GrantID != sec.Grant.GrantID {
			sec = &SkillContextVerification{Invalid: true, ReasonCode: "skill_context_grant_conflict"}
		} else {
			req.selectedGrant = sec.Grant
			skillAttribution = &SkillAttribution{
				SkillID: sec.SkillID, Version: sec.Version, ContentHash: sec.ContentHash,
				Status: SkillAttributionVerified, EvidenceLevel: sec.EvidenceLevel, ContextID: sec.ContextID,
			}
		}
	}
	finishAuthority := e.stageTimer("authority_validation")
	// A revoked but verified binding still identifies the trusted task for its
	// denial receipt. Retain that metadata without clearing taints or the error.
	if authorityErr != nil && resolvedIntent != nil && resolvedIntent.Trusted != nil && s.boundIntentID == "" {
		s.taskSeq, s.parentActionID = 0, ""
		s.boundIntentID, s.boundTaskID = resolvedIntent.IntentID, resolvedIntent.TaskID
		s.boundIntentDigest, s.boundAuthorityRevision = resolvedIntent.Digest, resolvedIntent.AuthorityRevision
		s.boundPrincipal = &runtimeaction.Principal{Type: "user", ID: resolvedIntent.Principal}
		s.boundProvenanceRefs = append([]string(nil), resolvedIntent.Trusted.ProvenanceRefs...)
	}
	if authorityErr == nil {
		switch {
		case s.boundIntentID != "" && resolvedIntent == nil:
			authorityErr = &intent.Violation{Code: "intent_downgrade_attempt"}
		case e.opts.IntentEnforcement == "required" && resolvedIntent == nil:
			authorityErr = &intent.Violation{Code: "intent_binding_missing"}
		case resolvedIntent != nil:
			if s.boundIntentID != "" && (s.boundIntentID != resolvedIntent.IntentID || s.boundTaskID != resolvedIntent.TaskID || s.boundIntentDigest != resolvedIntent.Digest || s.boundAuthorityRevision != resolvedIntent.AuthorityRevision) {
				authorityErr = &intent.Violation{Code: "intent_downgrade_attempt"}
			} else {
				// The first trusted task starts its own sequence without clearing taints.
				if s.boundIntentID == "" {
					s.taskSeq = 0
					s.parentActionID = ""
				}
				s.boundPrincipal = &runtimeaction.Principal{Type: "user", ID: resolvedIntent.Principal}
				if resolvedIntent.Trusted != nil {
					s.boundProvenanceRefs = append([]string(nil), resolvedIntent.Trusted.ProvenanceRefs...)
				}
				// Bind security state even if this particular action is outside its authority.
				s.boundIntentID, s.boundTaskID = resolvedIntent.IntentID, resolvedIntent.TaskID
				s.boundIntentDigest, s.boundAuthorityRevision = resolvedIntent.Digest, resolvedIntent.AuthorityRevision
				switch {
				case req.IntentID != "" && req.IntentID != resolvedIntent.IntentID:
					authorityErr = &intent.Violation{Code: "intent_downgrade_attempt"}
				case req.TaskID != "" && req.TaskID != resolvedIntent.TaskID:
					authorityErr = &intent.Violation{Code: "intent_task_mismatch"}
				default:
					if parameterErr == nil {
						authorityErr = resolvedIntent.validate(req, start)
					}
				}
			}
		}
	}

	if parameterErr != nil {
		authorityErr = &intent.Violation{Code: "runtime_parameter_budget_exceeded"}
	} else if runtimeTaskInvalid {
		authorityErr = &intent.Violation{Code: "runtime_task_invalid"}
	}
	finishAuthority()
	if err := e.actionCapacity(start); err != nil {
		return nil, err
	}
	paramsJSON, paramsErr := json.Marshal(req.Params)
	if paramsErr != nil {
		return nil, fmt.Errorf("runtime parameters are not JSON encodable")
	}
	// scan the raw string values, not the JSON encoding (which escapes quotes
	// and > < & and would hide `token="..."` or `> /etc/...` from the rules)
	paramsText := ""
	if parameterErr == nil {
		paramsText = flattenStrings(req.Params)
	}
	digest := sha256.Sum256(paramsJSON)

	paramsDigest := hex.EncodeToString(digest[:])
	if authorityErr == nil {
		if code := e.pendingReservedExecution(req, paramsDigest); code != "" {
			authorityErr = &intent.Violation{Code: code}
		}
	}
	finishNormalization := e.stageTimer("runtime_action_normalization")
	descriptor := runtimeaction.Describe(req.Tool, req.Params)
	finishNormalization()
	operation, effects := descriptor.Operation, descriptor.Effects
	// Preserve the host task identity even when no Intent is bound. It remains
	// untrusted input and grants no authority by itself, but signed correlation
	// records (SEC attribution and approved retry) must not erase the task
	// boundary they validated. A trusted Intent binding remains authoritative.
	taskID := req.TaskID
	if s.boundTaskID != "" {
		taskID = s.boundTaskID
	}
	intentID := s.boundIntentID
	intentDigest := s.boundIntentDigest
	authorityRevision := s.boundAuthorityRevision

	resources := descriptor.Resources
	resourceRefs := runtimeaction.ResourceRefs(resources)
	chainSeq, _ := e.opts.Chain.Head()
	actionID := runtimeaction.ActionID(runtimeaction.Envelope{
		Sequence:  chainSeq + 1,
		Principal: s.boundPrincipal, ResourceRefs: resourceRefs, ProvenanceRefs: s.boundProvenanceRefs,
		Platform:     req.Platform,
		SessionID:    req.SessionID,
		AgentID:      req.AgentID,
		TaskID:       taskID,
		IntentID:     intentID,
		Tool:         req.Tool,
		ToolCallID:   req.ToolCallID,
		Operation:    operation,
		Effects:      effects,
		ParamsDigest: paramsDigest,
	})
	s.taskSeq++
	rec := Receipt{
		ParameterProvenance: req.ParameterProvenance,
		ContextAssertionID:  req.ContextAssertionID,
		RecordType:          "decision", TaskSeq: s.taskSeq, ParentActionID: s.parentActionID,
		Principal: s.boundPrincipal, ResourceRefs: resourceRefs, ProvenanceRefs: append([]string(nil), s.boundProvenanceRefs...),
		ReceiptID:         "rcp-" + hex.EncodeToString(digest[:])[:12] + "-" + start.Format("150405.000000"),
		IssuedAt:          start.Format(time.RFC3339),
		Platform:          req.Platform,
		SessionID:         req.SessionID,
		ActionID:          actionID,
		Tool:              req.Tool,
		TaskID:            taskID,
		RuntimeTaskID:     runtimeTaskID,
		IntentID:          intentID,
		IntentDigest:      intentDigest,
		IntentBinding:     "unbound",
		AuthorityRevision: authorityRevision,
		Operation:         operation,
		Effects:           effects,
		ParamsDigest:      paramsDigest,
		MatchedFactIDs:    []string{},
		MatchedRuleIDs:    []string{},
		TaintLabels:       []string{},
		EnforcementMode:   e.opts.EnforcementMode,
		Engine:            EngineInfo{Version: e.opts.Version, RulepackVersion: e.opts.Pack.Version},
		SkillAttribution:  skillAttribution,
	}
	if resolvedIntent != nil || s.boundIntentID != "" {
		rec.IntentBinding = "bound"
	}
	if req.AgentID != "" {
		a := req.AgentID
		rec.AgentID = &a
	}
	if req.ToolCallID != "" {
		t := req.ToolCallID
		rec.ToolCallID = &t
	}
	// A verified attribution binds the exact final call: tool, tool call ID and
	// the final parameter set. If the adapter cannot name the call, the SEC
	// cannot verify it and the decision must fail closed instead of recording
	// an unbound verified attribution.
	if sec != nil && !sec.Invalid {
		binding, bindingErr := trustedcontext.CallBinding(req.Platform, req.SessionID, req.AgentID, runtimeTaskID, req.Tool, req.ToolCallID, req.Params)
		if bindingErr != nil {
			sec = &SkillContextVerification{Invalid: true, ReasonCode: "skill_context_invalid"}
			skillAttribution = e.resolveSkillAttribution(req)
			rec.SkillAttribution = skillAttribution
		} else {
			skillAttribution.CallBinding = binding
			rec.SkillAttribution = skillAttribution
		}
	}
	excerpt := truncate(e.analyzer.Redact(paramsText), excerptMax)
	rec.ParamsExcerpt = &excerpt

	// Accumulate parameter taints after authority validation, before policy
	// evaluation. This lets a proven message routing field be classified without
	// treating its mailbox as a disclosed payload; existing taints are never cleared.
	if descriptor.Egress {
		s.trifecta.Egress = true
	}
	if e.opts.UntrustedSkillLoaded != nil && e.opts.UntrustedSkillLoaded(req.SessionID) {
		s.trifecta.UntrustedInput = true
	}
	paths := descriptor.Paths
	for _, p := range paths {
		if credPathRe.MatchString(p) {
			s.taints[taintPrivate] = true
			s.trifecta.PrivateData = true
		}
	}
	tf := s.trifecta
	rec.Trifecta = &tf

	validationCode := ""
	if authorityErr != nil {
		validationCode = "intent_authority_invalid"
		var violation *intent.Violation
		if errors.As(authorityErr, &violation) {
			validationCode = violation.Code
		}
	}
	authority := runtimeauthz.Authority(validationCode, rec.IntentBinding == "bound")
	if authority.Valid && sec != nil && sec.Invalid {
		// A SEC matched this subject but failed verification (revoked, expired,
		// grant or install drift, claim conflict). This is an authority-class
		// failure: advisory modes must not allow it, and the request must never
		// fall back to a baseline grant.
		authority = runtimeauthz.Authority(sec.ReasonCode, rec.IntentBinding == "bound")
	}
	if authority.Valid && req.ContextAssertionID != "" {
		finish := e.stageTimer("context_validation")
		contextErr := e.checkContext(req, taskID, start)
		finish()
		if err := contextErr; err != nil {
			code := "trusted_context_invalid"
			var v *trustedcontext.Violation
			if errors.As(err, &v) {
				code = v.Code
			}
			authority = runtimeauthz.Authority(code, rec.IntentBinding == "bound")
		}
	}
	if authority.Valid {
		finish := e.stageTimer("provenance_resolution")
		provenanceErr := e.checkProvenance(req, resolvedIntent, start)
		finish()
		if err := provenanceErr; err != nil {
			code := "provenance_authority_invalid"
			var v *provenance.Violation
			if errors.As(err, &v) {
				code = v.Code
			}
			authority = runtimeauthz.Authority(code, rec.IntentBinding == "bound")
		}
	}
	rec.AuthorityStatus, rec.AuthorityReasonCode = authority.Status, authority.ReasonCode
	piiText := paramsText
	if authority.Valid {
		piiText = messagePayloadPIIText(req, resolvedIntent, descriptor, paramsText)
	}
	newTaints, ruleIDs := e.scanTaintsWithPII(paramsText, piiText)
	for _, t := range newTaints {
		s.taints[t] = true
	}
	rec.MatchedRuleIDs = ruleIDs
	rec.TaintLabels = sortedKeys(s.taints)
	policy := runtimeauthz.PolicyResult{}
	var redacted map[string]any
	if authority.Valid {
		finish := e.stageTimer("policy_evaluation")
		policy.Action, policy.Reason = e.evaluate(req, s, descriptor, &rec, start, sec)
		if policy.Reason == "intent_grant_installation_binding_required" {
			authority = runtimeauthz.Authority(policy.Reason, rec.IntentBinding == "bound")
			rec.AuthorityStatus, rec.AuthorityReasonCode = authority.Status, authority.ReasonCode
		}
		if policy.Action == ActionDeny && strings.HasPrefix(policy.Reason, "tainted egress") && e.redactAllowed(req, start) && containsSecretLiteral(e.analyzer, paramsText) {
			candidate := redactParams(e.analyzer, req.Params)
			// Redaction is a data transform, never authority to skip host/path
			// constraints or a per-tool human approval requirement.
			checked := req
			checked.Params = candidate
			cleanSession := *s
			cleanSession.taints = map[string]bool{}
			for label, present := range s.taints {
				if label != taintSecret {
					cleanSession.taints[label] = present
				}
			}
			checkedReceipt := rec
			if action, _ := e.evaluate(checked, &cleanSession, runtimeaction.Describe(req.Tool, candidate), &checkedReceipt, start, sec); action == ActionAllow && checkedReceipt.MatchedGrantID != nil && rec.MatchedGrantID != nil && *checkedReceipt.MatchedGrantID == *rec.MatchedGrantID {
				redacted = candidate
				rec.MatchedFactIDs = checkedReceipt.MatchedFactIDs
				policy.Action, policy.Reason = ActionRedact, "secret literal removed from params before egress (grant permits redaction)"
				// The executed call carries the redacted parameters; the verified
				// attribution must bind those, not the pre-redaction input.
				if sec != nil && rec.SkillAttribution != nil && rec.SkillAttribution.Status == SkillAttributionVerified {
					if b, berr := trustedcontext.CallBinding(req.Platform, req.SessionID, req.AgentID, runtimeTaskID, req.Tool, req.ToolCallID, candidate); berr == nil {
						rec.SkillAttribution.CallBinding = b
					}
				}
			}
		}
		policy.ReasonCode = classifyReason(policy.Reason, policy.Action)
		if validationCode != "" {
			policy.Action, policy.ReasonCode, policy.Reason = ActionDeny, validationCode, validationCode
			redacted = nil
		}
		rec.PolicyAction = policy.Action
		finish()
	}
	action, advisory := runtimeauthz.ApplyMode(authority, policy, e.opts.EnforcementMode)
	rec.AdvisoryAction = advisory
	reason := policy.Reason
	authorityCode := policy.ReasonCode
	if !authority.Valid {
		reason, authorityCode = authority.ReasonCode, authority.ReasonCode
	} else if advisory != nil {
		redacted = nil
		if e.opts.EnforcementMode == "warn" {
			reason = "WARN: " + reason
		}
	}
	var hold *Hold
	if action == ActionHold {
		hold = &Hold{Channel: e.opts.HoldChannel, TimeoutMS: e.opts.HoldTimeoutMS}
		rec.Hold = hold
	}
	rec.EffectiveAction = action
	rec.Action = action
	rec.Reason = reason
	rec.ReasonCode = classifyReason(reason, action)
	if authorityCode != "" {
		rec.ReasonCode = authorityCode
	}
	lat := int(e.opts.Now().Sub(start).Milliseconds())
	rec.DecisionLatencyMS = &lat

	finishAppend := e.stageTimer("receipt_append_fsync")
	appendErr := e.opts.Chain.Append(&rec)
	finishAppend()
	if err := appendErr; err != nil {
		return nil, err
	}
	// issued_at is signed at whole-second precision. Use the same deadline as
	// restoreActionState; subsecond wall time must not extend a live authority.
	e.actions[rec.ActionID] = &actionRecord{decision: rec, expires: start.Truncate(time.Second).Add(actionWindow)}
	if action == ActionAllow || action == ActionRedact {
		s.parentActionID = rec.ActionID
	}
	return &Decision{Action: action, Reason: reason, Receipt: rec, Params: redacted, Hold: hold}, nil
}

func classifyReason(reason, action string) string {
	r := strings.ToLower(reason)
	switch {
	case strings.Contains(r, "no deployed grant"):
		return "grant_missing"
	case r == "grant permission expired":
		return "grant_expired"
	case r == "grant expiration invalid":
		return "grant_expiration_invalid"
	case strings.Contains(r, "not granted") || strings.Contains(r, "outside granted"):
		return "grant_scope_violation"
	case strings.Contains(r, "skill attribution does not verify"):
		return "skill_attribution_mismatch"
	case strings.Contains(r, "intent"):
		return "intent_violation"
	case strings.Contains(r, "lethal trifecta"):
		return "lethal_trifecta"
	case strings.Contains(r, "tainted egress"):
		return "session_taint_violation"
	case action == ActionAllow:
		return "allow"
	default:
		return "runtime_denied"
	}
}

var (
	skillIDPattern      = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$`)
	skillVersionPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
	hex64Pattern        = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// validSkillClaim bounds the untrusted runtime claim so malformed identities
// can never reach a trusted record comparison or the signed receipt.
func validSkillClaim(c *SkillClaim) bool {
	if c == nil || !skillIDPattern.MatchString(c.SkillID) || len(c.Version) > 64 || len(c.ContentHash) > 64 {
		return false
	}
	if c.Version != "" && !skillVersionPattern.MatchString(c.Version) {
		return false
	}
	if c.ContentHash != "" && !hex64Pattern.MatchString(c.ContentHash) {
		return false
	}
	return true
}

// resolveSkillAttribution turns the runtime's untrusted skill claim into a
// trusted attribution record. A claim without an exact trusted match stays
// unknown; it is never treated as verified, whatever the runtime reports.
func (e *Engine) resolveSkillAttribution(req Request) *SkillAttribution {
	claim := req.Skill
	if claim == nil {
		return nil
	}
	if !validSkillClaim(claim) {
		return &SkillAttribution{Status: SkillAttributionUnknown}
	}
	if e.opts.SkillAttribution != nil {
		if a := e.opts.SkillAttribution(req.Platform, req.SessionID, req.AgentID, claim); a != nil {
			switch a.Status {
			case SkillAttributionVerified, SkillAttributionMismatch, SkillAttributionUnknown:
				return a
			}
		}
	}
	return &SkillAttribution{SkillID: claim.SkillID, Version: claim.Version, ContentHash: claim.ContentHash, Status: SkillAttributionUnknown}
}

// resolveSkillContext resolves a daemon-issued skill execution context for the
// request subject. It returns nil when no SEC covers the subject (the request
// then follows the pre-SEC claim path unchanged). Lookup results that violate
// the contract shape are treated as invalid (fail closed), never trusted.
func (e *Engine) resolveSkillContext(req Request) *SkillContextVerification {
	if e.opts.SkillContexts == nil {
		return nil
	}
	claim := req.Skill
	if claim != nil && !validSkillClaim(claim) {
		claim = nil
	}
	v := e.opts.SkillContexts(req.Platform, req.AgentID, req.SessionID, requestRuntimeTaskID(req), claim)
	if v == nil {
		return nil
	}
	if v.Invalid {
		code := v.ReasonCode
		if !strings.HasPrefix(code, "skill_context_") {
			code = "skill_context_invalid"
		}
		return &SkillContextVerification{Invalid: true, ReasonCode: code}
	}
	if v.ContextID == "" || v.Grant == nil || v.Grant.Skill == nil ||
		v.Grant.Skill.SkillID != v.SkillID || v.Grant.Skill.ContentHash != v.ContentHash ||
		!validSkillClaim(&SkillClaim{SkillID: v.SkillID, Version: v.Version, ContentHash: v.ContentHash}) ||
		(v.EvidenceLevel != "controlled_task" && v.EvidenceLevel != "controlled_session") {
		return &SkillContextVerification{Invalid: true, ReasonCode: "skill_context_invalid"}
	}
	return v
}

func requestRuntimeTaskID(req Request) string {
	if req.RuntimeTaskID != "" {
		return req.RuntimeTaskID
	}
	return req.TaskID
}

func receiptRuntimeTaskID(rec Receipt) string {
	if rec.RuntimeTaskID != "" {
		return rec.RuntimeTaskID
	}
	return rec.TaskID
}

// skillAttributionMatches reports whether the trusted attribution covers the
// grant's approved skill version exactly. Anything less (unclaimed, unknown,
// version or content drift) fails closed.
func skillAttributionMatches(ref grant.SkillRef, a *SkillAttribution) bool {
	if a == nil || a.Status != SkillAttributionVerified {
		return false
	}
	if a.SkillID != ref.SkillID || a.ContentHash != ref.ContentHash {
		return false
	}
	if ref.Version != nil && a.Version != *ref.Version {
		return false
	}
	return true
}

// evaluate performs steps 2–5 and returns the raw (pre-mode) action. A valid
// SEC switches evaluation to the permission intersection of the SEC-bound
// grant and the agent's baseline grant (N05/R01 §3.4).
func (e *Engine) evaluate(req Request, s *session, descriptor runtimeaction.Descriptor, rec *Receipt, now time.Time, sec *SkillContextVerification) (string, string) {
	if sec != nil {
		return e.evaluateIntersection(req, s, descriptor, rec, now, sec)
	}
	g := req.selectedGrant
	unselected := req.selectedGrant == nil
	if g == nil && e.opts.Grants != nil {
		g = e.opts.Grants(req.Platform, req.AgentID)
	}
	return e.evaluateGrant(req, s, descriptor, rec, now, g, unselected)
}

// evaluateIntersection applies the SEC-bound grant first and the agent's
// baseline grant second. The effective permission is the backend-computed
// intersection: any deny wins, otherwise any hold wins, otherwise allow.
// Without a live distinct baseline the SEC grant is the whole intersection.
func (e *Engine) evaluateIntersection(req Request, s *session, descriptor runtimeaction.Descriptor, rec *Receipt, now time.Time, sec *SkillContextVerification) (string, string) {
	action, reason := e.evaluateGrant(req, s, descriptor, rec, now, sec.Grant, false)
	if action == ActionDeny {
		return action, reason
	}
	var baseline *grant.Grant
	if e.opts.BaselineGrants != nil {
		baseline = e.opts.BaselineGrants(req.Platform, req.AgentID)
	}
	if baseline == nil || baseline.GrantID == sec.Grant.GrantID || baseline.Skill != nil {
		return action, reason
	}
	scratch := &Receipt{MatchedFactIDs: []string{}}
	baction, breason := e.evaluateGrant(req, s, descriptor, scratch, now, baseline, false)
	for _, fid := range scratch.MatchedFactIDs {
		rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
	}
	gid := sec.Grant.GrantID
	rec.MatchedGrantID = &gid
	switch {
	case baction == ActionDeny:
		return ActionDeny, "baseline grant " + baseline.GrantID + " intersection: " + breason
	case action == ActionHold:
		return ActionHold, reason
	case baction == ActionHold:
		return ActionHold, "baseline grant " + baseline.GrantID + " intersection: " + breason
	default:
		return ActionAllow, "granted by " + sec.Grant.GrantID + " intersect " + baseline.GrantID
	}
}

// evaluateGrant is the single-grant policy evaluation (spec §3.8.2 steps 2-5).
// unselected marks a grant from the default lookup rather than a trusted
// binding; import-reserved grants deny unless explicitly selected.
func (e *Engine) evaluateGrant(req Request, s *session, descriptor runtimeaction.Descriptor, rec *Receipt, now time.Time, g *grant.Grant, unselected bool) (string, string) {
	hosts, paths := descriptor.Hosts, descriptor.Paths
	if g == nil || (g.Status != "deployed" && g.Status != "effective" && !(!unselected && g.Status == "approved" && importsource.Reserved(g.AdmissionID))) {
		return ActionDeny, "no deployed grant for agent (default deny)"
	}

	if unselected && importsource.Reserved(g.AdmissionID) {
		return ActionDeny, "intent_grant_installation_binding_required"
	}
	gid := g.GrantID
	rec.MatchedGrantID = &gid
	if err := grant.ValidateLifetime(*g, now); err != nil {
		if errors.Is(err, grant.ErrExpired) {
			return ActionDeny, "grant permission expired"
		}
		return ActionDeny, "grant expiration invalid"
	}

	// A skill-scoped grant only serves calls attributed to exactly its
	// approved skill version; forged, switched or borrowed identities (and no
	// claim at all) fall through to default deny (UX-007, N05). Installed
	// grants use an import-reserved admission and always require a verified
	// SEC. The legacy feature flag remains for non-install grant flows whose
	// platform adapter cannot yet provide a trusted execution context.
	requireSkillAttribution := g.Skill != nil && (e.opts.SkillAttributionEnforced || importsource.Reserved(g.AdmissionID))
	if requireSkillAttribution && !skillAttributionMatches(*g.Skill, rec.SkillAttribution) {
		return ActionDeny, "skill attribution does not verify for grant (default deny)"
	}

	if !grant.ScenarioAllowsEffects(g.Scenario, descriptor.Effects) {
		return ActionDeny, "operation not granted by scenario"
	}
	allow, requireApproval := toolSets(g)
	switch {
	case requireApproval[req.Tool]:
		// still run data checks below; hold is the floor, deny can override
	case allow[req.Tool]:
	default:
		return ActionDeny, "tool " + req.Tool + " not granted (default deny)"
	}

	// step 5 first: taint / trifecta rules override everything for egress
	if descriptor.Egress || len(hosts) > 0 {
		if s.taints[taintSecret] || s.taints[taintPII] {
			return ActionDeny, "tainted egress: session carries " + strings.Join(sortedKeys(s.taints), ",") + " taint"
		}
		if s.trifecta.PrivateData && s.trifecta.UntrustedInput {
			return ActionDeny, "lethal trifecta: private data + untrusted input + egress in one session"
		}
	}

	// step 4b: hosts must be granted
	if descriptor.Operation == "request" && !descriptor.ShellLike {
		var ok bool
		hosts, ok = structuredGrantEndpoints(req.Params)
		if !ok {
			return ActionDeny, "network target not granted (unavailable resource)"
		}
	}
	for _, h := range hosts {
		fid, ok := hostGranted(g, h)
		if !ok {
			return ActionDeny, "network egress to " + h + " not in grant " + g.GrantID + " (default deny)"
		}
		rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
	}
	if descriptor.ShellLike && descriptor.Egress && len(hosts) == 0 {
		return ActionDeny, "egress exec requires granted host"
	}
	// step 4c: observational caller context cannot grant filesystem access
	fileOperation := false
	for _, effect := range descriptor.Effects {
		if effect == runtimeaction.EffectFileRead || effect == runtimeaction.EffectFileWrite || effect == runtimeaction.EffectFileDelete {
			fileOperation = true
		}
	}
	if fileOperation && (len(paths) == 0 || descriptor.ResourceError != nil) {
		return ActionDeny, "filesystem target not granted (unavailable resource)"
	}
	for _, p := range paths {
		if credPathRe.MatchString(p) {
			return ActionDeny, "credential path " + p + " denied (credential facts are never allow)"
		}
		if fid, ok := pathGranted(g, p, descriptor.FilesystemWriteHint); ok {
			if fid != "" {
				rec.MatchedFactIDs = appendUnique(rec.MatchedFactIDs, fid)
			}
			continue
		}
		if fileOperation || descriptor.FilesystemWriteHint {
			return ActionDeny, "filesystem target " + p + " outside granted paths (default deny)"
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
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.resolveHoldLocked(held, approve, actorID)
}

func (e *Engine) resolveHoldLocked(held Receipt, approve bool, actorID string) (*Receipt, error) {
	if actorID == "" {
		return nil, errors.New("receipt: actor required to resolve hold")
	}
	if held.Action != ActionHold {
		return nil, errors.New("receipt: not a held call")
	}
	now := e.opts.Now()
	if err := holdExpired(held, now); err != nil {
		return nil, err
	}
	if approve && held.IntentBinding == "bound" {
		if e.opts.IntentLookup == nil {
			return nil, correlationError("hold_authority_changed")
		}
		current, err := e.opts.IntentLookup(held.Platform, held.SessionID, str(held.AgentID))
		if err != nil || current == nil || current.IntentID != held.IntentID || current.TaskID != held.TaskID || current.Digest != held.IntentDigest || current.AuthorityRevision != held.AuthorityRevision {
			return nil, correlationError("hold_authority_changed")
		}
		if current.SelectedGrant != nil && current.SelectedGrant.GrantID != str(held.MatchedGrantID) {
			return nil, correlationError("hold_authority_changed")
		}
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
	rec.IssuedAt = now.Format(time.RFC3339Nano)
	rec.Action, rec.Reason = action, reason
	if rec.EffectiveAction != "" {
		rec.EffectiveAction = action
	}
	rec.RecordType = "hold_resolution"
	rec.DecisionReceiptID = held.ReceiptID
	rec.Hold = nil
	rec.AdvisoryAction = nil
	rec.DecisionLatencyMS = nil
	rec.Hash, rec.Sig = "", ""
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	if entry := e.actions[held.ActionID]; entry != nil {
		entry.approved = approve
		entry.approvedAt = now
		entry.holdResolved = true
		if approve {
			if session := e.sessions[held.SessionID]; session != nil && session.boundTaskID == held.TaskID && session.boundIntentID == held.IntentID {
				session.parentActionID = held.ActionID
			}
		}
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
	if !now.Before(deadline) {
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
	if s.boundIntentID != "" {
		return false
	}
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
	return e.scanTaintsWithPII(text, text)
}

func (e *Engine) scanTaintsWithPII(text, piiText string) ([]string, []string) {
	var taints, rules []string
	if containsSecretLiteral(e.analyzer, text) {
		taints = append(taints, taintSecret)
		rules = append(rules, "redaction:secret")
	}
	if piiRe.MatchString(piiText) {
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

func (e *Engine) redactAllowed(req Request, now time.Time) bool {
	g := req.selectedGrant
	if g == nil && e.opts.Grants != nil {
		g = e.opts.Grants(req.Platform, req.AgentID)
	}
	if g == nil || (g.Status != "deployed" && g.Status != "effective" && !(req.selectedGrant != nil && g.Status == "approved" && importsource.Reserved(g.AdmissionID))) || grant.ValidateLifetime(*g, now) != nil {
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
	return grant.RuntimeToolSets(g)
}

func flattenStrings(v any) string { return runtimeaction.FlattenStrings(v) }

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

// stageTimer uses a monotonic performance clock, never the injected authority clock.
func (e *Engine) stageTimer(stage string) func() {
	if e.opts.StageTiming == nil {
		return func() {}
	}
	start := time.Now()
	return func() { e.opts.StageTiming(stage, time.Since(start)) }
}

// Package grant implements least-privilege-grant (dev-spec §3.7): it turns the
// declared facts of an admission into platform allowlists and a backend-neutral
// desired policy, under default-deny, deny-overrides-allow, explicit overlap
// handling and a human-only approval state machine. Output conforms to
// packages/contracts/grant.schema.json.
package grant

import (
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// Fact is a permission fact inside a grant (five-state).
type Fact struct {
	FactID             string             `json:"fact_id"`
	Domain             string             `json:"domain"`
	Action             string             `json:"action"`
	Resource           admission.Resource `json:"resource"`
	Effect             string             `json:"effect"`
	Conditions         map[string]any     `json:"conditions,omitempty"`
	State              string             `json:"state"`
	Authority          string             `json:"authority"`
	AuthorityRevision  *string            `json:"authority_revision"`
	ReadbackEvidenceID *string            `json:"readback_evidence_id"`
	EvidenceIDs        []string           `json:"evidence_ids"`
}

// Subject of the grant.
type Subject struct {
	Type string `json:"type"`
	ID   string `json:"id"`
}

// OpenClawToolPolicy maps to before_tool_call decisions.
type OpenClawToolPolicy struct {
	Allow           []string `json:"allow"`
	Deny            []string `json:"deny"`
	RequireApproval []string `json:"require_approval"`
}

// DesiredPolicyRef points at the compiled desired policy.
type DesiredPolicyRef struct {
	PolicyID                 string   `json:"policy_id"`
	Version                  int      `json:"version"`
	StaticDomainsUnavailable []string `json:"static_domains_unavailable"`
}

// Overlap records same-domain resource pattern overlap.
type Overlap struct {
	Domain     string   `json:"domain"`
	FactIDs    []string `json:"fact_ids"`
	Resolution string   `json:"resolution"` // deny_overrides | manual | unresolved
	Note       *string  `json:"note"`
}

// Approval is the human sign-off record.
type Approval struct {
	ActorType  string `json:"actor_type"`
	ActorID    string `json:"actor_id"`
	ApprovedAt string `json:"approved_at"`
	Channel    string `json:"channel,omitempty"`
}

// Readback is the backend read-back proof required for effective.
type Readback struct {
	Backend    string `json:"backend"`
	Revision   string `json:"revision"`
	VerifiedAt string `json:"verified_at"`
	EvidenceID string `json:"evidence_id"`
}

// Grant is the signed document.
type Grant struct {
	GrantID                string              `json:"grant_id"`
	AdmissionID            string              `json:"admission_id"`
	Subject                Subject             `json:"subject"`
	Platform               string              `json:"platform"`
	Facts                  []Fact              `json:"facts"`
	DefaultEffect          string              `json:"default_effect"`
	HermesToolsetAllowlist *[]string           `json:"hermes_toolset_allowlist,omitempty"`
	OpenClawToolPolicy     *OpenClawToolPolicy `json:"openclaw_tool_policy,omitempty"`
	DesiredPolicyRef       *DesiredPolicyRef   `json:"desired_policy_ref"`
	OverlapConflicts       []Overlap           `json:"overlap_conflicts"`
	EnforcementMode        string              `json:"enforcement_mode"`
	Status                 string              `json:"status"`
	ApprovedBy             *Approval           `json:"approved_by"`
	EffectiveReadback      *Readback           `json:"effective_readback"`
	CreatedAt              string              `json:"created_at"`
	ExpiresAt              *string             `json:"expires_at"`
	Signature              string              `json:"signature"`
}

// DesiredPolicy is the backend-neutral policy derived alongside the grant
// (desired-policy.schema.json shape as a generic map for the compiler).
type DesiredPolicy = map[string]any

// Options for Build.
type Options struct {
	Subject         Subject
	Platform        string
	EnforcementMode string
	Now             time.Time
	Key             *signing.Key
	// RedactSecrets is recorded in conditions of credential deny facts so the
	// decide engine knows redaction is permitted (spec §3.8.2 step 6).
	RedactSecrets bool
}

// Result of Build.
type Result struct {
	Grant         Grant
	DesiredPolicy DesiredPolicy
}

var validPlatforms = map[string]bool{"openclaw": true, "hermes": true, "codebuddy": true, "trae": true, "claude_code": true, "codex": true, "other": true}

// Build derives a draft/pending grant from an admission. Quarantined
// admissions cannot be granted.
func Build(adm admission.Admission, opts Options) (*Result, error) {
	if opts.Key == nil {
		return nil, errors.New("grant: signing key required")
	}
	if adm.Verdict == "quarantine" {
		return nil, errors.New("grant: quarantined admission cannot be granted")
	}
	if !validPlatforms[opts.Platform] {
		return nil, fmt.Errorf("grant: unknown platform %q", opts.Platform)
	}
	if opts.EnforcementMode == "" {
		opts.EnforcementMode = "block"
	}
	if opts.Now.IsZero() {
		opts.Now = time.Now().UTC()
	}
	now := opts.Now.Format(time.RFC3339)
	g := Grant{
		GrantID:          "grt-" + adm.ContentHash[:12] + "-" + shortID(opts.Platform+opts.Subject.ID),
		AdmissionID:      adm.AdmissionID,
		Subject:          opts.Subject,
		Platform:         opts.Platform,
		DefaultEffect:    "deny",
		EnforcementMode:  opts.EnforcementMode,
		Status:           "draft",
		CreatedAt:        now,
		OverlapConflicts: []Overlap{},
	}
	dp := DesiredPolicy{
		"policy_id":        "pol-" + adm.ContentHash[:12],
		"selector":         map[string]any{"agent_ids": []any{opts.Subject.ID}},
		"version":          1,
		"status":           "validated",
		"enforcement_mode": opts.EnforcementMode,
	}

	var facts []Fact
	hermes := map[string]bool{}
	oc := OpenClawToolPolicy{Allow: []string{}, Deny: []string{}, RequireApproval: []string{}}
	ocAllow, ocReq := map[string]bool{}, map[string]bool{}
	var netRules []any
	fsRW := map[string]bool{}
	var models []any
	var tools []any
	needsProcess := false

	for i, d := range adm.DeclaredFacts {
		f := Fact{
			FactID: fmt.Sprintf("pf-%d-%s", i+1, shortID(d.Domain+d.Action+d.Resource.Value)),
			Domain: d.Domain, Action: d.Action, Resource: d.Resource, Effect: "allow",
			State: "declared", Authority: "skill_manifest", EvidenceIDs: d.EvidenceIDs,
		}
		switch d.Domain {
		case "tool":
			hermes[d.Resource.Value] = true
			ocAllow[d.Resource.Value] = true
			tools = append(tools, d.Resource.Value)
		case "network":
			netRules = append(netRules, map[string]any{"endpoint": d.Resource.Value, "effect": "allow"})
		case "filesystem":
			fsRW[d.Resource.Value] = true
		case "process":
			needsProcess = true
			hermes["terminal"] = true
			ocReq["exec"] = true
		case "resource": // package.install
			ocReq["exec"] = true
			hermes["terminal"] = true
		case "model":
			models = append(models, d.Resource.Value)
		case "credential":
			// never converted to allow: an explicit inferred deny + approval gate
			f.Effect = "deny"
			f.State = "inferred"
			f.Authority = "agentshield"
			f.Conditions = map[string]any{"reason": "credential access requires per-use approval", "redact_secrets": opts.RedactSecrets}
			ocReq["exec"] = true
		}
		facts = append(facts, f)
	}
	if needsProcess {
		facts = append(facts, Fact{
			FactID: "pf-inf-" + shortID("forbid_privilege_escalation"), Domain: "process", Action: "process.privilege_escalation",
			Resource: admission.Resource{Type: "capability", Value: "setuid/sudo"}, Effect: "deny", State: "inferred",
			Authority: "agentshield", EvidenceIDs: adm.EvidenceIDs,
		})
		dp["process"] = map[string]any{"forbid_privilege_escalation": true}
	}
	if len(netRules) > 0 {
		dp["network"] = netRules
	}
	if len(fsRW) > 0 {
		rw := keysSorted(fsRW)
		dp["filesystem"] = map[string]any{"read_only": []any{}, "read_write": toAny(rw)}
	}
	if len(models) > 0 {
		dp["model_routing"] = map[string]any{"allowed_models": models}
	}
	if len(tools) > 0 {
		dp["tools"] = tools
	}

	// deny overrides allow; detect overlaps
	facts, g.OverlapConflicts = resolveOverlaps(facts)
	g.Facts = facts
	if g.Facts == nil {
		g.Facts = []Fact{}
	}

	switch opts.Platform {
	case "hermes":
		al := keysSorted(hermes)
		g.HermesToolsetAllowlist = &al
	case "openclaw":
		oc.Allow = keysSorted(ocAllow)
		oc.RequireApproval = keysSorted(ocReq)
		g.OpenClawToolPolicy = &oc
	}

	var static []string
	if _, ok := dp["filesystem"]; ok {
		static = append(static, "filesystem")
	}
	if _, ok := dp["process"]; ok {
		static = append(static, "process")
	}
	if static == nil {
		static = []string{}
	}
	g.DesiredPolicyRef = &DesiredPolicyRef{PolicyID: dp["policy_id"].(string), Version: 1, StaticDomainsUnavailable: static}

	g.Status = "pending_approval"
	g.Signature = sign(opts.Key, g)
	return &Result{Grant: g, DesiredPolicy: dp}, nil
}

// resolveOverlaps applies spec §3.7.2: same domain + same resource type with
// overlapping patterns. Different effects → deny_overrides (the allow is
// dropped). Same effect → manual/unresolved (a human must confirm the merge).
func resolveOverlaps(facts []Fact) ([]Fact, []Overlap) {
	overlaps := []Overlap{}
	drop := map[string]bool{}
	for i := 0; i < len(facts); i++ {
		for j := i + 1; j < len(facts); j++ {
			a, b := facts[i], facts[j]
			if a.Domain != b.Domain || a.Resource.Type != b.Resource.Type || !patternsOverlap(a.Resource.Value, b.Resource.Value) {
				continue
			}
			ids := []string{a.FactID, b.FactID}
			if a.Effect != b.Effect {
				note := "deny overrides allow; allow fact dropped from outputs"
				overlaps = append(overlaps, Overlap{Domain: a.Domain, FactIDs: ids, Resolution: "deny_overrides", Note: &note})
				if a.Effect == "allow" {
					drop[a.FactID] = true
				} else {
					drop[b.FactID] = true
				}
				continue
			}
			note := "same-effect pattern overlap; confirm merge in console"
			overlaps = append(overlaps, Overlap{Domain: a.Domain, FactIDs: ids, Resolution: "unresolved", Note: &note})
		}
	}
	if len(drop) == 0 {
		return facts, overlaps
	}
	out := make([]Fact, 0, len(facts))
	for _, f := range facts {
		if !drop[f.FactID] {
			out = append(out, f)
		}
	}
	return out, overlaps
}

// patternsOverlap: identical, glob/prefix containment ("a/*" or "a/" vs
// "a/b"), or wildcard host ("*.example.com" vs "api.example.com:443").
func patternsOverlap(x, y string) bool {
	if x == y {
		return true
	}
	return contains(x, y) || contains(y, x)
}

func contains(pattern, value string) bool {
	switch {
	case strings.HasSuffix(pattern, "/*"):
		return strings.HasPrefix(value, strings.TrimSuffix(pattern, "*"))
	case strings.HasSuffix(pattern, "/"):
		return strings.HasPrefix(value, pattern)
	case strings.HasPrefix(pattern, "*."):
		host := value
		if i := strings.Index(host, ":"); i >= 0 {
			host = host[:i]
		}
		return strings.HasSuffix(host, pattern[1:])
	}
	return false
}

// ResolveOverlap marks an unresolved overlap as manually accepted. Only a
// human may do this; the grant is re-signed.
func ResolveOverlap(g Grant, idx int, actor Approval, key *signing.Key) (Grant, error) {
	if actor.ActorType != "human" {
		return g, errors.New("grant: only a human may resolve overlaps")
	}
	if idx < 0 || idx >= len(g.OverlapConflicts) {
		return g, errors.New("grant: overlap index out of range")
	}
	if g.OverlapConflicts[idx].Resolution != "unresolved" {
		return g, errors.New("grant: overlap already resolved")
	}
	g.OverlapConflicts[idx].Resolution = "manual"
	note := "merged by " + actor.ActorID + " at " + actor.ApprovedAt
	g.OverlapConflicts[idx].Note = &note
	g.Signature = sign(key, g)
	return g, nil
}

var transitions = map[string][]string{
	"draft":            {"pending_approval", "rejected", "revoked"},
	"pending_approval": {"approved", "rejected", "revoked"},
	"approved":         {"deployed", "revoked"},
	"deployed":         {"effective", "revoked"},
	"effective":        {"revoked"},
}

func canTransition(from, to string) bool {
	for _, t := range transitions[from] {
		if t == to {
			return true
		}
	}
	return false
}

// Approve moves pending_approval → approved. Fails unless the actor is human
// and no overlap is unresolved (mirrors the schema's if/then).
func Approve(g Grant, actor Approval, key *signing.Key) (Grant, error) {
	if !canTransition(g.Status, "approved") {
		return g, fmt.Errorf("grant: cannot approve from %s", g.Status)
	}
	if actor.ActorType != "human" || actor.ActorID == "" {
		return g, errors.New("grant: only a human actor may approve (ADR-003)")
	}
	for _, o := range g.OverlapConflicts {
		if o.Resolution == "unresolved" {
			return g, errors.New("grant: unresolved overlap conflicts block approval")
		}
	}
	a := actor
	g.ApprovedBy = &a
	g.Status = "approved"
	g.Signature = sign(key, g)
	return g, nil
}

// Reject / Revoke are terminal transitions.
func Reject(g Grant, key *signing.Key) (Grant, error) { return transition(g, "rejected", key) }

// Revoke ends any grant (admission superseded or manual).
func Revoke(g Grant, key *signing.Key) (Grant, error) { return transition(g, "revoked", key) }

// MarkDeployed records that platform files / OpenShell policy were written.
func MarkDeployed(g Grant, key *signing.Key) (Grant, error) { return transition(g, "deployed", key) }

func transition(g Grant, to string, key *signing.Key) (Grant, error) {
	if !canTransition(g.Status, to) {
		return g, fmt.Errorf("grant: illegal transition %s → %s", g.Status, to)
	}
	g.Status = to
	g.Signature = sign(key, g)
	return g, nil
}

// MarkEffective moves deployed → effective. factReadbacks maps fact_id →
// readback evidence id for facts the backend confirmed; only those become
// effective (with the backend revision). Facts in static-unavailable domains
// are never promoted.
func MarkEffective(g Grant, rb Readback, factReadbacks map[string]string, key *signing.Key) (Grant, error) {
	if !canTransition(g.Status, "effective") {
		return g, fmt.Errorf("grant: cannot mark effective from %s", g.Status)
	}
	if rb.Revision == "" || rb.EvidenceID == "" || rb.Backend == "" {
		return g, errors.New("grant: readback requires backend, revision and evidence_id")
	}
	static := map[string]bool{}
	if g.DesiredPolicyRef != nil {
		for _, d := range g.DesiredPolicyRef.StaticDomainsUnavailable {
			static[d] = true
		}
	}
	promoted := 0
	for i := range g.Facts {
		ev, ok := factReadbacks[g.Facts[i].FactID]
		if !ok {
			continue
		}
		if static[g.Facts[i].Domain] {
			return g, fmt.Errorf("grant: fact %s is in static domain %s and cannot be effective without generation", g.Facts[i].FactID, g.Facts[i].Domain)
		}
		rev := rb.Revision
		e := ev
		g.Facts[i].State = "effective"
		g.Facts[i].Authority = rb.Backend
		g.Facts[i].AuthorityRevision = &rev
		g.Facts[i].ReadbackEvidenceID = &e
		promoted++
	}
	if promoted == 0 {
		return g, errors.New("grant: no fact confirmed by readback")
	}
	r := rb
	g.EffectiveReadback = &r
	g.Status = "effective"
	g.Signature = sign(key, g)
	return g, nil
}

func sign(key *signing.Key, g Grant) string {
	raw, _ := json.Marshal(g)
	dec, err := canon.Decode(raw)
	if err != nil {
		return ""
	}
	m := dec.(map[string]any)
	delete(m, "signature")
	sig, err := key.SignCanonical(m)
	if err != nil {
		return ""
	}
	return sig
}

// Verify checks the grant signature.
func Verify(pub []byte, g Grant) bool {
	raw, _ := json.Marshal(g)
	dec, err := canon.Decode(raw)
	if err != nil {
		return false
	}
	m := dec.(map[string]any)
	sig, _ := m["signature"].(string)
	delete(m, "signature")
	return signing.VerifyCanonical(pub, m, sig)
}

func keysSorted(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func toAny(ss []string) []any {
	out := make([]any, len(ss))
	for i, s := range ss {
		out[i] = s
	}
	return out
}

func shortID(s string) string {
	h := uint32(2166136261)
	for i := 0; i < len(s); i++ {
		h ^= uint32(s[i])
		h *= 16777619
	}
	return fmt.Sprintf("%08x", h)
}

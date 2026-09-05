// Package inventory implements agent-asset-inventory (dev-spec §3.5) as a
// read-only, native discovery of agent platforms, skill directories and
// well-known MCP client configs on the local machine. It never starts MCP
// servers and never imports skill code or connectors/* (optional
// --connectors-dir only execs connector binaries). Platform configs contribute
// only existence, size and hash (and, for a few well-known keys, whether an
// AgentShield adapter is installed). MCP configs contribute mcp_server
// candidates with env key names and scheme://host only. Output conforms to
// candidate.schema.json / evidence.schema.json / permission-fact.schema.json.
package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// Candidate mirrors candidate.schema.json.
type Candidate struct {
	CandidateID    string            `json:"candidate_id"`
	SourceType     string            `json:"source_type"`
	SourceLocator  string            `json:"source_locator"`
	DiscoveredAt   string            `json:"discovered_at"`
	Name           string            `json:"name"`
	Framework      string            `json:"framework"`
	ArtifactDigest string            `json:"artifact_digest,omitempty"`
	Attributes     map[string]string `json:"attributes"`
	EvidenceIDs    []string          `json:"evidence_ids"`
	Confidence     float64           `json:"confidence"`
	Status         string            `json:"status"`
}

// Fact mirrors permission-fact.schema.json (observed facts about adapters).
type Fact struct {
	Subject     Subject            `json:"subject"`
	Domain      string             `json:"domain"`
	Action      string             `json:"action"`
	Resource    admission.Resource `json:"resource"`
	Effect      string             `json:"effect"`
	State       string             `json:"state"`
	Authority   string             `json:"authority"`
	EvidenceIDs []string           `json:"evidence_ids"`
}

// Subject mirrors permission-fact.subject.
type Subject struct {
	Type string `json:"type"`
	ID   string `json:"id"`
}

// Report is one inventory run.
type Report struct {
	GeneratedAt string               `json:"generated_at"`
	Home        string               `json:"home"`
	Platforms   []string             `json:"platforms"`
	Candidates  []Candidate          `json:"candidates"`
	Evidence    []admission.Evidence `json:"evidence"`
	Facts       []Fact               `json:"facts"`
	Skipped     []string             `json:"skipped"` // paths that could not be read (category only)
}

// Options for Run.
type Options struct {
	Home    string // defaults to os.UserHomeDir
	Cwd     string // project-level skill dirs are discovered under Cwd
	Now     time.Time
	Version string
	Key     *signing.Key
	// HasAdmission tells whether a skill content_hash already has an admission.
	HasAdmission func(contentHash string) (verdict string, ok bool)
	Limits       admission.Limits
	// ConnectorsDir is an optional parent of hermes/openclaw/directory/mcp
	// connector binaries (exec --serve). Empty skips subprocesses.
	ConnectorsDir string
}

type platformSpec struct {
	name       string
	framework  string
	configs    []string // relative to home; existence + hash only
	skillDirs  []string // relative to home
	projectDir []string // relative to cwd
}

// Well-known locations (docs checked 2026-09; see compatibility.md).
var platforms = []platformSpec{
	{"hermes", "hermes", []string{".hermes/config.yaml"}, []string{".hermes/skills"}, nil},
	{"openclaw", "openclaw", []string{".openclaw/openclaw.json"}, []string{".openclaw/skills", ".agents/skills"}, []string{"skills", ".agents/skills"}},
	{"codebuddy", "codebuddy", []string{".codebuddy/settings.json"}, []string{".codebuddy/skills"}, []string{".codebuddy/skills"}},
	{"trae", "trae", nil, []string{".trae/skills"}, []string{".trae/skills", ".agents/skills"}},
	{"claude_code", "claude_code", []string{".claude/settings.json"}, []string{".claude/skills"}, []string{".claude/skills"}},
	{"codex", "codex", []string{".codex/config.toml"}, []string{".codex/skills"}, nil},
}

var frontName = regexp.MustCompile(`(?m)^name:\s*(.+)$`)
var frontDesc = regexp.MustCompile(`(?m)^description:\s*(.+)$`)
var frontTools = regexp.MustCompile(`(?m)^allowed-tools:\s*(.+)$`)

// Run performs discovery.
func Run(opts Options) (*Report, error) {
	if opts.Key == nil {
		return nil, errors.New("inventory: signing key required")
	}
	if opts.Home == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		opts.Home = h
	}
	if opts.Now.IsZero() {
		opts.Now = time.Now().UTC()
	}
	r := &run{opts: opts, now: opts.Now.Format(time.RFC3339), report: &Report{GeneratedAt: opts.Now.Format(time.RFC3339), Home: redactHome(opts.Home, opts.Home)}}
	r.report.Platforms = []string{}
	r.report.Candidates = []Candidate{}
	r.report.Evidence = []admission.Evidence{}
	r.report.Facts = []Fact{}
	r.report.Skipped = []string{}

	seenSkillDir := map[string]bool{}
	for _, p := range platforms {
		present := false
		for _, c := range p.configs {
			full := filepath.Join(opts.Home, c)
			if r.platformConfig(p, full, c) {
				present = true
			}
		}
		for _, d := range p.skillDirs {
			full := filepath.Join(opts.Home, d)
			if r.skillDir(p, full, seenSkillDir) {
				present = true
			}
		}
		if opts.Cwd != "" {
			for _, d := range p.projectDir {
				r.skillDir(p, filepath.Join(opts.Cwd, d), seenSkillDir)
			}
		}
		if present {
			r.report.Platforms = append(r.report.Platforms, p.name)
		}
	}
	if r.hermesProfiles(filepath.Join(opts.Home, ".hermes", "profiles")) {
		if !containsStr(r.report.Platforms, "hermes") {
			r.report.Platforms = append(r.report.Platforms, "hermes")
		}
	}
	r.mcpConfigs()
	r.mergeConnectors()
	sort.Strings(r.report.Platforms)
	sort.Slice(r.report.Candidates, func(i, j int) bool { return r.report.Candidates[i].CandidateID < r.report.Candidates[j].CandidateID })
	sort.Slice(r.report.Evidence, func(i, j int) bool { return r.report.Evidence[i].EvidenceID < r.report.Evidence[j].EvidenceID })
	return r.report, nil
}

type run struct {
	opts   Options
	now    string
	report *Report
}

func (r *run) platformConfig(p platformSpec, full, rel string) bool {
	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		return false
	}
	raw, err := os.ReadFile(full)
	if err != nil {
		r.report.Skipped = append(r.report.Skipped, "unreadable:"+p.name+":"+rel)
		return true
	}
	sum := sha256.Sum256(raw)
	locator := p.name + "://" + rel
	evID := r.evidence("platform_config", locator, hex.EncodeToString(sum[:]))
	attrs := map[string]string{"platform": p.name, "config": rel, "bytes": itoa(len(raw))}
	// adapter detection: only well-known keys, never values of secrets
	l1, l2 := adapterInstalled(p.name, raw)
	if l1 {
		attrs["agentshield_install_gate"] = "true"
		r.fact(locator, "control_plane", "install.gate", "platform", p.name, evID, "observed")
	}
	if l2 {
		attrs["agentshield_tool_hook"] = "true"
		r.fact(locator, "control_plane", "tool.hook", "platform", p.name, evID, "observed")
	}
	if p.name == "hermes" {
		_, _, toolsets := extractConfigFacts(raw)
		modes := extractToolsetModeKeys(raw)
		if len(toolsets) > 0 {
			attrs["toolsets"] = joinCSV(toolsets)
			attrs["platform_toolsets"] = joinCSV(toolsets)
			r.declaredTools(locator, toolsets, evID)
		}
		if len(modes) > 0 {
			attrs["platform_toolset_modes"] = joinCSV(modes)
		}
	}
	if p.name == "openclaw" {
		r.openclawAgents(raw, evID)
	}
	r.report.Candidates = append(r.report.Candidates, Candidate{
		CandidateID: "platform:" + p.name, SourceType: "platform_config", SourceLocator: locator, DiscoveredAt: r.now,
		Name: p.name, Framework: p.framework, ArtifactDigest: hex.EncodeToString(sum[:]), Attributes: attrs,
		EvidenceIDs: []string{evID}, Confidence: 1.0, Status: "candidate",
	})
	return true
}

// adapterInstalled inspects known config shapes for AgentShield hooks.
func adapterInstalled(platform string, raw []byte) (installGate, toolHook bool) {
	var doc map[string]any
	if json.Unmarshal(raw, &doc) != nil {
		// Hermes YAML / Codex TOML: string search on the adapter marker only
		s := string(raw)
		return false, product.Mentions(s)
	}
	switch platform {
	case "openclaw":
		if sec, ok := doc["security"].(map[string]any); ok {
			if ip, ok := sec["installPolicy"].(map[string]any); ok {
				if ex, ok := ip["exec"].(map[string]any); ok {
					if cmd, _ := ex["command"].(string); product.Mentions(cmd) {
						installGate = true
					}
				}
			}
		}
		if plugins, ok := doc["plugins"].(map[string]any); ok {
			b, _ := json.Marshal(plugins)
			toolHook = product.Mentions(string(b))
		}
	case "codebuddy", "claude_code":
		if hooks, ok := doc["hooks"].(map[string]any); ok {
			b, _ := json.Marshal(hooks["PreToolUse"])
			toolHook = product.Mentions(string(b))
		}
	}
	return installGate, toolHook
}

func (r *run) skillDir(p platformSpec, dir string, seen map[string]bool) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	abs, _ := filepath.Abs(dir)
	found := false
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		skillPath := filepath.Join(dir, e.Name())
		absSkill := filepath.Join(abs, e.Name())
		if seen[absSkill] {
			continue
		}
		if _, err := os.Stat(filepath.Join(skillPath, "SKILL.md")); err != nil {
			continue
		}
		seen[absSkill] = true
		found = true
		r.skill(p, skillPath, e.Name())
	}
	return found
}

func (r *run) skill(p platformSpec, path, dirName string) {
	hash, files, err := admission.HashDir(path, r.opts.Limits)
	if err != nil {
		r.report.Skipped = append(r.report.Skipped, "unhashable:"+p.name+":"+dirName)
		return
	}
	md, _ := os.ReadFile(filepath.Join(path, "SKILL.md"))
	name := dirName
	if m := frontName.FindSubmatch(md); m != nil {
		name = strings.Trim(strings.TrimSpace(string(m[1])), `"'`)
	}
	attrs := map[string]string{"platform": p.name, "dir": dirName, "file_count": itoa(len(files))}
	if m := frontDesc.FindSubmatch(md); m != nil {
		attrs["description"] = truncate(strings.Trim(strings.TrimSpace(string(m[1])), `"'`), 200)
	}
	if m := frontTools.FindSubmatch(md); m != nil {
		attrs["allowed_tools"] = truncate(strings.TrimSpace(string(m[1])), 200)
	}
	if r.opts.HasAdmission != nil {
		if v, ok := r.opts.HasAdmission(hash); ok {
			attrs["admission_verdict"] = v
		} else {
			attrs["admission_verdict"] = "none"
		}
	}
	locator := p.name + "://skills/" + redactHome(path, r.opts.Home)
	evID := r.evidence("skill_dir", locator, hash)
	r.report.Candidates = append(r.report.Candidates, Candidate{
		CandidateID: "skill:" + p.name + ":" + name + "@" + hash[:12], SourceType: "skill_dir", SourceLocator: locator,
		DiscoveredAt: r.now, Name: name, Framework: p.framework, ArtifactDigest: hash, Attributes: attrs,
		EvidenceIDs: []string{evID}, Confidence: 1.0, Status: "candidate",
	})
}

func (r *run) evidence(sourceType, locator, contentHash string) string {
	id := "ev-" + shortHash(sourceType+"|"+locator+"|"+contentHash)
	ev := admission.Evidence{
		EvidenceID: id, SourceType: sourceType, SourceLocator: locator, ObservedAt: r.now, CollectedAt: r.now,
		CollectorID: "agentshield-local", ConnectorVersion: r.opts.Version, ContentHash: contentHash,
		RedactionProfile: "siq.redaction.v1", Classification: "internal",
	}
	ev.Signature = signDoc(r.opts.Key, ev)
	r.report.Evidence = append(r.report.Evidence, ev)
	return id
}

func (r *run) fact(locator, domain, action, rtype, rvalue, evID, state string) {
	if state == "" {
		state = "observed"
	}
	r.report.Facts = append(r.report.Facts, Fact{
		Subject: Subject{Type: "agent_asset", ID: locator}, Domain: domain, Action: action,
		Resource: admission.Resource{Type: rtype, Value: rvalue}, Effect: "allow", State: state,
		Authority: "agentshield", EvidenceIDs: []string{evID},
	})
}

func (r *run) declaredTools(locator string, tools []string, evID string) {
	for _, t := range tools {
		if t == "" {
			continue
		}
		r.fact(locator, "tool", "tool.invoke", "tool", t, evID, "declared")
	}
}

func (r *run) hermesProfiles(dir string) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	found := false
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		if name == "" || strings.HasPrefix(name, ".") {
			continue
		}
		cfg := filepath.Join(dir, name, "config.yaml")
		soul := filepath.Join(dir, name, "SOUL.md")
		var raw []byte
		srcFile := ""
		if b, err := os.ReadFile(cfg); err == nil {
			raw = b
			srcFile = "config.yaml"
		} else if b, err := os.ReadFile(soul); err == nil {
			raw = b
			srcFile = "SOUL.md"
		} else {
			continue
		}
		sum := sha256.Sum256(raw)
		locator := "hermes://profiles/" + name
		evID := r.evidence("platform_config", locator, hex.EncodeToString(sum[:]))
		attrs := map[string]string{"platform": "hermes", "profile": name, "config": srcFile}
		_, _, toolsets := extractConfigFacts(raw)
		modes := extractToolsetModeKeys(raw)
		if len(toolsets) > 0 {
			attrs["toolsets"] = joinCSV(toolsets)
			r.declaredTools(locator, toolsets, evID)
		}
		if len(modes) > 0 {
			attrs["platform_toolset_modes"] = joinCSV(modes)
		}
		r.report.Candidates = append(r.report.Candidates, Candidate{
			CandidateID: "agent:hermes:" + name, SourceType: "hermes_profile", SourceLocator: locator,
			DiscoveredAt: r.now, Name: name, Framework: "hermes", ArtifactDigest: hex.EncodeToString(sum[:]),
			Attributes: attrs, EvidenceIDs: []string{evID}, Confidence: 1.0, Status: "candidate",
		})
		found = true
	}
	return found
}

func (r *run) openclawAgents(raw []byte, configEv string) {
	var doc struct {
		Agents struct {
			List []struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"list"`
		} `json:"agents"`
	}
	if json.Unmarshal(raw, &doc) != nil {
		return
	}
	for _, a := range doc.Agents.List {
		id := strings.TrimSpace(a.ID)
		if id == "" {
			id = strings.TrimSpace(a.Name)
		}
		if id == "" || looksLikeSecret(id) {
			continue
		}
		name := strings.TrimSpace(a.Name)
		if name == "" {
			name = id
		}
		if looksLikeSecret(name) {
			name = id
		}
		locator := "openclaw://agents/" + id
		evID := configEv
		if evID == "" {
			sum := sha256.Sum256([]byte("openclaw-agent:" + id))
			evID = r.evidence("platform_config", locator, hex.EncodeToString(sum[:]))
		}
		attrs := map[string]string{"platform": "openclaw", "agent_id": id}
		r.report.Candidates = append(r.report.Candidates, Candidate{
			CandidateID: "agent:openclaw:" + id, SourceType: "openclaw_agent", SourceLocator: locator,
			DiscoveredAt: r.now, Name: name, Framework: "openclaw",
			Attributes: attrs, EvidenceIDs: []string{evID}, Confidence: 1.0, Status: "candidate",
		})
	}
}

func containsStr(ss []string, want string) bool {
	for _, s := range ss {
		if s == want {
			return true
		}
	}
	return false
}

func signDoc(key *signing.Key, v any) string {
	raw, _ := json.Marshal(v)
	dec, err := canon.Decode(raw)
	if err != nil {
		return ""
	}
	m := dec.(map[string]any)
	delete(m, "signature")
	sig, _ := key.SignCanonical(m)
	return sig
}

// redactHome replaces the home prefix so locators are stable and do not leak
// the user name.
func redactHome(p, home string) string {
	p = filepath.ToSlash(p)
	if home != "" && strings.HasPrefix(p, filepath.ToSlash(home)) {
		return "~" + strings.TrimPrefix(p, filepath.ToSlash(home))
	}
	return p
}

func shortHash(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])[:16]
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func itoa(i int) string {
	b, _ := json.Marshal(i)
	return string(b)
}

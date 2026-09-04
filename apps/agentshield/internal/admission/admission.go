// Package admission implements skill-admission (dev-spec §3.6): a static,
// deterministic pre-install verdict over a skill directory. It never executes
// or imports skill content. Output conforms to packages/contracts/admission.schema.json.
package admission

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/threat"
)

// EngineName is the admission.engine.name value for this implementation.
const EngineName = "agentshield-go"

const excerptMax = 200

// Source describes where the skill came from.
type Source struct {
	Type       string  `json:"type"`
	Locator    string  `json:"locator"`
	TrustLevel string  `json:"trust_level"`
	Ref        *string `json:"ref"`
}

// Resource is the (type, value) pair used by facts.
type Resource struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

// DeclaredFact is a permission fact with state=declared.
type DeclaredFact struct {
	Domain      string   `json:"domain"`
	Action      string   `json:"action"`
	Resource    Resource `json:"resource"`
	Effect      string   `json:"effect"`
	State       string   `json:"state"`
	Authority   string   `json:"authority"`
	SourceField string   `json:"source_field"`
	EvidenceIDs []string `json:"evidence_ids"`
}

// Location of a finding.
type Location struct {
	Path string `json:"path"`
	Line *int   `json:"line"`
}

// Finding is one rule / check hit.
type Finding struct {
	FindingID   string   `json:"finding_id"`
	RuleID      string   `json:"rule_id"`
	Category    string   `json:"category"`
	Severity    string   `json:"severity"`
	Confidence  float64  `json:"confidence"`
	Disposition string   `json:"disposition"`
	Location    Location `json:"location"`
	Excerpt     *string  `json:"excerpt"`
	EvidenceIDs []string `json:"evidence_ids"`
}

// Integrity summary.
type Integrity struct {
	FileCount        int   `json:"file_count"`
	TotalBytes       int64 `json:"total_bytes"`
	SymlinkEscape    bool  `json:"symlink_escape"`
	BinaryFiles      int   `json:"binary_files"`
	OverLimit        bool  `json:"over_limit"`
	FrontmatterValid bool  `json:"frontmatter_valid"`
}

// Engine identification.
type Engine struct {
	Name            string  `json:"name"`
	Version         string  `json:"version"`
	RulepackVersion int     `json:"rulepack_version"`
	RulepackSHA256  *string `json:"rulepack_sha256"`
}

// Admission is the signed verdict document.
type Admission struct {
	AdmissionID   string         `json:"admission_id"`
	SkillID       string         `json:"skill_id"`
	SkillName     string         `json:"skill_name"`
	SkillVersion  *string        `json:"skill_version"`
	Source        Source         `json:"source"`
	ContentHash   string         `json:"content_hash"`
	FileManifest  []FileEntry    `json:"file_manifest"`
	Verdict       string         `json:"verdict"`
	DecidedAt     string         `json:"decided_at"`
	Engine        Engine         `json:"engine"`
	DeclaredFacts []DeclaredFact `json:"declared_facts"`
	Findings      []Finding      `json:"findings"`
	Integrity     Integrity      `json:"integrity"`
	SkillCardRef  *string        `json:"skill_card_ref"`
	EvidenceIDs   []string       `json:"evidence_ids"`
	Signature     string         `json:"signature"`
}

// Evidence is the evidence.schema.json record backing findings and facts.
type Evidence struct {
	EvidenceID       string  `json:"evidence_id"`
	SourceType       string  `json:"source_type"`
	SourceLocator    string  `json:"source_locator"`
	SubjectRef       *string `json:"subject_ref"`
	ObservedAt       string  `json:"observed_at"`
	CollectedAt      string  `json:"collected_at"`
	CollectorID      string  `json:"collector_id"`
	ConnectorVersion string  `json:"connector_version"`
	ContentHash      string  `json:"content_hash"`
	RedactionProfile string  `json:"redaction_profile"`
	Classification   string  `json:"classification"`
	PayloadRef       *string `json:"payload_ref"`
	Signature        string  `json:"signature"`
	ExpiresAt        *string `json:"expires_at"`
}

// Options for Admit.
type Options struct {
	Source   Source
	Limits   Limits
	Now      time.Time
	Version  string // binary version for engine.version
	Key      *signing.Key
	Pack     *rulepack.Pack
	CardPath *string // recorded as skill_card_ref
}

// Result bundles the admission with its evidence and generated skill card.
type Result struct {
	Admission Admission
	Evidence  []Evidence
	SkillCard string
	// Frontmatter is exposed for callers (card / UI); not part of the contract.
	Frontmatter Frontmatter
}

// Admit analyses the skill directory at root.
func Admit(root string, opts Options) (*Result, error) {
	if opts.Pack == nil || opts.Key == nil {
		return nil, fmt.Errorf("admission: rulepack and signing key are required")
	}
	if opts.Limits == (Limits{}) {
		opts.Limits = DefaultLimits
	}
	if opts.Now.IsZero() {
		opts.Now = time.Now().UTC()
	}
	if opts.Source.TrustLevel == "" {
		opts.Source.TrustLevel = "unknown"
	}
	if opts.Source.Type == "" {
		opts.Source.Type = "local_dir"
	}
	if opts.Source.Locator == "" {
		opts.Source.Locator = root
	}
	w, err := walk(root, opts.Limits)
	if err != nil {
		return nil, err
	}
	b := &builder{opts: opts, w: w, analyzer: threat.New(opts.Pack), now: opts.Now.Format(time.RFC3339)}
	return b.run()
}

type builder struct {
	opts     Options
	w        *walked
	analyzer *threat.Analyzer
	now      string

	findings []Finding
	facts    map[string]*DeclaredFact
	evidence map[string]Evidence
	fm       Frontmatter
	binary   int
	stopped  bool
}

func (b *builder) run() (*Result, error) {
	b.facts = map[string]*DeclaredFact{}
	b.evidence = map[string]Evidence{}

	skillMD, hasSkillMD := b.w.contents["SKILL.md"]
	if !hasSkillMD {
		b.addHit(rawHit{"adm-skill-md-missing", catIntegrity, "critical", 1.0, dispQuarantine, "SKILL.md", 0, "SKILL.md not found", nil})
		b.fm = Frontmatter{Fields: map[string]string{}, Lists: map[string][]string{}, Nested: map[string]map[string]string{}}
	} else {
		b.fm = parseFrontmatter(string(skillMD))
		b.scanSkillMD(string(skillMD))
	}

	// per-file scans
	for _, f := range b.w.files {
		if b.stopped {
			break
		}
		data, scannable := b.w.contents[f.Path]
		if !scannable || threat.DetectType(data, f.Path, "") == "binary" || !utf8.Valid(data) {
			b.binary++
			if b.w.executable[f.Path] || isNativeExt(f.Path) {
				b.addHit(rawHit{"adm-binary-file", catSupplyChain, "medium", 0.8, dispDeclare, f.Path, 0, "native/executable artifact",
					&declaredCapability{"process", "process.exec", "path", f.Path}})
			} else {
				b.addHit(rawHit{"adm-binary-file", catSupplyChain, "low", 0.6, dispInfo, f.Path, 0, "binary file", nil})
			}
			continue
		}
		text := string(data)
		if f.Path == "SKILL.md" {
			continue // handled above
		}
		b.scanTextFile(f.Path, text)
	}

	// frontmatter-derived declarations
	if b.fm.Valid {
		for _, tool := range b.fm.allowedTools() {
			b.addHit(rawHit{"adm-allowed-tools", catCapability, "low", 1.0, dispDeclare, "SKILL.md", 1, "allowed-tools: " + tool,
				&declaredCapability{"tool", "tool.invoke", "tool", tool}})
		}
		if _, ok := b.fm.Nested["hooks"]; ok {
			b.addHit(rawHit{"adm-frontmatter-hooks", catCapability, "medium", 0.9, dispDeclare, "SKILL.md", 1, "hooks declared in frontmatter",
				&declaredCapability{"process", "process.exec", "tool", "frontmatter-hooks"}})
		} else if _, ok := b.fm.Fields["hooks"]; ok {
			b.addHit(rawHit{"adm-frontmatter-hooks", catCapability, "medium", 0.9, dispDeclare, "SKILL.md", 1, "hooks declared in frontmatter",
				&declaredCapability{"process", "process.exec", "tool", "frontmatter-hooks"}})
		}
		dir := baseName(b.opts.Source.Locator)
		if name := b.fm.Fields["name"]; name != "" && dir != "" && dir != "." && dir != name {
			b.addHit(rawHit{"adm-name-mismatch", catInfo, "info", 1.0, dispInfo, "SKILL.md", 1, "frontmatter name differs from directory", nil})
		}
	}

	for _, h := range checkShippedManifest(b.w.contents, b.w.files) {
		b.addHit(h)
	}

	return b.finish(hasSkillMD)
}

// checkShippedManifest verifies a candidate's detached per-file hash list
// (legacy skill.manifest.json). Mismatch is integrity failure → quarantine
// (design §4.1 / spec §3.6.4). An absent or empty files map is not a finding:
// shipping a manifest is optional.
func checkShippedManifest(contents map[string][]byte, files []FileEntry) []rawHit {
	raw, ok := contents["skill.manifest.json"]
	if !ok {
		return nil
	}
	var m struct {
		Files map[string]string `json:"files"`
	}
	if json.Unmarshal(raw, &m) != nil || len(m.Files) == 0 {
		return nil
	}
	have := make(map[string]string, len(files))
	for _, f := range files {
		have[f.Path] = f.SHA256
	}
	var hits []rawHit
	for p, want := range m.Files {
		got := have[p]
		if !strings.EqualFold(got, strings.TrimSpace(want)) {
			hits = append(hits, rawHit{"adm-manifest-mismatch", catIntegrity, "high", 1.0, dispQuarantine, p, 0, "sha256 does not match skill.manifest.json", nil})
		}
	}
	return hits
}

func isNativeExt(p string) bool {
	switch strings.ToLower(p[strings.LastIndex(p, "."):]) {
	case ".exe", ".dll", ".so", ".dylib", ".bin", ".elf":
		return true
	}
	return false
}

func (b *builder) scanSkillMD(text string) {
	if !b.fm.Present {
		b.addHit(rawHit{"adm-frontmatter-invalid", catInfo, "low", 0.7, dispInfo, "SKILL.md", 1, "no YAML frontmatter", nil})
	} else if !b.fm.Valid {
		b.addHit(rawHit{"adm-frontmatter-invalid", catInfo, "low", 0.7, dispInfo, "SKILL.md", 1, "unterminated frontmatter", nil})
	}
	for _, h := range checkHiddenComments(text) {
		b.addHit(h)
	}
	for _, h := range checkInvisible("SKILL.md", text) {
		b.addHit(h)
	}
	bodyStart := b.fm.EndLine + 1
	if !b.fm.Valid {
		bodyStart = 1
	}
	for _, h := range checkDeception(b.fm.Body, bodyStart) {
		b.addHit(h)
	}
	if b.fm.Valid {
		// frontmatter block is code-like: homoglyph check applies
		fmBlock := strings.SplitN(text, "\n---", 2)[0]
		for _, h := range checkHomoglyph("SKILL.md", fmBlock) {
			b.addHit(h)
		}
	}
	b.scanTextFile("SKILL.md", text)
}

// scanTextFile runs rulepack + built-in capability checks on one text file.
func (b *builder) scanTextFile(p, text string) {
	egressHits, hasEgress := checkEgress(p, text)
	res := b.analyzer.Analyze([]byte(text), p, "")
	for _, m := range res.Matches {
		if m.RuleID == "threat-net-webhook-exfil" || m.RuleID == "threat-net-reverse-shell" || m.RuleID == "threat-net-hardcoded-c2" {
			hasEgress = true
		}
	}
	lines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	fenced := fencedLines(lines)
	for _, m := range res.Matches {
		lineText := ""
		if m.Line >= 1 && m.Line <= len(lines) {
			lineText = lines[m.Line-1]
			if fenced[m.Line] && zoneOf(p) == zoneSkillMD {
				lineText = "> " + lineText // inside a fenced block: treat as example
			}
		}
		cat, disp, capab := classifyRuleHit(m.RuleID, p, m.Excerpt, lineText, hasEgress)
		b.addHit(rawHit{m.RuleID, cat, m.Severity, m.Confidence, disp, p, m.Line, m.Excerpt, capab})
	}
	for _, h := range egressHits {
		b.addHit(h)
	}
	for _, h := range checkCredentialPaths(p, text, hasEgress) {
		b.addHit(h)
	}
	for _, h := range checkPackageInstall(p, text) {
		b.addHit(h)
	}
	for _, h := range checkWritesOutside(p, text) {
		b.addHit(h)
	}
	if zoneOf(p) == zoneScripts || isCodeFile(p) {
		for _, h := range checkInvisible(p, text) {
			b.addHit(h)
		}
		for _, h := range checkHomoglyph(p, text) {
			b.addHit(h)
		}
	}
}

func (b *builder) addHit(h rawHit) {
	if b.stopped {
		return
	}
	if len(b.findings) >= b.opts.Limits.MaxFindings {
		b.w.overLimit = true
		b.stopped = true
		return
	}
	evID := b.addEvidence(h)
	var line *int
	if h.line > 0 {
		l := h.line
		line = &l
	}
	excerpt := truncateRunes(b.analyzer.Redact(h.excerpt), excerptMax)
	fid := "f-" + shortHash(h.ruleID+"|"+h.path+"|"+itoa(h.line)+"|"+h.excerpt)
	b.findings = append(b.findings, Finding{
		FindingID: fid, RuleID: h.ruleID, Category: h.category, Severity: h.severity, Confidence: h.confidence,
		Disposition: h.disp, Location: Location{Path: h.path, Line: line}, Excerpt: &excerpt, EvidenceIDs: []string{evID},
	})
	if h.disp == dispDeclare && h.cap != nil {
		key := h.cap.domain + "|" + h.cap.action + "|" + h.cap.resType + "|" + h.cap.resValue
		if f, ok := b.facts[key]; ok {
			f.EvidenceIDs = appendUnique(f.EvidenceIDs, evID)
			return
		}
		b.facts[key] = &DeclaredFact{
			Domain: h.cap.domain, Action: h.cap.action, Resource: Resource{h.cap.resType, h.cap.resValue},
			Effect: "allow", State: "declared", Authority: "skill_manifest",
			SourceField: sourceField(h), EvidenceIDs: []string{evID},
		}
	}
}

func sourceField(h rawHit) string {
	switch h.ruleID {
	case "adm-allowed-tools":
		return "frontmatter.allowed-tools"
	case "adm-frontmatter-hooks":
		return "frontmatter.hooks"
	}
	if h.line > 0 {
		return h.path + ":" + itoa(h.line)
	}
	return h.path
}

func (b *builder) addEvidence(h rawHit) string {
	id := "ev-" + shortHash(h.path+"|"+itoa(h.line)+"|"+h.ruleID)
	if _, ok := b.evidence[id]; ok {
		return id
	}
	sum := sha256.Sum256([]byte(h.excerpt))
	ev := Evidence{
		EvidenceID: id, SourceType: "manifest", SourceLocator: b.opts.Source.Locator + "/" + h.path,
		ObservedAt: b.now, CollectedAt: b.now, CollectorID: "agentshield-local", ConnectorVersion: b.opts.Version,
		ContentHash: hex.EncodeToString(sum[:]), RedactionProfile: "siq.redaction.v1", Classification: "internal",
	}
	ev.Signature = b.signDoc(ev)
	b.evidence[id] = ev
	return id
}

func (b *builder) finish(hasSkillMD bool) (*Result, error) {
	verdict := "admit"
	for _, f := range b.findings {
		if f.Disposition == dispQuarantine {
			verdict = "quarantine"
			break
		}
		if f.Disposition == dispDeclare {
			verdict = "admit_with_conditions"
		}
	}
	if b.w.overLimit || b.w.symlinkEscape || !hasSkillMD {
		verdict = "quarantine"
		if b.w.overLimit {
			b.forceHit(rawHit{"adm-over-limit", catIntegrity, "high", 1.0, dispQuarantine, ".", 0, "analysis resource limit exceeded", nil})
		}
		if b.w.symlinkEscape {
			b.forceHit(rawHit{"adm-symlink-escape", catIntegrity, "high", 1.0, dispQuarantine, ".", 0, "symlink resolves outside skill root", nil})
		}
	}

	facts := make([]DeclaredFact, 0, len(b.facts))
	if verdict == "admit_with_conditions" {
		for _, f := range b.facts {
			facts = append(facts, *f)
		}
		sort.Slice(facts, func(i, j int) bool {
			return facts[i].Domain+facts[i].Action+facts[i].Resource.Value < facts[j].Domain+facts[j].Action+facts[j].Resource.Value
		})
	}
	sort.Slice(b.findings, func(i, j int) bool {
		if b.findings[i].Location.Path != b.findings[j].Location.Path {
			return b.findings[i].Location.Path < b.findings[j].Location.Path
		}
		li, lj := 0, 0
		if b.findings[i].Location.Line != nil {
			li = *b.findings[i].Location.Line
		}
		if b.findings[j].Location.Line != nil {
			lj = *b.findings[j].Location.Line
		}
		if li != lj {
			return li < lj
		}
		return b.findings[i].RuleID < b.findings[j].RuleID
	})

	evIDs := make([]string, 0, len(b.evidence))
	evs := make([]Evidence, 0, len(b.evidence))
	for id, ev := range b.evidence {
		evIDs = append(evIDs, id)
		evs = append(evs, ev)
	}
	sort.Strings(evIDs)
	sort.Slice(evs, func(i, j int) bool { return evs[i].EvidenceID < evs[j].EvidenceID })
	if len(evIDs) == 0 {
		// a clean admit still needs one evidence: the manifest hash itself
		h := rawHit{"adm-manifest", catInfo, "info", 1.0, dispInfo, ".", 0, "", nil}
		id := b.addEvidence(h)
		evIDs = []string{id}
		evs = []Evidence{b.evidence[id]}
	}

	name := b.fm.Fields["name"]
	rawName := name
	if !skillName.MatchString(name) {
		name = sanitizeName(firstNonEmpty(name, baseName(b.opts.Source.Locator)))
		if rawName != "" {
			b.findings = append(b.findings, b.infoFinding("adm-name-invalid", "frontmatter name violates agentskills.io rules", evIDs[0]))
		}
	}
	ch := contentHash(b.w.files)
	var ver *string
	if v, ok := b.fm.Fields["version"]; ok && v != "" {
		ver = &v
	}
	adm := Admission{
		AdmissionID:  "adm-" + ch[:12],
		SkillID:      b.opts.Source.Type + ":" + name + "@" + ch[:12],
		SkillName:    name,
		SkillVersion: ver,
		Source:       b.opts.Source,
		ContentHash:  ch,
		FileManifest: b.w.files,
		Verdict:      verdict,
		DecidedAt:    b.now,
		Engine: Engine{Name: EngineName, Version: b.opts.Version, RulepackVersion: b.opts.Pack.Version,
			RulepackSHA256: strPtr(sha256Hex(rulepack.BuiltinBytes()))},
		DeclaredFacts: facts,
		Findings:      b.findings,
		Integrity: Integrity{FileCount: len(b.w.files), TotalBytes: b.w.totalBytes, SymlinkEscape: b.w.symlinkEscape,
			BinaryFiles: b.binary, OverLimit: b.w.overLimit, FrontmatterValid: b.fm.Valid},
		SkillCardRef: b.opts.CardPath,
		EvidenceIDs:  evIDs,
	}
	if adm.FileManifest == nil {
		adm.FileManifest = []FileEntry{}
	}
	if adm.Findings == nil {
		adm.Findings = []Finding{}
	}
	adm.Signature = b.signDoc(adm)
	card := renderCard(adm, b.fm)
	return &Result{Admission: adm, Evidence: evs, SkillCard: card, Frontmatter: b.fm}, nil
}

func (b *builder) forceHit(h rawHit) {
	b.stopped = false
	saved := b.opts.Limits.MaxFindings
	b.opts.Limits.MaxFindings = len(b.findings) + 1
	b.addHit(h)
	b.opts.Limits.MaxFindings = saved
	b.stopped = true
}

func (b *builder) infoFinding(ruleID, excerpt, evID string) Finding {
	e := excerpt
	return Finding{FindingID: "f-" + shortHash(ruleID+excerpt), RuleID: ruleID, Category: catInfo, Severity: "info", Confidence: 1.0,
		Disposition: dispInfo, Location: Location{Path: "SKILL.md"}, Excerpt: &e, EvidenceIDs: []string{evID}}
}

// signDoc signs the canonical JSON of v with its "signature" field removed.
func (b *builder) signDoc(v any) string {
	raw, _ := json.Marshal(v)
	dec, err := canon.Decode(raw)
	if err != nil {
		return ""
	}
	m := dec.(map[string]any)
	delete(m, "signature")
	sig, err := b.opts.Key.SignCanonical(m)
	if err != nil {
		return ""
	}
	return sig
}

// Verify checks an admission's signature with pub (hex Ed25519 over canonical
// JSON minus "signature").
func Verify(pub []byte, adm Admission) bool {
	raw, _ := json.Marshal(adm)
	dec, err := canon.Decode(raw)
	if err != nil {
		return false
	}
	m := dec.(map[string]any)
	sig, _ := m["signature"].(string)
	delete(m, "signature")
	return signing.VerifyCanonical(pub, m, sig)
}

// fencedLines marks 1-based line numbers that sit inside ``` / ~~~ fences.
func fencedLines(lines []string) map[int]bool {
	out := map[int]bool{}
	in := false
	for i, l := range lines {
		t := strings.TrimSpace(l)
		if strings.HasPrefix(t, "```") || strings.HasPrefix(t, "~~~") {
			in = !in
			continue
		}
		if in {
			out[i+1] = true
		}
	}
	return out
}

func shortHash(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])[:16]
}

func sha256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func truncateRunes(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}

func appendUnique(list []string, s string) []string {
	for _, x := range list {
		if x == s {
			return list
		}
	}
	return append(list, s)
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func baseName(p string) string {
	p = strings.TrimRight(p, "/\\")
	if i := strings.LastIndexAny(p, "/\\"); i >= 0 {
		return p[i+1:]
	}
	return p
}

func strPtr(s string) *string { return &s }

func itoa(i int) string { return fmt.Sprintf("%d", i) }

// Package state owns the local-mode state directory (dev-spec §2): paths,
// permissions, the decision-API bearer token, and the file-backed stores for
// admissions and grants. Files are only created or appended, never rewritten
// in place; grant status changes are new <grant_id>.<n>.json versions.
package state

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// DirEnv overrides the platform default state directory.
const DirEnv = product.EnvStateDir

// DefaultDir resolves the per-OS state directory (spec §2.1).
func DefaultDir() (string, error) {
	if d := product.Env(product.EnvStateDir, product.EnvStateDirOld); d != "" {
		return d, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	var newer, older string
	switch runtime.GOOS {
	case "windows":
		base := os.Getenv("LOCALAPPDATA")
		if base == "" {
			base = filepath.Join(home, "AppData", "Local")
		}
		newer = filepath.Join(base, product.Name)
		older = filepath.Join(base, product.LegacyName)
	case "darwin":
		newer = filepath.Join(home, "Library", "Application Support", product.Name)
		older = filepath.Join(home, "Library", "Application Support", product.LegacyName)
	default:
		base := os.Getenv("XDG_STATE_HOME")
		if base == "" {
			base = filepath.Join(home, ".local", "state")
		}
		newer = filepath.Join(base, product.Name)
		older = filepath.Join(base, product.LegacyName)
	}
	if _, err := os.Stat(newer); err == nil {
		return newer, nil
	}
	if _, err := os.Stat(older); err == nil {
		return older, nil
	}
	return newer, nil
}

// Config is <state>/config.json.
type Config struct {
	LinuxServiceHome  string `json:"linux_service_home,omitempty"`
	IntentEnforcement string `json:"intent_enforcement"`
	EnforcementMode   string `json:"enforcement_mode"`
	Port              int    `json:"port"`
	HoldChannel       string `json:"hold_channel"`
	// SessionIdleTTLSeconds: 0 → engine default (30m); -1 → disable idle expiry;
	// positive → seconds in [1, 86400] (DEV16-E).
	SessionIdleTTLSeconds int `json:"session_idle_ttl_seconds,omitempty"`
	// SkillAttributionEnforcement turns on the UX-007 skill-scoped grant gate.
	// Default off until platform adapters attach runtime skill claims; claims
	// are still resolved and recorded on receipts while off.
	SkillAttributionEnforcement bool `json:"skill_attribution_enforcement,omitempty"`
	// DesktopNotify turns on the daemon-side desktop notification dispatcher
	// (UX-008 background launcher layer). Default off; browser notifications
	// (ADR-032) are separate and client-side only.
	DesktopNotify bool `json:"desktop_notify,omitempty"`
	// DesktopNotifyCommand overrides the platform default notifier argv
	// (whitespace-split, executed without a shell). Empty uses the platform
	// default; unsupported platforms with no override stay silent.
	DesktopNotifyCommand string `json:"desktop_notify_command,omitempty"`
}

// Store is an opened state directory.
type Store struct {
	Dir               string
	runtimeGrantMu    sync.RWMutex
	runtimeGrantCheck func(*grant.Grant) error
}

// Open creates the directory tree with 0700 and returns the store.
func Open(dir string) (*Store, error) {
	if dir == "" {
		return nil, errors.New("state: directory required")
	}
	if err := RequireStateCompatibility(dir); err != nil {
		return nil, err
	}
	for _, sub := range append([]string{""}, coreStateDirs...) {
		if err := statefs.MkdirAll(filepath.Join(dir, sub), 0o700); err != nil {
			return nil, err
		}
	}
	return &Store{Dir: dir}, nil
}

// LoadConfig returns config.json or defaults (block / 47611 / console).
func (s *Store) LoadConfig() (Config, error) {
	raw, err := statefs.ReadFile(filepath.Join(s.Dir, "config.json"))
	if errors.Is(err, os.ErrNotExist) {
		return decodeConfig(nil)
	}
	if err != nil {
		return Config{}, err
	}
	return decodeConfig(raw)
}

func decodeConfig(raw []byte) (Config, error) {
	cfg := Config{IntentEnforcement: "optional", EnforcementMode: "block", Port: 47611, HoldChannel: "console"}
	if raw != nil {
		if err := json.Unmarshal(raw, &cfg); err != nil {
			return cfg, fmt.Errorf("state: config.json malformed: %w", err)
		}
	}
	if cfg.LinuxServiceHome != "" {
		home := cfg.LinuxServiceHome
		if !filepath.IsAbs(home) || filepath.Clean(home) != home || strings.IndexFunc(home, unicode.IsControl) >= 0 {
			return cfg, errors.New("state: invalid linux_service_home")
		}
		resolved, err := filepath.EvalSymlinks(home)
		info, statErr := os.Stat(home)
		if err != nil || resolved != home || statErr != nil || !info.IsDir() {
			return cfg, errors.New("state: linux_service_home requires an existing canonical directory")
		}
	}
	if cfg.IntentEnforcement != "optional" && cfg.IntentEnforcement != "required" {
		return cfg, fmt.Errorf("state: invalid intent_enforcement")
	}
	switch cfg.EnforcementMode {
	case "audit_only", "warn", "block":
	default:
		return cfg, fmt.Errorf("state: invalid enforcement_mode %q", cfg.EnforcementMode)
	}
	if cfg.Port <= 0 || cfg.Port > 65535 {
		return cfg, fmt.Errorf("state: invalid port %d", cfg.Port)
	}
	if cfg.SessionIdleTTLSeconds < -1 || cfg.SessionIdleTTLSeconds > 86400 {
		return cfg, fmt.Errorf("state: session_idle_ttl_seconds %d out of range [-1,86400]", cfg.SessionIdleTTLSeconds)
	}
	if cfg.DesktopNotifyCommand != "" {
		argv := strings.Fields(cfg.DesktopNotifyCommand)
		if len(argv) == 0 || strings.TrimSpace(argv[0]) == "" {
			return cfg, fmt.Errorf("state: invalid desktop_notify_command")
		}
	}
	return cfg, nil
}

// SessionIdleTTL maps config seconds to receipt.Engine Options (DEV16-E).
// 0 → use engine default (pass 0); -1 → disable (negative duration); else seconds.
func (c Config) SessionIdleTTL() time.Duration {
	switch {
	case c.SessionIdleTTLSeconds < 0:
		return -time.Second
	case c.SessionIdleTTLSeconds == 0:
		return 0
	default:
		return time.Duration(c.SessionIdleTTLSeconds) * time.Second
	}
}

// SaveConfig writes config.json (the one file that is rewritten; it holds no
// security decisions).
func (s *Store) SaveConfig(cfg Config) error {
	if err := RequireStateCompatibility(s.Dir); err != nil {
		return err
	}
	raw, _ := json.MarshalIndent(cfg, "", "  ")
	return statefs.WriteFile(filepath.Join(s.Dir, "config.json"), raw, 0o600)
}

// Token returns the decision-API bearer token, generating it once (0600).
func (s *Store) Token() (string, error) {
	if err := RequireStateCompatibility(s.Dir); err != nil {
		return "", err
	}
	p := filepath.Join(s.Dir, "token")
	if raw, err := statefs.ReadFile(p); err == nil {
		t := strings.TrimSpace(string(raw))
		if len(t) >= 32 {
			return t, nil
		}
		return "", errors.New("state: token file too short; refusing to use it")
	}
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	t := hex.EncodeToString(b)
	f, err := statefs.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if errors.Is(err, os.ErrExist) {
			return s.Token()
		}
		return "", err
	}
	if _, err := f.WriteString(t); err != nil {
		_ = f.Close()
		return "", err
	}
	return t, f.Close()
}

// --- admissions ---------------------------------------------------------------

// PutAdmission stores an admission plus its card and evidence. Fixed-id files
// are never overwritten: identical bytes are idempotent; same identity with
// later timestamps keeps the first write; a different identity is an error.
func (s *Store) PutAdmission(res *admission.Result) error {
	if err := RequireStateCompatibility(s.Dir); err != nil {
		return err
	}
	base := filepath.Join(s.Dir, "admissions", res.Admission.AdmissionID)
	cardPath := base + ".skill-card.md"
	if err := writeNewCompatible(cardPath, []byte(res.SkillCard), func([]byte) bool {
		return true
	}); err != nil {
		return err
	}
	raw, _ := json.MarshalIndent(res.Admission, "", "  ")
	if err := writeNewCompatible(base+".json", raw, func(existing []byte) bool {
		return sameAdmissionIdentity(existing, res.Admission)
	}); err != nil {
		return err
	}
	for _, ev := range res.Evidence {
		if err := s.PutEvidence(ev.EvidenceID, ev); err != nil {
			return err
		}
	}
	return nil
}

// GetAdmission loads one admission by id.
func (s *Store) GetAdmission(id string) (*admission.Admission, error) {
	if !safeID(id) {
		return nil, errors.New("state: invalid admission id")
	}
	raw, err := statefs.ReadFile(filepath.Join(s.Dir, "admissions", id+".json"))
	if err != nil {
		return nil, err
	}
	var a admission.Admission
	if err := json.Unmarshal(raw, &a); err != nil {
		return nil, err
	}
	return &a, nil
}

// SkillCard returns the markdown card written next to an admission.
func (s *Store) SkillCard(id string) (string, error) {
	if !safeID(id) {
		return "", errors.New("state: invalid admission id")
	}
	raw, err := statefs.ReadFile(filepath.Join(s.Dir, "admissions", id+".skill-card.md"))
	if err != nil {
		return "", err
	}
	return string(raw), nil
}

// ListAdmissions returns all admissions (newest decided_at first).
func (s *Store) ListAdmissions() ([]admission.Admission, error) {
	entries, err := statefs.ReadDir(filepath.Join(s.Dir, "admissions"))
	if err != nil {
		return nil, err
	}
	var out []admission.Admission
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		raw, err := statefs.ReadFile(filepath.Join(s.Dir, "admissions", e.Name()))
		if err != nil {
			return nil, err
		}
		var a admission.Admission
		if err := json.Unmarshal(raw, &a); err != nil || a.AdmissionID != strings.TrimSuffix(e.Name(), ".json") {
			return nil, errors.New("state: malformed admission document")
		}
		out = append(out, a)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].DecidedAt > out[j].DecidedAt })
	return out, nil
}

// --- grants -------------------------------------------------------------------

// PutGrant appends a new version file for the grant: <grant_id>.<n>.json.
// Prefer PutGrantCAS for read-modify-write transitions that must not double-succeed.
func (s *Store) PutGrant(g grant.Grant) error {
	if !safeID(g.GrantID) {
		return errors.New("state: invalid grant id")
	}
	return s.PutVersioned("grants", g.GrantID, g)
}

// PutGrantCAS publishes the next grant version only when expected matches the head seq.
func (s *Store) PutGrantCAS(g grant.Grant, expected int) (int, error) {
	if !safeID(g.GrantID) {
		return -1, errors.New("state: invalid grant id")
	}
	return s.PutVersionedCAS("grants", g.GrantID, expected, g)
}

// GetGrant returns the latest version of a grant.
func (s *Store) GetGrant(id string) (*grant.Grant, error) {
	g, _, err := s.GetGrantWithSeq(id)
	return g, err
}

// GetGrantWithSeq returns the latest grant and its disk version number.
func (s *Store) GetGrantWithSeq(id string) (*grant.Grant, int, error) {
	if !safeID(id) {
		return nil, -1, errors.New("state: invalid grant id")
	}
	seq, raw, err := s.LatestSeq("grants", id)
	if err != nil {
		return nil, -1, err
	}
	if err := s.checkGrantCommit(id, seq); err != nil {
		return nil, -1, err
	}
	if seq < 0 {
		return nil, -1, os.ErrNotExist
	}
	var g grant.Grant
	if err := json.Unmarshal(raw, &g); err != nil {
		return nil, -1, fmt.Errorf("state: malformed grant version: %w", err)
	}
	if g.GrantID != id {
		return nil, -1, errors.New("state: grant identity does not match version filename")
	}
	return &g, seq, nil
}

// PutChallenge publishes a new approval challenge (expected head 0 for fresh ids).
func (s *Store) PutChallenge(ch grant.ApprovalChallenge) error {
	if !safeID(ch.ChallengeID) {
		return errors.New("state: invalid challenge id")
	}
	_, err := s.PutVersionedCAS("challenges", ch.ChallengeID, -1, ch)
	return err
}

// PutChallengeCAS updates a challenge when expected matches the head seq.
func (s *Store) PutChallengeCAS(ch grant.ApprovalChallenge, expected int) (int, error) {
	if !safeID(ch.ChallengeID) {
		return -1, errors.New("state: invalid challenge id")
	}
	return s.PutVersionedCAS("challenges", ch.ChallengeID, expected, ch)
}

// GetChallengeWithSeq loads the latest approval challenge document.
func (s *Store) GetChallengeWithSeq(id string) (*grant.ApprovalChallenge, int, error) {
	if !safeID(id) {
		return nil, -1, errors.New("state: invalid challenge id")
	}
	seq, raw, err := s.LatestSeq("challenges", id)
	if err != nil {
		return nil, -1, err
	}
	if seq < 0 {
		return nil, -1, os.ErrNotExist
	}
	var ch grant.ApprovalChallenge
	if err := json.Unmarshal(raw, &ch); err != nil {
		return nil, -1, fmt.Errorf("state: malformed challenge version: %w", err)
	}
	if ch.ChallengeID != id {
		return nil, -1, errors.New("state: challenge identity does not match version filename")
	}
	return &ch, seq, nil
}

// ListGrants returns the latest version of every grant.
func (s *Store) ListGrants() ([]grant.Grant, error) {
	entries, err := statefs.ReadDir(filepath.Join(s.Dir, "grants"))
	if err != nil {
		return nil, err
	}
	latest := map[string]int{}
	files := map[string]string{}
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".json") {
			continue
		}
		stem := strings.TrimSuffix(name, ".json")
		dot := strings.LastIndex(stem, ".")
		if dot < 0 {
			continue
		}
		n, err := strconv.Atoi(stem[dot+1:])
		if err != nil {
			continue
		}
		id := stem[:dot]
		if cur, ok := latest[id]; !ok || n > cur {
			latest[id] = n
			files[id] = filepath.Join(s.Dir, "grants", name)
		}
	}
	var out []grant.Grant
	for id, p := range files {
		if err := s.checkGrantCommit(id, latest[id]); err != nil {
			return nil, err
		}
		raw, err := statefs.ReadFile(p)
		if err != nil {
			return nil, err
		}
		var g grant.Grant
		if err := json.Unmarshal(raw, &g); err != nil {
			return nil, fmt.Errorf("state: malformed grant version: %w", err)
		}
		if g.GrantID != id {
			return nil, errors.New("state: grant identity does not match version filename")
		}
		out = append(out, g)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out, nil
}

// ActiveGrant is the receipt.GrantLookup: newest deployed/effective grant for
// (platform, agent).
func (s *Store) ActiveGrant(platform, agentID string) *grant.Grant {
	all, err := s.ListGrants()
	if err != nil {
		return nil
	}
	for i := range all {
		g := all[i]
		if g.Platform == platform && g.Subject.ID == agentID && (g.Status == "deployed" || g.Status == "effective") {
			return &g
		}
	}
	return nil
}

// GrantByID returns the newest stored version of one grant whatever its
// state, or nil. Verification callers re-check status, lifetime and digests.
func (s *Store) GrantByID(id string) *grant.Grant {
	if !safeID(id) {
		return nil
	}
	all, err := s.ListGrants()
	if err != nil {
		return nil
	}
	for i := range all {
		if all[i].GrantID == id {
			return &all[i]
		}
	}
	return nil
}

// BaselineGrant returns the newest deployed/effective grant without a skill
// scope for (platform, agent): the second leg of the SEC permission
// intersection (N05/R01). nil means no baseline exists.
func (s *Store) BaselineGrant(platform, agentID string) *grant.Grant {
	all, err := s.ListGrants()
	if err != nil {
		return nil
	}
	for i := range all {
		g := all[i]
		if g.Platform == platform && g.Subject.ID == agentID && g.Skill == nil && (g.Status == "deployed" || g.Status == "effective") {
			return &g
		}
	}
	return nil
}

// SkillAttribution is the receipt.SkillAttributionLookup: it resolves a
// runtime skill claim against approved grant records (deployed/effective,
// lifetime valid) for the same platform and agent. A metadata match cannot
// attest which Skill caused a tool execution: identifiers and hashes can be
// copied by the caller. Until a trusted execution binding exists, even an
// exact match remains unknown and cannot satisfy the verified-skill gate.
func (s *Store) SkillAttribution(platform, sessionID, agentID string, claim *receipt.SkillClaim) *receipt.SkillAttribution {
	_ = sessionID // attribution is per platform+agent trusted state, not per session
	if claim == nil || claim.SkillID == "" {
		return nil
	}
	all, err := s.ListGrants()
	if err != nil {
		return nil
	}
	now := time.Now()
	skillKnown := false
	for i := range all {
		g := all[i]
		if g.Platform != platform || g.Subject.ID != agentID || g.Skill == nil {
			continue
		}
		if g.Status != "deployed" && g.Status != "effective" {
			continue
		}
		if grant.ValidateLifetime(g, now) != nil {
			continue
		}
		if g.Skill.SkillID != claim.SkillID {
			continue
		}
		skillKnown = true
		if claim.ContentHash == "" || claim.ContentHash != g.Skill.ContentHash {
			continue
		}
		if g.Skill.Version != nil && claim.Version != *g.Skill.Version {
			continue
		}
		a := receipt.SkillAttribution{
			SkillID:     g.Skill.SkillID,
			ContentHash: g.Skill.ContentHash,
			Status:      receipt.SkillAttributionUnknown,
		}
		if g.Skill.Version != nil {
			a.Version = *g.Skill.Version
		}
		return &a
	}
	if skillKnown {
		return &receipt.SkillAttribution{SkillID: claim.SkillID, Status: receipt.SkillAttributionMismatch}
	}
	return nil
}

// PutDesiredPolicy stores the derived policy as policies/<id>.v<version>.json.
// The file is Sync'd before close so a successful return means durable bytes.
func (s *Store) PutDesiredPolicy(dp grant.DesiredPolicy) error {
	if err := RequireStateCompatibility(s.Dir); err != nil {
		return err
	}
	id, _ := dp["policy_id"].(string)
	if !safeID(id) {
		return errors.New("state: invalid policy id")
	}
	v := 1
	switch t := dp["version"].(type) {
	case int:
		v = t
	case float64:
		v = int(t)
	}
	raw, err := json.MarshalIndent(dp, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	dir := filepath.Join(s.Dir, "policies")
	if err := statefs.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	return publishCommitFile(filepath.Join(dir, fmt.Sprintf("%s.v%d.json", id, v)), raw)
}

// writeDurable creates path exclusively, Syncs, then closes. Identical content
// at an existing path is treated as idempotent success (same as writeNew).
func writeDurable(path string, data []byte) error {
	f, err := statefs.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		existing, readErr := statefs.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if bytes.Equal(existing, data) {
			return nil
		}
		return fmt.Errorf("%w: %s", ErrConflict, filepath.Base(path))
	}
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		_ = statefs.Remove(path)
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		_ = statefs.Remove(path)
		return err
	}
	if err := f.Close(); err != nil {
		_ = statefs.Remove(path)
		return err
	}
	return nil
}

// PutEvidence writes a new evidence file (0600). A later write with the same
// evidence_id, content_hash and source_locator is idempotent; a different
// identity at that path is an error and does not replace the file.
func (s *Store) PutEvidence(id string, doc any) error {
	if err := RequireStateCompatibility(s.Dir); err != nil {
		return err
	}
	if !safeID(id) {
		return errors.New("state: invalid evidence id")
	}
	raw, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	return writeNewCompatible(filepath.Join(s.Dir, "evidence", id+".json"), raw, func(existing []byte) bool {
		return sameJSONIdentity(existing, raw, "evidence_id", "content_hash", "source_locator")
	})
}

// GetEvidence reads one previously written evidence document. Evidence files
// are immutable, so this is a read-only view: it exists so a projection can be
// rebuilt after a restart without replaying anything.
//
// A missing file returns (nil, nil) so callers can tell "never recorded" apart
// from "recorded but unreadable". Unreadable must never be silently treated as
// absent: a caller that conflates the two would report an execution as never
// having happened.
func (s *Store) GetEvidence(id string) (map[string]any, error) {
	if !safeID(id) {
		return nil, errors.New("state: invalid evidence id")
	}
	raw, err := statefs.ReadFile(filepath.Join(s.Dir, "evidence", id+".json"))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, err
	}
	return doc, nil
}

// ErrConflict means an O_EXCL target exists with bytes that are not identical.
var ErrConflict = errors.New("state: immutable path exists with different content")

func writeNew(path string, data []byte) error {
	f, err := statefs.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		existing, readErr := statefs.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if bytes.Equal(existing, data) {
			return nil
		}
		return fmt.Errorf("%w: %s", ErrConflict, filepath.Base(path))
	}
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

func writeNewCompatible(path string, data []byte, sameIdentity func(existing []byte) bool) error {
	err := writeNew(path, data)
	if err == nil || !errors.Is(err, ErrConflict) {
		return err
	}
	existing, readErr := statefs.ReadFile(path)
	if readErr != nil {
		return readErr
	}
	if sameIdentity != nil && sameIdentity(existing) {
		return nil
	}
	return err
}

func sameAdmissionIdentity(existing []byte, a admission.Admission) bool {
	var old admission.Admission
	if json.Unmarshal(existing, &old) != nil {
		return false
	}
	return old.AdmissionID == a.AdmissionID && old.ContentHash == a.ContentHash
}

func sameJSONIdentity(existing, neu []byte, keys ...string) bool {
	var oldDoc, newDoc map[string]any
	if json.Unmarshal(existing, &oldDoc) != nil || json.Unmarshal(neu, &newDoc) != nil {
		return false
	}
	for _, key := range keys {
		oldVal, oldOK := oldDoc[key]
		newVal, newOK := newDoc[key]
		if !oldOK || !newOK {
			return false
		}
		left, right := fmt.Sprint(oldVal), fmt.Sprint(newVal)
		if left == "" || left != right {
			return false
		}
	}
	return true
}

func safeID(id string) bool {
	if id == "" || len(id) > 128 {
		return false
	}
	for _, r := range id {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_') {
			return false
		}
	}
	return true
}

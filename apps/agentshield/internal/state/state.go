// Package state owns the local-mode state directory (dev-spec §2): paths,
// permissions, the decision-API bearer token, and the file-backed stores for
// admissions and grants. Files are only created or appended, never rewritten
// in place; grant status changes are new <grant_id>.<n>.json versions.
package state

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
)

// DirEnv overrides the platform default state directory.
const DirEnv = "AGENTSHIELD_STATE_DIR"

// DefaultDir resolves the per-OS state directory (spec §2.1).
func DefaultDir() (string, error) {
	if d := os.Getenv(DirEnv); d != "" {
		return d, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	switch runtime.GOOS {
	case "windows":
		if d := os.Getenv("LOCALAPPDATA"); d != "" {
			return filepath.Join(d, "agentshield"), nil
		}
		return filepath.Join(home, "AppData", "Local", "agentshield"), nil
	case "darwin":
		return filepath.Join(home, "Library", "Application Support", "agentshield"), nil
	default:
		if d := os.Getenv("XDG_STATE_HOME"); d != "" {
			return filepath.Join(d, "agentshield"), nil
		}
		return filepath.Join(home, ".local", "state", "agentshield"), nil
	}
}

// Config is <state>/config.json.
type Config struct {
	EnforcementMode string `json:"enforcement_mode"`
	Port            int    `json:"port"`
	HoldChannel     string `json:"hold_channel"`
}

// Store is an opened state directory.
type Store struct{ Dir string }

// Open creates the directory tree with 0700 and returns the store.
func Open(dir string) (*Store, error) {
	if dir == "" {
		return nil, errors.New("state: directory required")
	}
	for _, sub := range []string{"", "keys", "admissions", "grants", "policies", "evidence", "receipts", "inventory", "backups", "logs"} {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o700); err != nil {
			return nil, err
		}
	}
	return &Store{Dir: dir}, nil
}

// LoadConfig returns config.json or defaults (block / 47611 / console).
func (s *Store) LoadConfig() (Config, error) {
	cfg := Config{EnforcementMode: "block", Port: 47611, HoldChannel: "console"}
	raw, err := os.ReadFile(filepath.Join(s.Dir, "config.json"))
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return cfg, err
	}
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return cfg, fmt.Errorf("state: config.json malformed: %w", err)
	}
	switch cfg.EnforcementMode {
	case "audit_only", "warn", "block":
	default:
		return cfg, fmt.Errorf("state: invalid enforcement_mode %q", cfg.EnforcementMode)
	}
	if cfg.Port <= 0 || cfg.Port > 65535 {
		return cfg, fmt.Errorf("state: invalid port %d", cfg.Port)
	}
	return cfg, nil
}

// SaveConfig writes config.json (the one file that is rewritten; it holds no
// security decisions).
func (s *Store) SaveConfig(cfg Config) error {
	raw, _ := json.MarshalIndent(cfg, "", "  ")
	return os.WriteFile(filepath.Join(s.Dir, "config.json"), raw, 0o600)
}

// Token returns the decision-API bearer token, generating it once (0600).
func (s *Store) Token() (string, error) {
	p := filepath.Join(s.Dir, "token")
	if raw, err := os.ReadFile(p); err == nil {
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
	f, err := os.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
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

// PutAdmission stores an admission (new file; identical id = identical content
// hash, so overwriting is a no-op by construction) plus its card and evidence.
func (s *Store) PutAdmission(res *admission.Result) error {
	base := filepath.Join(s.Dir, "admissions", res.Admission.AdmissionID)
	cardPath := base + ".skill-card.md"
	res.Admission.SkillCardRef = &cardPath
	if err := writeNew(cardPath, []byte(res.SkillCard)); err != nil {
		return err
	}
	raw, _ := json.MarshalIndent(res.Admission, "", "  ")
	if err := writeNew(base+".json", raw); err != nil {
		return err
	}
	for _, ev := range res.Evidence {
		evRaw, _ := json.Marshal(ev)
		if err := writeNew(filepath.Join(s.Dir, "evidence", ev.EvidenceID+".json"), evRaw); err != nil {
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
	raw, err := os.ReadFile(filepath.Join(s.Dir, "admissions", id+".json"))
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
	raw, err := os.ReadFile(filepath.Join(s.Dir, "admissions", id+".skill-card.md"))
	if err != nil {
		return "", err
	}
	return string(raw), nil
}

// ListAdmissions returns all admissions (newest decided_at first).
func (s *Store) ListAdmissions() ([]admission.Admission, error) {
	entries, err := os.ReadDir(filepath.Join(s.Dir, "admissions"))
	if err != nil {
		return nil, err
	}
	var out []admission.Admission
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(s.Dir, "admissions", e.Name()))
		if err != nil {
			return nil, err
		}
		var a admission.Admission
		if json.Unmarshal(raw, &a) == nil {
			out = append(out, a)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].DecidedAt > out[j].DecidedAt })
	return out, nil
}

// --- grants -------------------------------------------------------------------

// PutGrant appends a new version file for the grant: <grant_id>.<n>.json.
func (s *Store) PutGrant(g grant.Grant) error {
	if !safeID(g.GrantID) {
		return errors.New("state: invalid grant id")
	}
	n := 0
	for {
		p := filepath.Join(s.Dir, "grants", fmt.Sprintf("%s.%d.json", g.GrantID, n))
		if _, err := os.Stat(p); errors.Is(err, os.ErrNotExist) {
			raw, _ := json.MarshalIndent(g, "", "  ")
			return writeNew(p, raw)
		}
		n++
		if n > 10000 {
			return errors.New("state: too many grant versions")
		}
	}
}

// GetGrant returns the latest version of a grant.
func (s *Store) GetGrant(id string) (*grant.Grant, error) {
	all, err := s.ListGrants()
	if err != nil {
		return nil, err
	}
	for i := range all {
		if all[i].GrantID == id {
			return &all[i], nil
		}
	}
	return nil, os.ErrNotExist
}

// ListGrants returns the latest version of every grant.
func (s *Store) ListGrants() ([]grant.Grant, error) {
	entries, err := os.ReadDir(filepath.Join(s.Dir, "grants"))
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
	for _, p := range files {
		raw, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		var g grant.Grant
		if json.Unmarshal(raw, &g) == nil {
			out = append(out, g)
		}
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

// PutDesiredPolicy stores the derived policy as policies/<id>.v<version>.json.
func (s *Store) PutDesiredPolicy(dp grant.DesiredPolicy) error {
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
	raw, _ := json.MarshalIndent(dp, "", "  ")
	return writeNew(filepath.Join(s.Dir, "policies", fmt.Sprintf("%s.v%d.json", id, v)), raw)
}

// PutEvidence writes a new evidence file (0600). Existing ids are left as-is.
func (s *Store) PutEvidence(id string, doc any) error {
	if !safeID(id) {
		return errors.New("state: invalid evidence id")
	}
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	return writeNew(filepath.Join(s.Dir, "evidence", id+".json"), raw)
}

func writeNew(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		return nil // identical id ⇒ identical content by construction
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

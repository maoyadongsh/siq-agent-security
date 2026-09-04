package rulepack

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

const pythonBuiltin = "../../../control-api/app/data/threat_rules.v1.json"

// The embedded copy must stay byte-identical to the control-plane copy: both
// implementations are contractually bound to the same signed document.
func TestEmbeddedPackMatchesControlPlaneCopy(t *testing.T) {
	py, err := os.ReadFile(pythonBuiltin)
	if err != nil {
		t.Skipf("control-api rulepack not available: %v", err)
	}
	if !bytes.Equal(py, BuiltinBytes()) {
		t.Fatal("apps/agentshield/internal/rulepack/data/threat_rules.v1.json drifted from apps/control-api/app/data/threat_rules.v1.json")
	}
}

func TestBuiltinParsesAndEveryPatternIsRE2(t *testing.T) {
	p, err := Builtin()
	if err != nil {
		t.Fatal(err)
	}
	if p.Version < 1 || len(p.Rules) == 0 {
		t.Fatalf("unexpected pack: version=%d rules=%d", p.Version, len(p.Rules))
	}
	for _, r := range p.Rules {
		if len(r.Patterns) == 0 {
			t.Fatalf("rule %s has no compiled patterns", r.ID)
		}
	}
	if len(p.Redactions) == 0 {
		t.Fatal("redactions must not be empty")
	}
}

func TestParseRejectsMalformedPacks(t *testing.T) {
	cases := map[string]string{
		"not object":         `[]`,
		"version float":      `{"version":1.0,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`,
		"version zero":       `{"version":0,"rules":[]}`,
		"empty rules":        `{"version":1,"rules":[]}`,
		"missing field":      `{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","patterns":["x"]}]}`,
		"bad severity":       `{"version":1,"rules":[{"rule_id":"a","severity":"nope","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`,
		"confidence > 1":     `{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":1.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`,
		"duplicate id":       `{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]},{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["y"]}]}`,
		"uncompilable regex": `{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["(?<=x)y"]}]}`,
		"empty patterns":     `{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":[]}]}`,
		"redaction empty":    `{"version":1,"redaction_patterns":[],"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`,
		"redaction no repl":  `{"version":1,"redaction_patterns":[{"pattern":"x"}],"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`,
	}
	for name, doc := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse([]byte(doc)); err == nil || !ErrRejected(err) {
				t.Fatalf("expected rejection, got %v", err)
			}
		})
	}
}

func TestParseOmittedRedactionsFallBackToDefaults(t *testing.T) {
	p, err := Parse([]byte(`{"version":1,"rules":[{"rule_id":"a","severity":"high","confidence":0.5,"description":"d","impact":"i","remediation":"r","patterns":["x"]}]}`))
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Redactions) != len(defaultRedactions) {
		t.Fatalf("expected default redactions, got %d", len(p.Redactions))
	}
}

func signPack(t *testing.T, dir, name string, doc []byte, priv ed25519.PrivateKey) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, doc, 0o600); err != nil {
		t.Fatal(err)
	}
	v, err := canon.Decode(doc)
	if err != nil {
		t.Fatal(err)
	}
	msg, _ := canon.Marshal(v)
	sig := ed25519.Sign(priv, msg)
	if err := os.WriteFile(path+".sig", []byte(base64.StdEncoding.EncodeToString(sig)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func externalDoc(version string) []byte {
	return []byte(`{"version":` + version + `,"rules":[{"rule_id":"ext-only","severity":"high","confidence":0.9,"description":"d","impact":"i","remediation":"r","patterns":["\\bEXTERNAL_MARKER\\b"]}]}`)
}

func TestLoadAcceptsSignedNewerExternalPack(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	builtin, _ := Builtin()
	dir := t.TempDir()
	path := signPack(t, dir, "ext.json", externalDoc(itoa(builtin.Version+1)), priv)
	t.Setenv(PathEnv, path)
	var warnings []string
	p, err := Load(pub, func(s string) { warnings = append(warnings, s) })
	if err != nil {
		t.Fatal(err)
	}
	if p.Source != path || len(p.Rules) != 1 || p.Rules[0].ID != "ext-only" {
		t.Fatalf("external pack not adopted: source=%s warnings=%v", p.Source, warnings)
	}
}

func TestLoadFailsClosedToBuiltin(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	_, otherPriv, _ := ed25519.GenerateKey(rand.Reader)
	builtin, _ := Builtin()
	newer := itoa(builtin.Version + 1)

	cases := []struct {
		name  string
		setup func(dir string) string
		key   ed25519.PublicKey
		want  string
	}{
		{"missing sig", func(dir string) string {
			path := filepath.Join(dir, "ext.json")
			_ = os.WriteFile(path, externalDoc(newer), 0o600)
			return path
		}, pub, "missing signature"},
		{"wrong key", func(dir string) string {
			return signPack(t, dir, "ext.json", externalDoc(newer), otherPriv)
		}, pub, "verification failed"},
		{"tampered after signing", func(dir string) string {
			path := signPack(t, dir, "ext.json", externalDoc(newer), priv)
			_ = os.WriteFile(path, []byte(strings.Replace(string(externalDoc(newer)), "EXTERNAL_MARKER", "TAMPERED", 1)), 0o600)
			return path
		}, pub, "verification failed"},
		{"no verification key", func(dir string) string {
			return signPack(t, dir, "ext.json", externalDoc(newer), priv)
		}, nil, "no verification key"},
		{"unparsable", func(dir string) string {
			return signPack(t, dir, "ext.json", []byte(`{"version":`+newer+`,"rules":[]}`), priv)
		}, pub, "rejected"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dir := t.TempDir()
			t.Setenv(PathEnv, c.setup(dir))
			var warnings []string
			p, err := Load(c.key, func(s string) { warnings = append(warnings, s) })
			if err != nil {
				t.Fatal(err)
			}
			if p.Source != "builtin" {
				t.Fatalf("must fall back to builtin, got %s", p.Source)
			}
			if len(warnings) != 1 || !strings.Contains(warnings[0], c.want) {
				t.Fatalf("expected one warning containing %q, got %v", c.want, warnings)
			}
			for _, w := range warnings {
				if strings.Contains(w, "EXTERNAL_MARKER") {
					t.Fatal("warning leaked rule content")
				}
			}
		})
	}
}

func itoa(i int) string { return strconv.Itoa(i) }

func TestDowngradeRuleMatchesPython(t *testing.T) {
	builtin := &Pack{Version: 3}
	if !isDowngrade(&Pack{Version: 2}, builtin) {
		t.Fatal("older external pack must be a downgrade")
	}
	if isDowngrade(&Pack{Version: 3}, builtin) {
		t.Fatal("equal version is accepted (Python: external < builtin is the only rejection)")
	}
	if isDowngrade(&Pack{Version: 4}, builtin) {
		t.Fatal("newer pack is not a downgrade")
	}
}

func TestLoadAcceptsEqualVersionExternalPack(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	builtin, _ := Builtin()
	path := signPack(t, t.TempDir(), "ext.json", externalDoc(itoa(builtin.Version)), priv)
	t.Setenv(PathEnv, path)
	p, err := Load(pub, nil)
	if err != nil {
		t.Fatal(err)
	}
	if p.Source != path {
		t.Fatalf("equal-version signed pack must be accepted, got %s", p.Source)
	}
}

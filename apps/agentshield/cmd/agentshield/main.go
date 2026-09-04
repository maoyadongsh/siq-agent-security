// agentshield is the local AgentShield binary (ADR-011). W1 scope: rulepack
// loading, static scan, local signing identity. inventory / admit / grant /
// serve land in later increments.
package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/threat"
)

// Version is set by the release build (-ldflags "-X main.Version=...").
var Version = "0.0.0-dev"

// RulepackPubEnv carries the base64 Ed25519 public key that external rule
// packs must be signed with. Unset means only the built-in pack is trusted.
const RulepackPubEnv = "AGENTSHIELD_RULEPACK_PUBKEY"

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "version":
		fmt.Printf("agentshield %s (%s/%s)\n", Version, runtime.GOOS, runtime.GOARCH)
	case "rulepack":
		err = cmdRulepack()
	case "scan":
		err = cmdScan(os.Args[2:])
	case "pubkey":
		err = cmdPubkey()
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "agentshield:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `usage:
  agentshield version
  agentshield rulepack            # effective rule pack summary (JSON)
  agentshield scan <file>...      # static threat scan, one JSON result per line
  agentshield pubkey              # local signing public key (base64)`)
}

func stateDir() (string, error) {
	if d := os.Getenv("AGENTSHIELD_STATE_DIR"); d != "" {
		return d, nil
	}
	switch runtime.GOOS {
	case "windows":
		if d := os.Getenv("LOCALAPPDATA"); d != "" {
			return filepath.Join(d, "agentshield"), nil
		}
	case "darwin":
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, "Library", "Application Support", "agentshield"), nil
	default:
		if d := os.Getenv("XDG_STATE_HOME"); d != "" {
			return filepath.Join(d, "agentshield"), nil
		}
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, ".local", "state", "agentshield"), nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".agentshield"), nil
}

func rulepackPub() (ed25519.PublicKey, error) {
	b64 := os.Getenv(RulepackPubEnv)
	if b64 == "" {
		return nil, nil
	}
	raw, err := base64.StdEncoding.Strict().DecodeString(b64)
	if err != nil || len(raw) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("%s is not a valid base64 Ed25519 public key", RulepackPubEnv)
	}
	return ed25519.PublicKey(raw), nil
}

func loadPack() (*rulepack.Pack, error) {
	pub, err := rulepackPub()
	if err != nil {
		return nil, err
	}
	return rulepack.Load(pub, func(reason string) { fmt.Fprintln(os.Stderr, "agentshield:", reason) })
}

func cmdRulepack() error {
	p, err := loadPack()
	if err != nil {
		return err
	}
	ids := make([]string, 0, len(p.Rules))
	for _, r := range p.Rules {
		ids = append(ids, r.ID)
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{
		"version":    p.Version,
		"source":     p.Source,
		"rule_count": len(p.Rules),
		"rule_ids":   ids,
		"redactions": len(p.Redactions),
		"engine":     threat.New(p).Version(),
	})
}

func cmdScan(paths []string) error {
	if len(paths) == 0 {
		return fmt.Errorf("scan: at least one file required")
	}
	p, err := loadPack()
	if err != nil {
		return err
	}
	a := threat.New(p)
	enc := json.NewEncoder(os.Stdout)
	for _, path := range paths {
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		res := a.Analyze(content, filepath.Base(path), "")
		if err := enc.Encode(map[string]any{"path": path, "engine": a.Version(), "result": res}); err != nil {
			return err
		}
	}
	return nil
}

func cmdPubkey() error {
	dir, err := stateDir()
	if err != nil {
		return err
	}
	k, err := signing.Load(dir)
	if err != nil {
		return err
	}
	fmt.Println(k.PublicBase64())
	return nil
}

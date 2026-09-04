// agentshield is the local AgentShield binary (ADR-011). W1 scope: rulepack
// loading, static scan, local signing identity. inventory / admit / grant /
// serve land in later increments.
package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/receipt"
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
	case "admit":
		err = cmdAdmit(os.Args[2:])
	case "pubkey":
		err = cmdPubkey()
	case "verify":
		err = cmdVerify(os.Args[2:])
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
  agentshield admit <skill-dir> [--trust trusted|community|unknown] [--out <dir>] [--card]
                                  # pre-install verdict (JSON); exit 3 = quarantine
  agentshield pubkey              # local signing public key (base64)
  agentshield verify [--chain local]
                                  # recompute the receipt hash chain and signatures; exit 4 on first break`)
}

func cmdVerify(args []string) error {
	fs := flag.NewFlagSet("verify", flag.ContinueOnError)
	chainID := fs.String("chain", "local", "chain id under <state>/receipts/")
	if err := fs.Parse(args); err != nil {
		return err
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	chain, err := receipt.OpenChain(dir, *chainID, key)
	if err != nil {
		return err
	}
	all, err := chain.Read()
	if err != nil {
		return err
	}
	if verr := receipt.Verify(all, key.Public()); verr != nil {
		fmt.Fprintln(os.Stderr, "agentshield:", verr)
		os.Exit(4)
	}
	seq, head := chain.Head()
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"chain": *chainID, "receipts": len(all), "head_seq": seq, "head_hash": head, "verified": true})
}

func cmdAdmit(args []string) error {
	fs := flag.NewFlagSet("admit", flag.ContinueOnError)
	trust := fs.String("trust", "unknown", "source trust level: trusted|community|unknown")
	out := fs.String("out", "", "write <admission_id>.json / .skill-card.md / evidence into this directory")
	card := fs.Bool("card", false, "print the skill card to stderr")
	// allow the positional directory before or after flags
	var root string
	var flagArgs []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if !strings.HasPrefix(a, "-") && root == "" {
			root = a
			continue
		}
		flagArgs = append(flagArgs, a)
		if (a == "--trust" || a == "-trust" || a == "--out" || a == "-out") && i+1 < len(args) {
			flagArgs = append(flagArgs, args[i+1])
			i++
		}
	}
	if err := fs.Parse(flagArgs); err != nil {
		return err
	}
	if root == "" || fs.NArg() != 0 {
		return fmt.Errorf("admit: exactly one skill directory required")
	}
	pack, err := loadPack()
	if err != nil {
		return err
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	var cardRef *string
	if *out != "" {
		if err := os.MkdirAll(*out, 0o700); err != nil {
			return err
		}
	}
	res, err := admission.Admit(root, admission.Options{
		Source:   admission.Source{Type: "local_dir", Locator: root, TrustLevel: *trust},
		Version:  Version,
		Key:      key,
		Pack:     pack,
		CardPath: cardRef,
	})
	if err != nil {
		return err
	}
	if *out != "" {
		base := filepath.Join(*out, res.Admission.AdmissionID)
		cardPath := base + ".skill-card.md"
		res.Admission.SkillCardRef = &cardPath
		if err := os.WriteFile(cardPath, []byte(res.SkillCard), 0o600); err != nil {
			return err
		}
		admJSON, _ := json.MarshalIndent(res.Admission, "", "  ")
		if err := os.WriteFile(base+".json", admJSON, 0o600); err != nil {
			return err
		}
		evDir := filepath.Join(*out, "evidence")
		_ = os.MkdirAll(evDir, 0o700)
		for _, ev := range res.Evidence {
			evJSON, _ := json.Marshal(ev)
			if err := os.WriteFile(filepath.Join(evDir, ev.EvidenceID+".json"), evJSON, 0o600); err != nil {
				return err
			}
		}
	}
	if *card {
		fmt.Fprintln(os.Stderr, res.SkillCard)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(res.Admission); err != nil {
		return err
	}
	if res.Admission.Verdict == "quarantine" {
		os.Exit(3)
	}
	return nil
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

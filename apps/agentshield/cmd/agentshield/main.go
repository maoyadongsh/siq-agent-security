// agentshield is the local AgentShield binary (ADR-011). W1 scope: rulepack
// loading, static scan, local signing identity. inventory / admit / grant /
// serve land in later increments.
package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/server"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/threat"
	"siq-agent-security/apps/agentshield/internal/ui"
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
	case "serve":
		err = cmdServe(os.Args[2:])
	case "inventory":
		err = cmdInventory(os.Args[2:])
	case "policy-exec":
		err = cmdPolicyExec()
	case "hook":
		err = cmdHook(os.Args[2:])
	case "adapter":
		err = cmdAdapter(os.Args[2:])
	case "grant":
		err = cmdGrant(os.Args[2:])
	case "openshell":
		err = cmdOpenshell(os.Args[2:])
	case "release-manifest":
		err = cmdReleaseManifest(os.Args[2:])
	case "manifest-verify":
		err = cmdManifestVerify(os.Args[2:])
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
                                  # recompute the receipt hash chain and signatures; exit 4 on first break
  agentshield inventory [--cwd DIR] [--out FILE]
                                  # read-only discovery of platforms + skill dirs (JSON report)
  agentshield policy-exec         # OpenClaw security.installPolicy exec: stdin request → {decision,reason}
  agentshield hook codebuddy      # CodeBuddy PreToolUse/PostToolUse hook: stdin event → hookSpecificOutput
  agentshield adapter install|uninstall|status [platform]
                                  # write/restore host adapter files (openclaw|hermes|codebuddy|trae)
  agentshield grant <admission_id> --platform P --subject ID
  agentshield grant approve|deploy|reject|revoke <grant_id> [--approve-as ACTOR]
                                  # least-privilege grant; approve requires a human --approve-as
  agentshield openshell probe
  agentshield openshell doctor    # diagnose CLI/gateway; never starts a gateway
  agentshield openshell apply --target NAME [--allow host:port] [--deny host:port]
                                  # L3: CLI-only network policy set + readback (never create_generation)
  agentshield serve [--port N] [--mode audit_only|warn|block]
                                  # decision API + console on 127.0.0.1 (bearer token in <state>/token)
  agentshield release-manifest [--build] [--bin-dir DIR] [--skill-dir DIR]
                                  # sign skill-manifest.json (requires AGENTSHIELD_RELEASE_SEED)
  agentshield manifest-verify [path]
                                  # verify signature + content_hash of a skill-manifest.json`)
}

func cmdInventory(args []string) error {
	fs := flag.NewFlagSet("inventory", flag.ContinueOnError)
	cwd := fs.String("cwd", "", "also scan project-level skill dirs under this directory")
	out := fs.String("out", "", "also write the report to this file (0600)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	admissions, _ := st.ListAdmissions()
	byHash := map[string]string{}
	for _, a := range admissions {
		byHash[a.ContentHash] = a.Verdict
	}
	rep, err := inventory.Run(inventory.Options{Cwd: *cwd, Version: Version, Key: key,
		HasAdmission: func(h string) (string, bool) { v, ok := byHash[h]; return v, ok }})
	if err != nil {
		return err
	}
	raw, _ := json.MarshalIndent(rep, "", "  ")
	if *out != "" {
		if err := os.WriteFile(*out, raw, 0o600); err != nil {
			return err
		}
	}
	_ = os.WriteFile(filepath.Join(dir, "inventory", time.Now().UTC().Format("20060102T150405Z")+".json"), raw, 0o600)
	_, err = os.Stdout.Write(append(raw, '\n'))
	return err
}

func cmdPolicyExec() error {
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	pack, err := loadPack()
	if err != nil {
		return err
	}
	out := adapters.PolicyExec(os.Stdin, adapters.PolicyExecDeps{Pack: pack, Key: key, Version: Version, Persist: st.PutAdmission})
	return json.NewEncoder(os.Stdout).Encode(out)
}

// httpDecider talks to a running `agentshield serve` on behalf of hook subcommands.
type httpDecider struct {
	endpoint, token string
	client          *http.Client
}

func (h *httpDecider) post(path string, body any, out any) error {
	raw, _ := json.Marshal(body)
	req, err := http.NewRequest(http.MethodPost, h.endpoint+path, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+h.token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := h.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("decision service returned %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (h *httpDecider) Decide(r receipt.Request) (*receipt.Decision, error) {
	var out struct {
		Action    string         `json:"action"`
		Reason    string         `json:"reason"`
		ReceiptID string         `json:"receipt_id"`
		Params    map[string]any `json:"params"`
	}
	if err := h.post("/v1/decide", r, &out); err != nil {
		return nil, err
	}
	return &receipt.Decision{Action: out.Action, Reason: out.Reason, Params: out.Params, Receipt: receipt.Receipt{ReceiptID: out.ReceiptID}}, nil
}

func (h *httpDecider) Observe(r receipt.Request, result string) error {
	body := map[string]any{"platform": r.Platform, "session_id": r.SessionID, "agent_id": r.AgentID, "tool": r.Tool, "params": map[string]any{}, "result": result}
	var out map[string]any
	return h.post("/v1/observe", body, &out)
}

func cmdHook(args []string) error {
	if len(args) < 1 || args[0] != "codebuddy" {
		return fmt.Errorf("hook: supported platforms: codebuddy")
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	tok, err := st.Token()
	if err != nil {
		return err
	}
	agentID := os.Getenv("AGENTSHIELD_AGENT_ID")
	if agentID == "" {
		agentID = "default"
	}
	d := &httpDecider{endpoint: fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), token: tok, client: &http.Client{Timeout: 4 * time.Second}}
	out, err := adapters.CodeBuddyHook(os.Stdin, d, agentID, cfg.EnforcementMode)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(out)
}

func cmdServe(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	port := fs.Int("port", 0, "listen port (default from config.json, 47611)")
	mode := fs.String("mode", "", "enforcement mode override: audit_only|warn|block")
	if err := fs.Parse(args); err != nil {
		return err
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	if *port != 0 {
		cfg.Port = *port
	}
	if *mode != "" {
		switch *mode {
		case "audit_only", "warn", "block":
			cfg.EnforcementMode = *mode
		default:
			return fmt.Errorf("serve: invalid --mode %q", *mode)
		}
	}
	lockPath := filepath.Join(dir, "serve.lock")
	lock, err := os.OpenFile(lockPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if os.IsExist(err) {
			return fmt.Errorf("serve: another instance holds %s (remove it if that process is gone)", lockPath)
		}
		return err
	}
	fmt.Fprintf(lock, "%d\n", os.Getpid())
	_ = lock.Close()
	defer os.Remove(lockPath)

	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	pack, err := loadPack()
	if err != nil {
		return err
	}
	tok, err := st.Token()
	if err != nil {
		return err
	}
	chain, err := receipt.OpenChain(dir, "local", key)
	if err != nil {
		return err
	}
	eng, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: st.ActiveGrant, EnforcementMode: cfg.EnforcementMode, Version: Version, HoldChannel: cfg.HoldChannel})
	if err != nil {
		return err
	}
	home, _ := os.UserHomeDir()
	bin, _ := os.Executable()
	if bin != "" {
		bin, _ = filepath.Abs(bin)
	}
	addr := fmt.Sprintf("127.0.0.1:%d", cfg.Port)
	srv, err := server.New(server.Deps{
		Store: st, Engine: eng, Chain: chain, Pack: pack, Key: key, Token: tok,
		Version: Version, Mode: cfg.EnforcementMode, UI: ui.Handler(),
		Home: home, Binary: bin, Endpoint: "http://" + addr,
		Openshell: openshell.New(openshell.Options{ProbeTimeout: 5 * time.Second}),
	})
	if err != nil {
		return err
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "agentshield %s serving on http://%s  mode=%s  state=%s\n", Version, addr, cfg.EnforcementMode, dir)
	fmt.Fprintf(os.Stderr, "bearer token: %s\n", filepath.Join(dir, "token"))
	hs := &http.Server{Handler: srv.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = hs.Shutdown(ctx)
	}()
	if err := hs.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
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
	if err := persistAdmission(res); err != nil {
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

func stateDir() (string, error) { return state.DefaultDir() }

func loadKey() (*signing.Key, error) {
	dir, err := stateDir()
	if err != nil {
		return nil, err
	}
	return signing.Load(dir)
}

func persistAdmission(res *admission.Result) error {
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	return st.PutAdmission(res)
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

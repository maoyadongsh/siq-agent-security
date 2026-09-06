// agentshield is the local siq-agent-security binary (ADR-011). The public
// CLI name is siq-agent-security; this package path stays apps/agentshield.
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
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/product"
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
const RulepackPubEnv = product.EnvRulepackPub

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "version":
		fmt.Printf("%s %s (%s/%s)\n", product.Name, Version, runtime.GOOS, runtime.GOARCH)
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
	case "export":
		err = cmdExport(os.Args[2:])
	case "sync":
		err = cmdSync(os.Args[2:])
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
	case "incomplete":
		err = cmdIncomplete(os.Args[2:])
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, product.Name+":", err)
		os.Exit(1)
	}
}

func usage() {
	n := product.Name
	fmt.Fprintf(os.Stderr, `usage:
  %[1]s version
  %[1]s rulepack            # effective rule pack summary (JSON)
  %[1]s scan <file>...      # static threat scan, one JSON result per line
  %[1]s admit <skill-dir> [--trust trusted|community|unknown] [--out <dir>] [--card]
                                  # pre-install verdict (JSON); exit 3 = quarantine
  %[1]s pubkey              # local signing public key (base64)
  %[1]s verify [--chain local]
                                  # recompute the receipt hash chain and signatures; exit 4 on first break
  %[1]s inventory [--cwd DIR] [--out FILE] [--connectors-dir DIR]
                                  # read-only discovery of platforms, skill dirs, MCP configs (JSON report)
  %[1]s export [--out FILE] # redacted bundle (0600 file or stdout)
  %[1]s sync --control-api URL [--identity ID] [--secret-file PATH] [--task-id ID]
                                  # optional Edge upload; skip (exit 0) without creds; never auto-runs from serve
  %[1]s policy-exec         # OpenClaw security.installPolicy exec: stdin request → {decision,reason}
  %[1]s hook codebuddy      # CodeBuddy PreToolUse/PostToolUse hook: stdin event → hookSpecificOutput
  %[1]s adapter install|uninstall|status [platform]
                                  # write/restore host adapter files (openclaw|hermes|codebuddy|trae)
  %[1]s grant <admission_id> --platform P --subject ID
  %[1]s grant approve|deploy|reject|revoke <grant_id> [--approve-as ACTOR]
                                  # least-privilege grant; approve requires a human --approve-as
  %[1]s openshell probe
  %[1]s openshell doctor    # diagnose CLI/gateway; never starts a gateway
  %[1]s openshell apply --target NAME [--allow host:port] [--deny host:port]
                                  # L3: CLI-only network policy set + readback (never create_generation)
  %[1]s serve [--port N] [--mode audit_only|warn|block]
                                  # loopback console; adapters use <state>/token; UI requires pairing code
  %[1]s release-manifest [--build] [--bin-dir DIR] [--skill-dir DIR]
                                  # sign skill-manifest.json (requires SIQ_AGENT_SECURITY_RELEASE_SEED)
  %[1]s manifest-verify [path]
                                  # verify signature + content_hash of a skill-manifest.json
  %[1]s incomplete [--recover]  # list durable incomplete multi-file commits
`, n)
}

func cmdIncomplete(args []string) error {
	fs := flag.NewFlagSet("incomplete", flag.ContinueOnError)
	recoverFlag := fs.Bool("recover", false, "replay prepared commits under exclusive writer ownership")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("incomplete: unexpected arguments")
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	if *recoverFlag {
		writer, err := state.AcquireWriter(dir)
		if err != nil {
			return err
		}
		defer writer.Release()
		if _, err := st.RecoverGrantCommits(writer); err != nil {
			return err
		}
	}
	markers, err := st.ListIncompleteCommits()
	if err != nil {
		return err
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(markers)
}

func cmdInventory(args []string) error {
	fs := flag.NewFlagSet("inventory", flag.ContinueOnError)
	cwd := fs.String("cwd", "", "also scan project-level skill dirs under this directory")
	out := fs.String("out", "", "also write the report to this file (0600)")
	connectors := fs.String("connectors-dir", "", "optional parent of hermes/openclaw/directory/mcp connector binaries")
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
	rep, err := runLocalInventory(st, key, *cwd, resolveConnectorsDir(*connectors))
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

// httpDecider talks to a running `siq-agent-security serve` on behalf of hook subcommands.
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
	agentID := product.Env(product.EnvAgentID, product.EnvAgentIDOld)
	if agentID == "" {
		agentID = "default"
	}
	d := &httpDecider{endpoint: fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), token: tok, client: &http.Client{Timeout: 4 * time.Second}}
	out, err := adapters.CodeBuddyHook(os.Stdin, d, agentID, cfg.EnforcementMode, dir)
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
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return fmt.Errorf("serve: %w", err)
	}
	defer func() { _ = writer.Release() }()
	if _, err := st.RecoverGrantCommits(writer); err != nil {
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
	tok, err := st.Token()
	if err != nil {
		return err
	}
	chain, err := receipt.OpenChain(dir, "local", key)
	if err != nil {
		return err
	}
	if cpStore, err := receipt.OpenCheckpointStore(dir, key); err != nil {
		return err
	} else {
		chain.AttachCheckpointStore(cpStore)
	}
	eng, err := receipt.New(receipt.Options{
		Pack: pack, Chain: chain, Grants: st.ActiveGrant, EnforcementMode: cfg.EnforcementMode,
		Version: Version, HoldChannel: cfg.HoldChannel, SessionIdleTTL: cfg.SessionIdleTTL(),
	})
	if err != nil {
		return err
	}
	if n, err := pending.Promote(dir, func(rec pending.Record) error {
		_, err := eng.AppendPendingObserved(rec)
		return err
	}); err != nil {
		return fmt.Errorf("serve: promote pending: %w", err)
	} else if n > 0 {
		fmt.Fprintf(os.Stderr, "%s: promoted %d pending fail-closed decision(s) to signed receipts\n", product.Name, n)
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
		Openshell:  openshell.New(openshell.Options{ProbeTimeout: 5 * time.Second}),
		ListenHost: "127.0.0.1", ListenPort: cfg.Port,
	})
	if err != nil {
		return err
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "%s %s serving on http://%s  mode=%s  state=%s\n", product.Name, Version, addr, cfg.EnforcementMode, dir)
	fmt.Fprintf(os.Stderr, "adapters: decision token file %s (not accepted on admin endpoints)\n", filepath.Join(dir, "token"))
	if code := srv.PairingDisplay(); code != "" {
		fmt.Fprintf(os.Stderr, "admin pairing code (single use, 5 min): %s\n", code)
		fmt.Fprintf(os.Stderr, "desktop profile is same-UID: this code does not stop a same-user Agent from reading the state directory or running CLI.\n")
	}
	hs := &http.Server{Handler: srv.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	refreshCtx, refreshCancel := context.WithCancel(context.Background())
	defer refreshCancel()
	go func() {
		ticker := time.NewTicker(5 * time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				_ = srv.Refresh("")
			case <-refreshCtx.Done():
				return
			}
		}
	}()
	go func() {
		<-stop
		refreshCancel()
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
		fmt.Fprintln(os.Stderr, product.Name+":", verr)
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
	b64 := product.Env(product.EnvRulepackPub, product.EnvRulepackPubOld)
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
	return rulepack.Load(pub, func(reason string) { fmt.Fprintln(os.Stderr, product.Name+":", reason) })
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

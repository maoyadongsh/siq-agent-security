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
	"io"
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
	"siq-agent-security/apps/agentshield/internal/provenance"
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
	case "import-skill":
		err = cmdImportSkill(os.Args[2:], os.Stdout)
	case "pubkey":
		err = cmdPubkey()
	case "verify":
		err = cmdVerify(os.Args[2:])
	case "serve":
		err = cmdServe(os.Args[2:])
	case "ui":
		err = cmdUI(os.Args[2:], os.Stdout)
	case "teardown":
		err = cmdTeardown(os.Args[2:], os.Stdout)
	case "setup":
		err = cmdSetup(os.Args[2:], os.Stdout)
	case "init":
		err = cmdInitialize(os.Args[2:], os.Stdout)
	case "start":
		err = startLocal(os.Args[2:], os.Stdout, cmdServe)
	case "service-login":
		err = cmdServiceLogin(os.Args[2:], os.Stdout)
	case "launch-agent-status":
		err = cmdLaunchAgentStatus(os.Args[2:], os.Stdout)
	case "launch-agent-load":
		err = cmdLaunchAgentLoad(os.Args[2:], os.Stdout)
	case "launch-agent-start":
		err = cmdLaunchAgentStart(os.Args[2:], os.Stdout)
	case "launch-agent-register":
		err = cmdLaunchAgentRegister(os.Args[2:], os.Stdout)
	case "launch-agent-prepare":
		err = cmdLaunchAgentPrepare(os.Args[2:], os.Stdout)
	case "launch-agent-plist":
		err = cmdLaunchAgentPlist(os.Args[2:], os.Stdout)
	case "service-unit":
		err = cmdServiceUnit(os.Args[2:], os.Stdout)
	case "service-start", "service-stop", "service-status":
		err = cmdServiceControl(strings.TrimPrefix(os.Args[1], "service-"), os.Args[2:], os.Stdout)
	case "client-upgrade-check":
		err = cmdClientUpgradeCheck(os.Args[2:], os.Stdout)
	case "service-rollback":
		err = cmdServiceRollback(os.Args[2:], os.Stdout)
	case "service-upgrade":
		err = cmdServiceUpgrade(os.Args[2:], os.Stdout)
	case "client-install":
		err = cmdClientInstall(os.Args[2:], os.Stdout)
	case "client-stage":
		err = cmdClientStage(os.Args[2:], os.Stdout)
	case "service-unregister":
		err = cmdServiceUnregister(os.Args[2:], os.Stdout)
	case "service-register":
		err = cmdServiceRegister(os.Args[2:], os.Stdout)
	case "service-prepare":
		err = cmdServicePrepare(os.Args[2:], os.Stdout)
	case "status":
		err = cmdLocalSession("status", os.Args[2:])
	case "pair":
		err = cmdLocalSession("pair", os.Args[2:])
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
  %[1]s import-skill --path PATH --kind local_dir|local_zip --actor ACTOR [--id si-...]
                                  # fix and scan a candidate under the state writer lock; does not install
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
  %[1]s setup --confirm-setup [--port N] [--runtime] [--open-ui] # initialize, register and start Linux user service
  %[1]s client-install --manifest FILE --binary FILE --confirm-install [--port N] [--runtime] [--open-ui]
  %[1]s teardown --confirm-teardown # disable startup, stop, unregister; preserve data
  %[1]s ui [--print]       # open verified local management page, or print its URL
  %[1]s init [--port N]     # initialize local configuration and instance identity; does not start protection
  %[1]s start [--port N]    # initialize and serve in foreground, or reuse a matching running instance
  %[1]s service-login --enable --confirm-enable | --disable # control user login startup
  %[1]s launch-agent-status # verify loaded macOS configuration and local API
  %[1]s launch-agent-load --confirm-load # load registered macOS configuration without starting
  %[1]s launch-agent-start --confirm-start # start owned macOS task and verify local API
  %[1]s launch-agent-register # publish owned macOS user configuration; does not load/start
  %[1]s launch-agent-prepare # prepare signed macOS configuration without loading it
  %[1]s launch-agent-plist # export macOS LaunchAgent configuration; read-only
  %[1]s service-unit        # export Linux user service configuration (read-only, requires init)
  %[1]s service-start|service-status # start or inspect the owned Linux service
  %[1]s service-stop --confirm-stop # stop protection explicitly
  %[1]s service-unregister --confirm-unregister # remove stopped service registration, keep data
  %[1]s client-upgrade-check --manifest FILE --binary FILE # read-only signed compatibility preflight
  %[1]s service-rollback --transaction ID --manifest OLD --binary OLD --confirm-rollback [--recover ID]
  %[1]s service-upgrade --manifest FILE --binary FILE --confirm-upgrade [--recover ID]
  %[1]s client-stage --manifest FILE --binary FILE # verify and stage a release without activation
  %[1]s service-register [--runtime] # register Linux user service without starting it
  %[1]s service-prepare     # publish signed service configuration under the state writer lock
  %[1]s serve [--port N] [--mode audit_only|warn|block]
                                  # loopback console; adapters use <state>/token; UI requires pairing code
  %[1]s status [--port N]   # verify the local service identity and readiness (JSON)
  %[1]s pair [--port N]     # print a new one-time admin pairing code without restarting serve
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
		ActionID  string         `json:"action_id"`
		Params    map[string]any `json:"params"`
	}
	if err := h.post("/v1/decide", r, &out); err != nil {
		return nil, err
	}
	return &receipt.Decision{Action: out.Action, Reason: out.Reason, Params: out.Params, Receipt: receipt.Receipt{ReceiptID: out.ReceiptID, ActionID: out.ActionID}}, nil
}

func (h *httpDecider) Observe(r receipt.Request, result string) error {
	body := map[string]any{"platform": r.Platform, "session_id": r.SessionID, "agent_id": r.AgentID, "tool": r.Tool, "tool_call_id": r.ToolCallID, "action_id": r.ActionID, "decision_receipt_id": r.DecisionReceiptID, "params": r.Params, "result": result}
	var out map[string]any
	return h.post("/v1/observe", body, &out)
}

func cmdHook(args []string) error {
	if len(args) < 1 || args[0] != "codebuddy" {
		return fmt.Errorf("hook: supported platforms: codebuddy")
	}
	return runCodeBuddyHook(os.Stdin, os.Stdout)
}

// A command-hook exit status of 1 is non-blocking in CodeBuddy. Initialization
// failures must still reach the adapter's structured pre/post failure mapping.
func codeBuddyClient() (adapters.Decider, string, string) {
	dir, err := stateDir()
	if err != nil {
		return nil, "block", ""
	}
	st, err := state.Open(dir)
	if err != nil {
		return nil, "block", ""
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		// Partial decoded fields cannot authorize advisory mode.
		return nil, "block", dir
	}
	// Credential creation belongs to the daemon. A hook only reads its token.
	raw, err := os.ReadFile(filepath.Join(dir, "token"))
	tok := strings.TrimSpace(string(raw))
	if err != nil || len(tok) < 32 {
		return nil, cfg.EnforcementMode, dir
	}
	d := &httpDecider{endpoint: fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), token: tok, client: &http.Client{Timeout: 4 * time.Second}}
	return d, cfg.EnforcementMode, dir
}

func runCodeBuddyHook(in io.Reader, out io.Writer) error {
	d, mode, dir := codeBuddyClient()
	agentID := product.Env(product.EnvAgentID, product.EnvAgentIDOld)
	if agentID == "" {
		agentID = "default"
	}
	result, err := adapters.CodeBuddyHook(in, d, agentID, mode, dir)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
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
	if _, err := os.Lstat(filepath.Join(dir, "config.json")); errors.Is(err, os.ErrNotExist) {
		return errors.New("serve: configuration missing; run siq-agent-security init with the same state directory first")
	} else if err != nil {
		return errors.New("serve: configuration unavailable; check the selected state directory")
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
	if err := st.CheckServiceSwitchPending(); err != nil {
		return err
	}
	if _, err := st.RecoverGrantCommits(writer); err != nil {
		return err
	}

	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	intentStore, err := st.IntentAuthority(key)
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
	recovery, err := st.RecoveryToken()
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
	provenanceStore, err := provenance.Open(dir, key)
	if err != nil {
		return err
	}
	eng, err := receipt.New(receipt.Options{
		Pack: pack, Chain: chain, Grants: st.ActiveGrant, EnforcementMode: cfg.EnforcementMode,
		Version: Version, HoldChannel: cfg.HoldChannel, SessionIdleTTL: cfg.SessionIdleTTL(),
		IntentLookup:      receipt.ResolveStore(intentStore),
		ProvenanceCheck:   provenanceStore.MatchParameters,
		ContextLookup:     intentStore.GetContext,
		IntentEnforcement: cfg.IntentEnforcement,
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
		Store: st, Engine: eng, Chain: chain, Pack: pack, Key: key, Token: tok, RecoveryToken: recovery,
		Version: Version, Mode: cfg.EnforcementMode, UI: ui.Handler(),
		Home: home, Binary: bin, Endpoint: "http://" + addr,
		HermesHome: os.Getenv("HERMES_HOME"), HermesCLI: os.Getenv("SIQ_AGENT_SECURITY_HERMES_CLI"), LocalAppData: os.Getenv("LOCALAPPDATA"),
		Openshell:  openshell.New(openshell.Options{ProbeTimeout: 5 * time.Second}),
		ListenHost: "127.0.0.1", ListenPort: cfg.Port,
	})
	if err != nil {
		return err
	}
	ln, err := net.Listen("tcp", addr)
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.CloseRuntimeChecks(ctx)
	}()
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
	defer signal.Stop(stop)
	refreshCtx, refreshCancel := context.WithCancel(context.Background())
	refreshDone := make(chan struct{})
	defer func() {
		refreshCancel()
		<-refreshDone
	}()
	go func() {
		defer close(refreshDone)
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
	return serveLocalHTTP(hs, ln, stop, 3*time.Second)
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

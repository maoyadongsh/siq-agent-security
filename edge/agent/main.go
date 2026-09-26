// Command edge-agent is the SIQ Edge Agent CLI (Phase 0 skeleton).
//
// Subcommands:
//
//	register  --control-plane URL --enrollment-code CODE
//	heartbeat
//	tasks
//	run-once  --connector NAME [--scope JSON] [--connector-bin PATH]
//
// The agent talks to the control plane (apps/control-api, Phase 0 server
// contract defined in client.go) and drives connector binaries over the
// NDJSON subprocess protocol (packages/contracts/connector-protocol.v1.md).
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"regexp"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// agentVersion is sent as X-Edge-Version and in register.version.
var agentVersion = "0.1.0" // Release builds stamp main.agentVersion via -ldflags -X.

func main() {
	log.SetFlags(log.LstdFlags)
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	var err error
	switch os.Args[1] {
	case "inspect-host":
		err = cmdInspectHost(os.Args[2:])
	case "register":
		err = cmdRegister(ctx, os.Args[2:])
	case "heartbeat":
		err = cmdHeartbeat(ctx, os.Args[2:])
	case "tasks":
		err = cmdTasks(ctx, os.Args[2:])
	case "serve":
		err = cmdServe(ctx, os.Args[2:])
	case "service-unit":
		err = cmdServiceUnit(os.Args[2:])
	case "prepare-install":
		err = cmdPrepareInstall(os.Args[2:])
	case "verify-enterprise-release":
		err = cmdVerifyEnterpriseRelease(os.Args[2:])
	case "recover-registration":
		err = cmdRecoverRegistration(ctx, os.Args[2:])
	case "rotate-credential":
		err = cmdRotateCredential(ctx, os.Args[2:])
	case "confirm-discovery-plan":
		err = cmdConfirmDiscovery(os.Args[2:])
	case "confirm-discovery-schedule":
		err = cmdConfirmSchedule(ctx, os.Args[2:])
	case "retire-discovery-schedule":
		err = cmdRetireSchedule(ctx, os.Args[2:])
	case "install-user-service":
		err = cmdInstallUserService(ctx, os.Args[2:])
	case "user-service-status":
		err = cmdUserServiceStatus(ctx, os.Args[2:])
	case "setup-enterprise":
		err = cmdSetupEnterprise(ctx, os.Args[2:])
	case "run-once":
		err = cmdRunOnce(ctx, os.Args[2:])
	case "help", "-h", "--help":
		usage()
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		log.Printf("error: %v", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `usage: edge-agent <command> [flags]

commands:
  rotate-credential --confirm-device ID [--resume]          Linux: explicitly rotate/recover device credential; no business grants
  inspect-host                                             Linux: read bounded host metadata; no upload or registration
  setup-enterprise --help                                  Linux: confirmed plan to registered discovery service
  install-user-service --release FILE --stage DIR [--start]  Linux: install verified discovery user service
  user-service-status                                     Linux: read user service state; no start or registration
  confirm-discovery-plan --plan FILE --tenant ID --confirm-plan-sha256 DIGEST
  confirm-discovery-schedule (--intent FILE | --schedule-id ID | --resume) [--interactive | --confirm-intent-sha256 DIGEST]   Linux: preview or confirm bounded discovery
                                                           Linux: restrict scans to confirmed plan scope
  retire-discovery-schedule [--resume] [--interactive | --confirm-retire-intent-sha256 DIGEST]
                                                           Linux: preview or archive a revoked old schedule; --resume finishes a pending archive
  recover-registration --control-plane ORIGIN --environment ID
                                                           Linux: recover a pending initial registration
  prepare-install --help                                   Linux: validate confirmed plan and stage files only
  verify-enterprise-release --release FILE [--bundle DIR]   Linux: verify publisher and optionally all artifacts; no install
  serve                                                    Linux: heartbeat and task polling until stopped
  service-unit --binary PATH --state-dir PATH --connector-dir PATH
                                                           print Linux user service; does not install it
  register  --control-plane URL --enrollment-code CODE   enroll this device
  heartbeat                                                beat every 30s (exponential backoff on failure)
  tasks                                                    fetch pending tasks and execute run-scan tasks
  run-once  --connector NAME [--scope JSON] [--connector-bin PATH]
                                                          run one local scan and print NDJSON results
`)
}

// parseFlags parses a subcommand flag set; -h/--help returns nil.
func parseFlags(fs *flag.FlagSet, args []string) error {
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	return nil
}

// cmdRegister enrolls the device and persists state (0600). The public key of
// a local Phase-0 signer is sent so the control plane can later pin it.
func cmdRegister(ctx context.Context, args []string) error {
	return registerWithCapabilities(ctx, args, map[string]any{
		"connectors":       []string{"hermes", "docker", "directory", "openclaw"},
		"protocol_version": "connector-protocol.v1",
		"data_categories":  []string{"config_names", "tool_names", "image_names"},
	})
}

func registerWithCapabilities(ctx context.Context, args []string, caps map[string]any) error {
	return registerWithCapabilitiesInput(ctx, args, caps, func(ctx context.Context) (string, error) {
		return readEnrollmentCodeContext(ctx, os.Stdin)
	})
}

func registerWithCapabilitiesInput(ctx context.Context, args []string, caps map[string]any, readCode func(context.Context) (string, error)) error {
	fs := flag.NewFlagSet("register", flag.ContinueOnError)
	cp := fs.String("control-plane", "http://127.0.0.1:8600", "control plane base URL")
	code := fs.String("enrollment-code", "", "enrollment code issued by the control plane (required)")
	stdinCode := fs.Bool("enrollment-code-stdin", false, "read enrollment code from standard input instead of process arguments")
	expectedEnvironment := fs.String("environment", "", "expected environment from confirmed installation plan")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if *stdinCode {
		if *code != "" {
			return errors.New("use only one enrollment code input")
		}
		value, err := readCode(ctx)
		if err != nil {
			return err
		}
		*code = value
	}
	if *expectedEnvironment != "" && !regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,64}$`).MatchString(*expectedEnvironment) {
		return errors.New("invalid expected environment")
	}
	if *code == "" {
		return errors.New("--enrollment-code is required")
	}
	statePath, err := StateFilePath()
	if err != nil {
		return err
	}
	if _, err := os.Lstat(statePath); !os.IsNotExist(err) {
		return errors.New("local device state already exists or is unreadable; use its heartbeat/tasks commands")
	}
	if _, err := validateControlPlaneURL(*cp); err != nil {
		return errors.New("invalid registration control plane")
	}
	dir, err := StateDir()
	if err != nil {
		return errRegistrationPending
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return errRegistrationPending
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errRegistrationPending
	}
	defer unlock()
	if _, err := os.Lstat(statePath); !os.IsNotExist(err) {
		return errRegistrationPending
	}
	identity, err := NewUUID()
	if err != nil {
		return err
	}
	signer, err := NewSigner()
	if err != nil {
		return err
	}
	pubPEM, err := signer.PublicKeyPEM()
	if err != nil {
		return err
	}
	pending := &State{ControlPlaneURL: *cp, DeviceIdentity: identity, PublicKeyPEM: pubPEM, SignerSeed: signer.SeedB64(), EnvironmentID: *expectedEnvironment}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err := beginRegistration(pending); err != nil {
		return err
	}
	cli := NewClient(ClientConfig{ControlPlaneURL: *cp, Version: agentVersion})
	resp, err := cli.RegisterBound(ctx, *code, identity, pubPEM, caps, *expectedEnvironment)
	if err != nil {
		return err
	}
	state := &State{
		ControlPlaneURL:       *cp,
		DeviceIdentity:        identity,
		Secret:                resp.DeviceSecret,
		PublicKeyPEM:          pubPEM,
		ControlPlanePublicKey: resp.ControlPlanePublicKey,
		EnvironmentID:         resp.EnvironmentID,
		SignerSeed:            signer.SeedB64(),
	}
	if err := state.Save(); err != nil {
		return err
	}
	path, err := StateFilePath()
	if err != nil {
		return err
	}
	log.Printf("registered device %s (state written to %s, mode 0600; secret never logged)", state.DeviceIdentity, path)
	return nil
}

// CLI cancellation can return while the stdin reader remains blocked; main then
// exits. Do not close a caller-owned input stream or reuse this as a daemon loop.
func readEnrollmentCodeContext(ctx context.Context, input io.Reader) (string, error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	type result struct {
		code string
		err  error
	}
	done := make(chan result, 1)
	go func() { code, err := readEnrollmentCode(input); done <- result{code, err} }()
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case value := <-done:
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return value.code, value.err
	}
}

func readEnrollmentCode(input io.Reader) (string, error) {
	reader := bufio.NewReader(io.LimitReader(input, 1025))
	line, err := reader.ReadString('\n')
	if err != nil && err != io.EOF || len(line) > 1024 {
		return "", errors.New("invalid enrollment code input")
	}
	code := strings.TrimSpace(line)
	if code == "" || strings.ContainsAny(code, " \t\r\n") {
		return "", errors.New("invalid enrollment code input")
	}
	return code, nil
}

func newAuthedClient(state *State) *Client {
	return NewClient(ClientConfig{
		ControlPlaneURL: state.ControlPlaneURL,
		DeviceIdentity:  state.DeviceIdentity,
		Secret:          state.Secret,
		Version:         agentVersion,
	})
}

// cmdHeartbeat beats forever (30s interval, exponential backoff) until the
// process receives a signal.
func cmdHeartbeat(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("heartbeat", flag.ContinueOnError)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	state, err := LoadState()
	if err != nil {
		return err
	}
	cli := newAuthedClient(state)
	log.Printf("heartbeat loop: control plane %s, interval 30s", state.ControlPlaneURL)
	return cli.RunHeartbeatLoop(ctx, 30*time.Second, 15*time.Minute)
}

// cmdTasks fetches pending tasks and executes run-scan tasks, posting a
// receipt per task. One failing task does not abort the others.
func cmdTasks(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("tasks", flag.ContinueOnError)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	state, err := LoadState()
	if err != nil {
		return err
	}
	cli := newAuthedClient(state)
	release, err := acquireTaskLock()
	if err != nil {
		return err
	}
	defer release()
	return executePendingTasks(ctx, state, cli)
}

func executePendingTasks(ctx context.Context, state *State, cli *Client) error {
	// R04：先冲刷本地 pending receipt，避免 uploaded 卡住无人回执。
	if n, err := DrainPendingReceipts(ctx, cli); err != nil {
		log.Printf("drain pending receipts: posted=%d err=%v", n, err)
	} else if n > 0 {
		log.Printf("drain pending receipts: posted=%d", n)
	}
	tasks, err := cli.FetchTasks(ctx, state.DeviceIdentity)
	if err != nil {
		return err
	}
	if len(tasks) == 0 {
		log.Printf("no pending tasks for %s", state.DeviceIdentity)
		return nil
	}
	runner := &Runner{Client: cli, State: state}
	for _, t := range tasks {
		rcpt, err := runner.Execute(ctx, t)
		if err != nil {
			log.Printf("task %s: execution infrastructure failure: %v", t.TaskID, err)
			continue
		}
		if err := cli.PostReceipt(ctx, t.TaskID, rcpt); err != nil {
			log.Printf("task %s: failed to post receipt: %v", t.TaskID, err)
			continue
		}
		if err := RemovePendingReceipt(t.TaskID); err != nil {
			log.Printf("task %s: clear pending receipt: %v", t.TaskID, err)
		}
		if rcpt.Status != "success" {
			log.Printf("task %s: status=%s error=%s %s", t.TaskID, rcpt.Status, rcpt.ErrorCode, rcpt.ErrorMessage)
		} else {
			log.Printf("task %s: status=%s candidates=%d evidence=%d", t.TaskID, rcpt.Status, rcpt.CandidateCount, rcpt.EvidenceCount)
		}
	}
	return nil
}

// cmdRunOnce runs one scan locally and prints the results as NDJSON, one
// record per line: {"describe":...}, {"validate_scope":...}, {"plan_scan":...},
// {"candidate":...}, {"evidence":...}, {"checkpoint":...}.
func cmdRunOnce(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("run-once", flag.ContinueOnError)
	connector := fs.String("connector", "hermes", "connector name (hermes|openclaw|docker|directory|systemd|kubernetes|process|mcp|piagent|workbuddy|dify|siq)")
	scopeJSON := fs.String("scope", "", "connector scope as JSON (default: connector default scope)")
	binOverride := fs.String("connector-bin", "", "explicit connector binary path")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	bin, err := ResolveConnectorBin(*connector, *binOverride)
	if err != nil {
		return err
	}
	log.Printf("run-once: connector=%s binary=%s", *connector, bin)

	cc, err := NewSubprocessConnector(ctx, bin, SubprocessOptions{Name: *connector, Version: agentVersion})
	if err != nil {
		return err
	}
	defer cc.Close()

	caps, err := cc.Describe(ctx)
	if err != nil {
		return err
	}
	emit("describe", caps)

	var scope *protocol.Scope
	if strings.TrimSpace(*scopeJSON) != "" {
		if err := json.Unmarshal([]byte(*scopeJSON), &scope); err != nil {
			return fmt.Errorf("--scope is not a valid Scope object: %w", err)
		}
		vr, err := cc.ValidateScope(ctx, scope)
		if err != nil {
			return err
		}
		emit("validate_scope", vr)
		if !vr.Valid {
			return fmt.Errorf("scope rejected: %s", strings.Join(vr.Errors, "; "))
		}
	}
	plan, err := cc.PlanScan(ctx, scope, "")
	if err != nil {
		return err
	}
	emit("plan_scan", plan)

	batch, err := cc.Collect(ctx, plan)
	if err != nil {
		return err
	}
	if batch.Truncated {
		log.Printf("run-once: batch truncated (audit note: limit_exceeded)")
	}
	for _, c := range batch.Candidates {
		emit("candidate", c)
	}
	for _, e := range batch.Evidence {
		emit("evidence", e)
	}
	cursor, err := cc.Checkpoint(ctx)
	if err != nil {
		return err
	}
	emit("checkpoint", protocol.CursorResult{Cursor: cursor})
	return nil
}

// emit prints one NDJSON line {"kind": value}.
func emit(kind string, v any) {
	line, err := json.Marshal(map[string]any{kind: v})
	if err != nil {
		log.Printf("emit %s: %v", kind, err)
		return
	}
	fmt.Println(string(line))
}

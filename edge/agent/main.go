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
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// agentVersion is sent as X-Edge-Version and in register.version.
const agentVersion = "0.1.0"

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
	case "register":
		err = cmdRegister(ctx, os.Args[2:])
	case "heartbeat":
		err = cmdHeartbeat(ctx, os.Args[2:])
	case "tasks":
		err = cmdTasks(ctx, os.Args[2:])
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
	fs := flag.NewFlagSet("register", flag.ContinueOnError)
	cp := fs.String("control-plane", "http://127.0.0.1:8600", "control plane base URL")
	code := fs.String("enrollment-code", "", "enrollment code issued by the control plane (required)")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if *code == "" {
		return errors.New("--enrollment-code is required")
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
	caps := map[string]any{
		"connectors":       []string{"hermes", "docker", "directory", "openclaw"},
		"protocol_version": "connector-protocol.v1",
		"data_categories":  []string{"config_names", "tool_names", "image_names"},
	}
	cli := NewClient(ClientConfig{ControlPlaneURL: *cp, Version: agentVersion})
	resp, err := cli.Register(ctx, *code, identity, pubPEM, caps)
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
	connector := fs.String("connector", "hermes", "connector name (hermes|openclaw|docker|directory|systemd|kubernetes|process|mcp|piagent|workbuddy|dify)")
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

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/controlsync"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdSync(args []string) error {
	fs := flag.NewFlagSet("sync", flag.ContinueOnError)
	api := fs.String("control-api", "", "Control API base URL (no trailing path)")
	identity := fs.String("identity", os.Getenv("SIQ_AS_EDGE_IDENTITY"), "Edge device identity")
	secretFile := fs.String("secret-file", "", "file containing the Edge bearer secret")
	taskID := fs.String("task-id", os.Getenv("SIQ_AS_EDGE_TASK_ID"), "scan task id")
	cwd := fs.String("cwd", "", "also scan project-level skill dirs under this directory")
	connectors := fs.String("connectors-dir", "", "optional connector binaries parent")
	if err := fs.Parse(args); err != nil {
		return err
	}
	secret := strings.TrimSpace(os.Getenv("SIQ_AS_EDGE_SECRET"))
	if strings.TrimSpace(*secretFile) != "" {
		raw, err := os.ReadFile(*secretFile)
		if err != nil {
			return fmt.Errorf("sync: cannot read secret-file")
		}
		secret = strings.TrimSpace(string(raw))
	}
	creds := controlsync.Creds{
		ControlAPI: strings.TrimSpace(*api),
		Identity:   strings.TrimSpace(*identity),
		Secret:     secret,
		TaskID:     strings.TrimSpace(*taskID),
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

	res, err := controlsync.Push(rep, key, creds, time.Now().UTC(), nil)
	now := time.Now().UTC().Format(time.RFC3339)
	if err != nil {
		_ = st.AppendAudit(state.AuditEvent{At: now, Event: "sync_failed", Note: "http"})
		return err
	}
	if res.Skipped {
		_ = st.AppendAudit(state.AuditEvent{At: now, Event: "sync_skipped", Note: "missing enrollment or empty batch"})
	} else {
		_ = st.AppendAudit(state.AuditEvent{At: now, Event: "sync_ok", Note: "candidates+evidence"})
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(map[string]any{
		"skipped":     res.Skipped,
		"reason":      res.Reason,
		"status_code": res.StatusCode,
		"candidates":  res.Candidates,
		"evidence":    res.Evidence,
	})
}

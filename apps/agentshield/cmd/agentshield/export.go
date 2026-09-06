package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	"siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdExport(args []string) error {
	fs := flag.NewFlagSet("export", flag.ContinueOnError)
	out := fs.String("out", "", "write JSON to this file (0600); default stdout")
	cwd := fs.String("cwd", "", "also scan project-level skill dirs under this directory")
	connectors := fs.String("connectors-dir", "", "optional connector binaries parent")
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
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	rep, err := runLocalInventory(st, key, *cwd, resolveConnectorsDir(*connectors))
	if err != nil {
		return err
	}
	admissions, err := st.ListAdmissions()
	if err != nil {
		return err
	}
	grants, err := st.ListGrants()
	if err != nil {
		return err
	}
	chain, err := receipt.OpenChain(dir, "local", key)
	if err != nil {
		return err
	}
	var cp *receipt.Checkpoint
	if store, err := receipt.OpenCheckpointStore(dir, key); err != nil {
		return err
	} else if loaded, err := store.LoadOptional("local"); err != nil {
		return err
	} else {
		cp = loaded
	}
	recs, err := chain.ReadLimited(receipt.ReadLimit{
		MaxRecords: export.DefaultMaxReceipts,
		MaxBytes:   32 << 20,
	})
	if err != nil {
		return err
	}
	snap := ledger.Snapshot{Report: rep, Admissions: admissions, Grants: grants, Receipts: recs.Receipts}
	if err := ledger.Refresh(st, key, &snap, time.Now().UTC()); err != nil {
		return err
	}
	audit, err := st.TailAudit(export.DefaultMaxAudit)
	if err != nil {
		return fmt.Errorf("export: audit: %w", err)
	}
	bundle := export.Build(export.Input{
		Now:        time.Now().UTC().Format(time.RFC3339),
		Mode:       cfg.EnforcementMode,
		Key:        key,
		Snap:       snap,
		Audit:      audit,
		DiskRead:   &recs,
		Checkpoint: cp,
	})
	if err := export.Seal(key, &bundle); err != nil {
		return err
	}
	raw, err := export.MarshalJSONBytesBudget(bundle, export.DefaultMaxJSONBytes)
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	if *out == "" {
		_, err = os.Stdout.Write(raw)
		return err
	}
	return os.WriteFile(*out, raw, 0o600)
}

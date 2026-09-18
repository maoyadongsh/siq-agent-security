package main

import (
	"encoding/json"
	"errors"
	"flag"
	"io"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func cmdStateMigrate(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("state-migrate", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	confirm := fs.Bool("confirm", false, "confirm versioned backup and metadata migration")
	if e := fs.Parse(args); e != nil {
		return e
	}
	if !*confirm || fs.NArg() != 0 {
		return errors.New("请先停止本实例，使用 state-migrate --confirm 确认备份并迁移状态；不会恢复旧权限")
	}
	dir, e := state.DefaultDir()
	if e != nil {
		return e
	}
	result, e := (&state.Store{Dir: dir}).MigrateState(Version)
	if e != nil {
		return e
	}
	return json.NewEncoder(out).Encode(result)
}
func cmdStateStatus(args []string, out io.Writer) error {
	if len(args) != 0 {
		return errors.New("state-status: no arguments expected")
	}
	dir, e := state.DefaultDir()
	if e != nil {
		return e
	}
	c, e := state.CheckStateCompatibility(dir)
	// Diagnosis must include the same ancestor barriers that protect file I/O.
	// A compatible inner instance must not hide an incompatible outer marker.
	if ancestorErr := stateformat.RequirePath(dir, true); e == nil && ancestorErr != nil {
		e = ancestorErr
		c.Status = state.CompatStatusCorrupt
		if errors.Is(ancestorErr, stateformat.ErrFuture) {
			c.Status = state.CompatStatusFuture
		}
	}
	result := map[string]any{"schema": "local-state-status/v1", "compatible": e == nil, "status": c.Status, "format_version": c.Format, "reader_version": stateformat.ReaderVersion, "writer_version": stateformat.WriterVersion}
	if e != nil {
		result["recovery"] = stateformat.RecoveryMessageFor(e)
	}
	return json.NewEncoder(out).Encode(result)
}

func cmdStateEnableWindowsResources(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("state-enable-windows-resources", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	confirm := fs.Bool("confirm", false, "confirm Windows resource compatibility activation")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if !*confirm || fs.NArg() != 0 {
		return errors.New("使用 state-enable-windows-resources --confirm 明确确认状态版本升级；不会批准已有或新增授权")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	if err := prepareWindowsProfileIdentity(dir); err != nil {
		return err
	}
	status, err := (&state.Store{Dir: dir}).ActivateWindowsProfile(true, Version)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(map[string]any{"schema": "local-state-windows-profile-result/v1", "status": status, "filesystem_profile": stateformat.WindowsResourceProfile, "min_reader": 3, "min_writer": 3})
}

func checkUpgradeForCurrentState(manifest, binary string) (string, error) {
	dir, e := state.DefaultDir()
	if e != nil {
		return "", e
	}
	return clientrelease.CheckUpgradeForState(dir, manifest, binary)
}

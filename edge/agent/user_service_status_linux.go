//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

var errUserServiceStatus = errors.New("user_service_status_unavailable; no service changes made")

type userServiceStatus struct {
	SchemaVersion      string `json:"schema_version"`
	Unit               string `json:"unit"`
	LoadState          string `json:"load_state"`
	ActiveState        string `json:"active_state"`
	UnitFileState      string `json:"unit_file_state"`
	HeartbeatVerified  bool   `json:"heartbeat_verified"`
	DiscoveryVerified  bool   `json:"discovery_verified"`
	ProtectionVerified bool   `json:"protection_verified"`
}

type serviceStatusBuffer struct{ bytes.Buffer }

func (b *serviceStatusBuffer) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 4096 {
		return 0, errUserServiceStatus
	}
	return b.Buffer.Write(p)
}

func readUserServiceStatus(ctx context.Context, run func(context.Context, ...string) ([]byte, error)) (userServiceStatus, error) {
	result := userServiceStatus{SchemaVersion: "enterprise-user-service-status/v1", Unit: enterpriseUnitName}
	if ctx.Err() != nil {
		return result, errUserServiceStatus
	}
	raw, err := run(ctx, "--user", "show", "--no-pager", "--property=LoadState,ActiveState,UnitFileState", enterpriseUnitName)
	if err != nil || ctx.Err() != nil || len(raw) > 4096 {
		return result, errUserServiceStatus
	}
	values := map[string]string{}
	for _, line := range strings.Split(strings.TrimSuffix(string(raw), "\n"), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return result, errUserServiceStatus
		}
		if _, exists := values[key]; exists {
			return result, errUserServiceStatus
		}
		switch key {
		case "LoadState", "ActiveState", "UnitFileState":
			values[key] = value
		default:
			return result, errUserServiceStatus
		}
	}
	if len(values) != 3 {
		return result, errUserServiceStatus
	}
	// Never print unexpected manager output (paths, injected fields, diagnostics).
	known := func(value string, allowed ...string) string {
		for _, item := range allowed {
			if value == item {
				return value
			}
		}
		return "unknown"
	}
	result.LoadState = known(values["LoadState"], "loaded", "not-found", "error", "masked", "bad-setting", "stub", "merged")
	result.ActiveState = known(values["ActiveState"], "active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance", "refreshing")
	result.UnitFileState = known(values["UnitFileState"], "enabled", "enabled-runtime", "disabled", "static", "indirect", "masked", "masked-runtime", "linked", "linked-runtime", "generated", "transient", "alias", "bad")
	return result, nil
}

const userServiceStatusHelp = "user-service-status\n" +
	"Read-only diagnostic: shows LoadState/ActiveState/UnitFileState of the fixed per-user\n" +
	"siq-edge-discovery.service via /usr/bin/systemctl --user. No options, unit or scope\n" +
	"arguments; never starts, stops, reloads or registers anything. active is service-manager\n" +
	"state only, not proof of control-plane connectivity, completed discovery or runtime protection.\n"

func cmdUserServiceStatus(ctx context.Context, args []string) error {
	return runUserServiceStatus(ctx, args, os.Stdout, func(ctx context.Context, args ...string) ([]byte, error) {
		cmd := exec.CommandContext(ctx, "/usr/bin/systemctl", args...)
		var output serviceStatusBuffer
		cmd.Stdout = &output
		cmd.Stderr = io.Discard
		cmd.WaitDelay = time.Second
		err := cmd.Run()
		return output.Bytes(), err
	})
}

func runUserServiceStatus(ctx context.Context, args []string, stdout io.Writer, run func(context.Context, ...string) ([]byte, error)) error {
	fs := flag.NewFlagSet("user-service-status", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, e := io.WriteString(stdout, userServiceStatusHelp)
			return e
		}
		return errUserServiceStatus
	}
	if fs.NArg() != 0 {
		return errUserServiceStatus
	}
	bounded, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	status, err := readUserServiceStatus(bounded, run)
	if err != nil {
		return err
	}
	return json.NewEncoder(stdout).Encode(status)
}

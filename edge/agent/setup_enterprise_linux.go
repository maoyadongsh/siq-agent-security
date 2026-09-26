//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

var errEnterpriseSetup = errors.New("enterprise_setup_invalid; preserve local installation state")

type setupActions struct {
	prepare  func() (string, error)
	register func() error
	recover  func() error
	confirm  func() error
	schedule func() error
	install  func(string) error
}

func runEnterpriseSetup(ctx context.Context, kind string, start bool, output io.Writer, actions setupActions) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if kind != "new" && kind != "pending" && kind != "registered" {
		return errEnterpriseSetup
	}
	emit := func(phase, status, path string) error {
		return json.NewEncoder(output).Encode(struct {
			Phase  string `json:"phase"`
			Status string `json:"status"`
			Stage  string `json:"stage_path,omitempty"`
		}{phase, status, path})
	}
	path, err := actions.prepare()
	if err != nil || path == "" {
		return errors.New("enterprise_setup_failed_at_prepare")
	}
	if emit("prepare", "staged_only", path) != nil {
		return errors.New("enterprise_setup_progress_write_failed")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	switch kind {
	case "new":
		if actions.register() != nil {
			return errors.New("enterprise_setup_failed_at_register")
		}
	case "pending":
		if actions.recover() != nil {
			return errors.New("enterprise_setup_failed_at_recover")
		}
	}
	if emit("identity", "registered_only", "") != nil {
		return errors.New("enterprise_setup_progress_write_failed")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if actions.confirm() != nil {
		return errors.New("enterprise_setup_failed_at_consent")
	}
	if emit("consent", "discovery_scope_saved", "") != nil {
		return errors.New("enterprise_setup_progress_write_failed")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if actions.schedule != nil {
		if err := actions.schedule(); err != nil {
			// Forward only locally defined recovery categories, never upstream text.
			for _, known := range []error{errScheduleConfirmationUnknown, errScheduleReceiptUnstored} {
				if errors.Is(err, known) {
					return fmt.Errorf("enterprise_setup_failed_at_schedule; service installation not attempted: %w", known)
				}
			}
			return errors.New("enterprise_setup_failed_at_schedule; service installation not attempted; preserve state and inspect confirmation stage before retry; do not delete journals")
		}
		if emit("schedule", "confirmation_acknowledged_only", "") != nil {
			return errors.New("enterprise_setup_progress_write_failed")
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
	}
	if actions.install(path) != nil {
		return errors.New("enterprise_setup_failed_at_service")
	}
	status := "configured_only"
	if start {
		status = "service_active_only"
	}
	if emit("service", status, path) != nil {
		return errors.New("enterprise_setup_progress_write_failed")
	}
	return nil
}

func cmdSetupEnterprise(ctx context.Context, args []string) error {
	return setupEnterprise(ctx, args, os.Stdout)
}

func setupEnterprise(ctx context.Context, args []string, output io.Writer) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	var o prepareOptions
	fs := flag.NewFlagSet("setup-enterprise", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&o.plan, "plan", "", "")
	fs.StringVar(&o.release, "release", "", "")
	fs.StringVar(&o.bundle, "bundle", "", "")
	fs.StringVar(&o.parent, "staging-parent", "", "")
	fs.StringVar(&o.resume, "resume-stage", "", "")
	fs.StringVar(&o.tenant, "tenant", "", "")
	fs.StringVar(&o.environment, "environment", "", "")
	fs.StringVar(&o.origin, "control-plane", "", "")
	fs.StringVar(&o.confirmation, "confirm-plan-sha256", "", "")
	stdinCode := fs.Bool("enrollment-code-stdin", false, "")
	start := fs.Bool("start", false, "")
	reviewOnly := fs.Bool("review-only", false, "")
	interactive := fs.Bool("interactive", false, "")
	scheduleID := fs.String("schedule-id", "", "")
	scheduleDigest := fs.String("confirm-schedule-sha256", "", "")
	resumeSchedule := fs.Bool("resume-schedule", false, "")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, err = io.WriteString(output, "setup-enterprise --plan FILE --release FILE (--bundle DIR --staging-parent PRIVATE_DIR | --resume-stage DIR) --tenant ID --environment ID --control-plane ORIGIN (--interactive | --confirm-plan-sha256 DIGEST [--enrollment-code-stdin]) [--start]\nRead-only preview: --review-only --plan FILE --tenant ID --environment ID --control-plane ORIGIN [--start]\nInteractive mode requires a terminal, shows scope, defaults to cancel, and hides enrollment input. Default configures only; --start enables discovery service, never business permissions.\n")
			if err == nil {
				_, err = io.WriteString(output, "Optional existing-device schedule: (--schedule-id ID | --resume-schedule) with --confirm-schedule-sha256 DIGEST, or --interactive for a separate periodic consent prompt. Not supported with --review-only. Schedule failure stops before service installation.\n")
			}
			return err
		}
		return errEnterpriseSetup
	}
	if fs.NArg() != 0 {
		return errEnterpriseSetup
	}
	var scheduleAction func() error
	if *scheduleID != "" || *scheduleDigest != "" || *resumeSchedule {
		args, err := setupScheduleArgs(*scheduleID, *scheduleDigest, *resumeSchedule, *interactive)
		if *reviewOnly || err != nil {
			return errEnterpriseSetup
		}
		scheduleAction = func() error {
			return confirmSchedule(ctx, args, output, time.Now().UTC(), func(ctx context.Context, state *State, body DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
				return newAuthedClient(state).ConfirmDiscoverySchedule(ctx, body)
			})
		}
	}
	if *interactive && (*reviewOnly || *stdinCode || o.confirmation != "") {
		return errEnterpriseSetup
	}
	raw, err := readInstallDocument(o.plan)
	if err != nil {
		return errEnterpriseSetup
	}
	h := sha256.Sum256(raw)
	p, err := installplan.Parse(raw)
	if err != nil || p.ServiceMode != "user" || p.RequireCurrent(time.Now().UTC(), o.tenant, o.environment, o.origin, runtime.GOARCH) != nil {
		return errEnterpriseSetup
	}
	if *reviewOnly {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		encoder := json.NewEncoder(output)
		encoder.SetIndent("", "  ")
		if encoder.Encode(struct {
			Schema               string            `json:"schema_version"`
			Status               string            `json:"status"`
			Confirmation         string            `json:"confirmation_sha256"`
			StartService         bool              `json:"start_service"`
			SignatureVerified    bool              `json:"release_signature_verified"`
			RequiresConfirmation bool              `json:"requires_explicit_confirmation"`
			BusinessPermissions  bool              `json:"business_permissions_granted"`
			Plan                 *installplan.Plan `json:"plan"`
			Notice               string            `json:"notice"`
		}{"enterprise-install-review/v1", "review_only", hex.EncodeToString(h[:]), *start, false, true, false, p, "请核对组织、环境、采集目录和文件后再确认。此预览未验签制品、未注册设备、未启动扫描，也不授予智能体业务权限。"}) != nil {
			return errors.New("enterprise_setup_progress_write_failed")
		}
		return nil
	}
	if *interactive {
		if _, err := terminalState(os.Stdin); err != nil {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := printInstallHostSummary(output, inspectLinuxHost()); err != nil {
			return errors.New("enterprise_setup_progress_write_failed")
		}
		if err := confirmInteractivePlan(ctx, os.Stdin, output, p, *start); err != nil {
			return err
		}
		current, err := readInstallDocument(o.plan)
		if err != nil || !bytes.Equal(current, raw) {
			return errors.New("enterprise_setup_plan_changed")
		}
		if p.RequireCurrent(time.Now().UTC(), o.tenant, o.environment, o.origin, runtime.GOARCH) != nil {
			return errEnterpriseSetup
		}
		o.confirmation = hex.EncodeToString(h[:])
		*stdinCode = true
	}
	if hex.EncodeToString(h[:]) != o.confirmation {
		return errEnterpriseSetup
	}
	kind, err := setupIdentityKind(o.origin, o.environment)
	if err != nil || (kind == "new" && !*stdinCode) {
		return errEnterpriseSetup
	}
	// Organization-created schedules are bound to an already registered device.
	// Do not partially register a new identity before discovering an unusable ID.
	if scheduleAction != nil && kind != "registered" {
		return errEnterpriseSetup
	}
	prepareArgs := []string{"--plan", o.plan, "--release", o.release, "--tenant", o.tenant, "--environment", o.environment, "--control-plane", o.origin, "--confirm-plan-sha256", o.confirmation}
	if o.resume != "" {
		if o.bundle != "" || o.parent != "" {
			return errEnterpriseSetup
		}
		prepareArgs = append(prepareArgs, "--resume-stage", o.resume)
	} else {
		prepareArgs = append(prepareArgs, "--bundle", o.bundle, "--staging-parent", o.parent)
	}
	var actualCapabilities map[string]any
	return runEnterpriseSetup(ctx, kind, *start, output, setupActions{
		prepare: func() (string, error) {
			var out bytes.Buffer
			if err := prepareInstall(prepareArgs, &out, time.Now().UTC(), runtime.GOARCH, installplan.StageBundle, installplan.VerifyStagedBundle); err != nil {
				return "", err
			}
			var result struct {
				Stage string `json:"stage_path"`
			}
			if json.Unmarshal(out.Bytes(), &result) != nil || result.Stage == "" {
				return "", errEnterpriseSetup
			}
			actualCapabilities, err = installedCapabilities(ctx, result.Stage, p, probeInstalledConnector)
			if err != nil {
				// Keep the recovery location visible even when capability validation
				// fails after successful staging. No identity action has started.
				if json.NewEncoder(output).Encode(struct {
					Phase  string `json:"phase"`
					Status string `json:"status"`
					Stage  string `json:"stage_path"`
				}{"prepare", "capabilities_unverified", result.Stage}) != nil {
					return "", errors.New("enterprise_setup_progress_write_failed")
				}
				return "", err
			}
			return result.Stage, nil
		},
		register: func() error {
			if *interactive {
				return registerWithCapabilitiesInput(ctx, []string{"--control-plane", o.origin, "--environment", o.environment, "--enrollment-code-stdin"}, actualCapabilities, func(ctx context.Context) (string, error) {
					return readInteractiveEnrollment(ctx, os.Stdin, output)
				})
			}
			return registerWithCapabilities(ctx, []string{"--control-plane", o.origin, "--environment", o.environment, "--enrollment-code-stdin"}, actualCapabilities)
		},
		recover: func() error {
			return cmdRecoverRegistration(ctx, []string{"--control-plane", o.origin, "--environment", o.environment})
		},
		confirm: func() error {
			return cmdConfirmDiscovery([]string{"--plan", o.plan, "--tenant", o.tenant, "--confirm-plan-sha256", o.confirmation})
		},
		schedule: scheduleAction,
		install: func(path string) error {
			args := []string{"--release", o.release, "--stage", path}
			if *start {
				args = append(args, "--start")
			}
			return cmdInstallUserService(ctx, args)
		},
	})
}

// The installation-scope answer is never reused as periodic consent. Interactive
// mode delegates to a second, complete intent display and prompt.
func setupScheduleArgs(id, digest string, resume, interactive bool) ([]string, error) {
	if resume == (id != "") || (id != "" && !regexp.MustCompile(`^eds-[a-f0-9]{32}$`).MatchString(id)) {
		return nil, errEnterpriseSetup
	}
	var args []string
	if interactive {
		if digest != "" {
			return nil, errEnterpriseSetup
		}
		args = []string{"--interactive"}
	} else {
		if !regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(digest) {
			return nil, errEnterpriseSetup
		}
		args = []string{"--confirm-intent-sha256", digest}
	}
	if resume {
		return append(args, "--resume"), nil
	}
	return append(args, "--schedule-id", id), nil
}

func setupIdentityKind(origin, environment string) (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", errEnterpriseSetup
	}
	path := filepath.Join(dir, "state.json")
	if _, err := os.Lstat(path); err == nil {
		var state State
		if readPrivateJSON(path, &state, installplan.MaxBytes+8192) != nil || state.Secret == "" || state.DeviceIdentity == "" || state.ControlPlaneURL != origin || state.EnvironmentID != environment {
			return "", errEnterpriseSetup
		}
		return "registered", nil
	} else if !os.IsNotExist(err) {
		return "", errEnterpriseSetup
	}
	path = filepath.Join(dir, "registration-pending.json")
	if _, err := os.Lstat(path); err == nil {
		var pending pendingRegistration
		if readRecoveryFile(path, &pending) != nil || pending.Schema != "edge-registration-pending/v1" || pending.ControlPlane != origin || (pending.ExpectedEnvironment != "" && pending.ExpectedEnvironment != environment) {
			return "", errEnterpriseSetup
		}
		return "pending", nil
	} else if !os.IsNotExist(err) {
		return "", errEnterpriseSetup
	}
	return "new", nil
}

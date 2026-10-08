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
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

var errUpgradeApply = errors.New("enterprise_upgrade_not_completed; preserve state and pending journal; inspect service and signed sources before explicit recovery")
var errUpgradeStopped = errors.New("enterprise_upgrade_requires_stopped_unmodified_user_service; no automatic stop or start")
var errUpgradeProtocol = errors.New("enterprise_upgrade_source_lacks_verified_recovery_protocol; use compatible signed sources")

type upgradeCapabilities struct {
	Schema       string `json:"schema_version"`
	Version      string `json:"version"`
	Pending      string `json:"pending_protocol"`
	Confirmation string `json:"confirmation_protocol"`
	TaskLock     bool   `json:"task_lock"`
}

func expectedUpgradeCapabilities(version string) upgradeCapabilities {
	return upgradeCapabilities{"enterprise-upgrade-capabilities/v1", version, "enterprise-upgrade-pending/v1", "enterprise-upgrade-intent/v1", true}
}
func cmdUpgradeCapabilities(args []string) error {
	if len(args) != 0 {
		return errUpgradeProtocol
	}
	return json.NewEncoder(os.Stdout).Encode(expectedUpgradeCapabilities(agentVersion))
}

type upgradeCompletion struct {
	Schema              string         `json:"schema_version"`
	Status              string         `json:"status"`
	Direction           string         `json:"direction"`
	Journal             upgradeJournal `json:"journal"`
	StateHash           string         `json:"state_sha256"`
	UnitHash            string         `json:"unit_sha256"`
	ServiceStarted      bool           `json:"service_started"`
	BusinessPermissions bool           `json:"business_permissions_granted"`
}

// Per-call seams are private to tests. The CLI never takes a key, service
// command, verifier result or failure hook from flags/environment.
type upgradeApplyDeps struct {
	now        func() time.Time
	verify     upgradeStageVerifier
	probe      func(context.Context, upgradeSide) error
	manager    func(context.Context, ...string) ([]byte, error)
	checkpoint func(string) error
}

func realUpgradeDeps() upgradeApplyDeps {
	return upgradeApplyDeps{time.Now, installplan.VerifyStagedBundle, probeUpgradeSource, runUpgradeManager, func(string) error { return nil }}
}
func runUpgradeManager(ctx context.Context, args ...string) ([]byte, error) {
	bounded, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(bounded, "/usr/bin/systemctl", args...)
	cmd.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	for _, key := range []string{"HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"} {
		if value, ok := os.LookupEnv(key); ok {
			cmd.Env = append(cmd.Env, key+"="+value)
		}
	}
	var output serviceStatusBuffer
	cmd.Stdout = &output
	cmd.Stderr = io.Discard
	cmd.WaitDelay = time.Second
	err := cmd.Run()
	return output.Bytes(), err
}
func requireUpgradeStopped(ctx context.Context, unit string, clean bool, run func(context.Context, ...string) ([]byte, error)) error {
	if ctx.Err() != nil {
		return errUpgradeStopped
	}
	raw, err := run(ctx, "--user", "show", "--no-pager", "--property=LoadState,ActiveState,SubState,MainPID,ControlPID,FragmentPath,DropInPaths,NeedDaemonReload", enterpriseUnitName)
	if err != nil || ctx.Err() != nil || len(raw) > 4096 {
		return errUpgradeStopped
	}
	fields := map[string]string{}
	for _, line := range strings.Split(strings.TrimSuffix(string(raw), "\n"), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return errUpgradeStopped
		}
		if _, ok := fields[key]; ok {
			return errUpgradeStopped
		}
		fields[key] = value
	}
	if len(fields) != 8 || fields["LoadState"] != "loaded" || fields["MainPID"] != "0" || fields["ControlPID"] != "0" || fields["FragmentPath"] != unit || fields["DropInPaths"] != "" ||
		!((fields["ActiveState"] == "inactive" && fields["SubState"] == "dead") || (fields["ActiveState"] == "failed" && fields["SubState"] == "failed")) ||
		(fields["NeedDaemonReload"] != "no" && fields["NeedDaemonReload"] != "yes") || (clean && fields["NeedDaemonReload"] != "no") {
		return errUpgradeStopped
	}
	// Missing fields with empty values must not be confused with a real empty field.
	for _, key := range []string{"LoadState", "ActiveState", "SubState", "MainPID", "ControlPID", "FragmentPath", "DropInPaths", "NeedDaemonReload"} {
		if _, ok := fields[key]; !ok {
			return errUpgradeStopped
		}
	}
	return nil
}
func probeUpgradeSource(ctx context.Context, side upgradeSide) error {
	raw, err := readInstallDocument(filepath.Join(side.StagePath, "release.json"))
	if err != nil || installplan.VerifyStagedBundle(side.Plan, raw, side.StagePath) != nil {
		return errUpgradeProtocol
	}
	release, err := installplan.VerifyPlanRelease(side.Plan, raw)
	if err != nil {
		return errUpgradeProtocol
	}
	for _, a := range release.Artifacts {
		if a.ID != "edge-agent" || a.Arch != runtime.GOARCH || a.OS != "linux" {
			continue
		}
		return probeUpgradeProgram(ctx, filepath.Join(side.StagePath, a.Path), a.SHA256, side.Plan.ReleaseVersion)
	}
	return errUpgradeProtocol
}

func probeUpgradeProgram(ctx context.Context, path, digest, version string) error {
	file, err := openVerifiedProgram(path, "edge-agent", digest)
	if err != nil {
		return errUpgradeProtocol
	}
	defer file.Close()
	bounded, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(bounded, "/proc/self/fd/3", "upgrade-capabilities")
	cmd.ExtraFiles = []*os.File{file}
	cmd.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return os.ErrProcessDone
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	var output serviceStatusBuffer
	cmd.Stdout = &output
	cmd.Stderr = io.Discard
	cmd.WaitDelay = time.Second
	if cmd.Run() != nil || ctx.Err() != nil || !validRetirementJSON(output.Bytes()) {
		return errUpgradeProtocol
	}
	return validateUpgradeCapabilities(output.Bytes(), version)
}

func validateUpgradeCapabilities(raw []byte, version string) error {
	if !validRetirementJSON(raw) {
		return errUpgradeProtocol
	}
	if _, ok := rotationJSONFields(raw, []string{"schema_version", "version", "pending_protocol", "confirmation_protocol", "task_lock"}, true); !ok {
		return errUpgradeProtocol
	}
	var caps upgradeCapabilities
	if strictDiscoveryJSON(raw, &caps) != nil || caps != expectedUpgradeCapabilities(version) {
		return errUpgradeProtocol
	}
	return nil
}

// Atomic private replacement only after a fresh exact old-byte comparison.
// Ancestors are owner-controlled and checked by readDeviceState/readUpgradeUnit;
// same-UID/root malicious mutation remains outside the threat boundary.
func replaceUpgradeFile(path string, expected, next []byte, read func(string) ([]byte, error)) error {
	current, err := read(path)
	if err != nil || !bytes.Equal(current, expected) {
		return errUpgradeApply
	}
	if bytes.Equal(current, next) {
		return nil
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".siq-upgrade-*.tmp")
	if err != nil {
		return errUpgradeApply
	}
	defer os.Remove(file.Name())
	if n, err := file.Write(next); err != nil || n != len(next) {
		file.Close()
		return errUpgradeApply
	}
	if file.Sync() != nil {
		file.Close()
		return errUpgradeApply
	}
	if file.Close() != nil {
		return errUpgradeApply
	}
	current, err = read(path)
	if err != nil || !bytes.Equal(current, expected) {
		return errUpgradeApply
	}
	if os.Rename(file.Name(), path) != nil || syncRegistrationDirectory(filepath.Dir(path)) != nil {
		return errUpgradeApply
	}
	return nil
}
func completionPath(j *upgradeJournal) string {
	return filepath.Join(filepath.Dir(j.Intent.StatePath), "enterprise-upgrade-completed-"+j.Confirmation+".json")
}
func writeUpgradeCompletion(path string, body []byte) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, os.ErrExist) {
		raw, e := readDeviceState(path)
		if e != nil || !bytes.Equal(raw, body) {
			return errUpgradeApply
		}
		file, e := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
		if e != nil {
			return errUpgradeApply
		}
		syncErr := file.Sync()
		closeErr := file.Close()
		if syncErr != nil || closeErr != nil {
			return errUpgradeApply
		}
		return syncRegistrationDirectory(filepath.Dir(path))
	}
	if err != nil {
		return errUpgradeApply
	}
	n, e := file.Write(body)
	syncErr := file.Sync()
	closeErr := file.Close()
	if e != nil || n != len(body) || syncErr != nil || closeErr != nil || syncRegistrationDirectory(filepath.Dir(path)) != nil {
		return errUpgradeApply
	}
	raw, err := readDeviceState(path)
	if err != nil || !bytes.Equal(raw, body) {
		return errUpgradeApply
	}
	return nil
}

func upgradePreflight(ctx context.Context, j *upgradeJournal, d upgradeApplyDeps) error {
	if requireUpgradeStopped(ctx, j.Intent.UnitPath, false, d.manager) != nil {
		return errUpgradeStopped
	}
	for _, side := range []upgradeSide{j.Intent.From, j.Intent.To} {
		if d.probe(ctx, side) != nil {
			return errUpgradeProtocol
		}
	}
	return nil
}

// Caller owns the raw task lock. Every error before pending removal leaves a
// durable stop marker; there is no in-memory rollback pretending to be recovery.
func finishUpgrade(ctx context.Context, j *upgradeJournal, direction string, d upgradeApplyDeps) (*upgradeCompletion, error) {
	if direction != "target" && direction != "previous" {
		return nil, errUpgradeApply
	}
	state, err := j.inspect(ctx, d.verify)
	if err != nil {
		return nil, err
	}
	side, plan := j.Intent.From, j.OriginalPlan
	if direction == "target" {
		side = j.Intent.To
		plan, err = json.Marshal(side.Plan)
		if err != nil {
			return nil, errUpgradeApply
		}
	}
	nextState, err := upgradeStateBytes(state, plan)
	if err != nil {
		return nil, err
	}
	nextUnit, err := upgradeUnit(side.StagePath, filepath.Dir(j.Intent.StatePath))
	if err != nil {
		return nil, errUpgradeApply
	}
	result := &upgradeCompletion{Schema: "enterprise-upgrade-completed/v1", Status: "configured_not_started", Direction: direction, Journal: *j, StateHash: upgradeDigest(nextState), UnitHash: upgradeDigest(nextUnit)}
	body, err := json.Marshal(result)
	if err != nil {
		return nil, errUpgradeApply
	}
	archive := completionPath(j)
	committed := false
	if _, err := os.Lstat(archive); err == nil {
		raw, e := readDeviceState(archive)
		actualState, se := readDeviceState(j.Intent.StatePath)
		actualUnit, ue := readUpgradeUnit(j.Intent.UnitPath)
		if e != nil || se != nil || ue != nil || !bytes.Equal(raw, body) || !bytes.Equal(actualState, nextState) || !bytes.Equal(actualUnit, nextUnit) {
			return nil, errUpgradeApply
		}
		committed = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, errUpgradeApply
	}
	validate := func() error {
		stored, e := readUpgradeJournal(ctx, d.verify)
		if e != nil || !reflect.DeepEqual(stored, j) {
			return errUpgradeApply
		}
		if direction == "target" && !committed && side.Plan.RequireCurrent(d.now(), j.Intent.TenantID, j.Intent.EnvironmentID, j.Intent.ControlPlaneOrigin, runtime.GOARCH) != nil {
			return errUpgradeWindow
		}
		if err := upgradePreflight(ctx, j, d); err != nil {
			return err
		}
		stored, e = readUpgradeJournal(ctx, d.verify)
		if e != nil || !reflect.DeepEqual(stored, j) {
			return errUpgradeApply
		}
		if direction == "target" && !committed && side.Plan.RequireCurrent(d.now(), j.Intent.TenantID, j.Intent.EnvironmentID, j.Intent.ControlPlaneOrigin, runtime.GOARCH) != nil {
			return errUpgradeWindow
		}
		return nil
	}
	if err := validate(); err != nil {
		return nil, err
	}
	current, err := readDeviceState(j.Intent.StatePath)
	if err != nil {
		return nil, errUpgradeApply
	}
	if replaceUpgradeFile(j.Intent.StatePath, current, nextState, readDeviceState) != nil {
		return nil, errUpgradeApply
	}
	if d.checkpoint("state") != nil {
		return nil, errUpgradeApply
	}
	if err := validate(); err != nil {
		return nil, err
	}
	current, err = readUpgradeUnit(j.Intent.UnitPath)
	if err != nil {
		return nil, errUpgradeApply
	}
	if replaceUpgradeFile(j.Intent.UnitPath, current, nextUnit, readUpgradeUnit) != nil {
		return nil, errUpgradeApply
	}
	if d.checkpoint("unit") != nil {
		return nil, errUpgradeApply
	}
	if err := validate(); err != nil {
		return nil, err
	}
	if _, err := d.manager(ctx, "--user", "daemon-reload"); err != nil || ctx.Err() != nil {
		return nil, errUpgradeApply
	}
	if d.checkpoint("reload") != nil {
		return nil, errUpgradeApply
	}
	if err := validate(); err != nil {
		return nil, err
	}
	if requireUpgradeStopped(ctx, j.Intent.UnitPath, true, d.manager) != nil {
		return nil, errUpgradeStopped
	}
	actualState, se := readDeviceState(j.Intent.StatePath)
	actualUnit, ue := readUpgradeUnit(j.Intent.UnitPath)
	if se != nil || ue != nil || !bytes.Equal(actualState, nextState) || !bytes.Equal(actualUnit, nextUnit) {
		return nil, errUpgradeApply
	}
	if writeUpgradeCompletion(archive, body) != nil {
		return nil, errUpgradeApply
	}
	if d.checkpoint("archive") != nil {
		return nil, errUpgradeApply
	}
	if err := validate(); err != nil {
		return nil, err
	}
	if requireUpgradeStopped(ctx, j.Intent.UnitPath, true, d.manager) != nil {
		return nil, errUpgradeStopped
	}
	actualState, se = readDeviceState(j.Intent.StatePath)
	actualUnit, ue = readUpgradeUnit(j.Intent.UnitPath)
	archived, ae := readDeviceState(archive)
	if se != nil || ue != nil || ae != nil || !bytes.Equal(actualState, nextState) || !bytes.Equal(actualUnit, nextUnit) || !bytes.Equal(archived, body) || ctx.Err() != nil {
		return nil, errUpgradeApply
	}
	if os.Remove(filepath.Join(filepath.Dir(j.Intent.StatePath), upgradePendingName)) != nil {
		return nil, errUpgradeApply
	}
	if d.checkpoint("unlink") != nil || syncRegistrationDirectory(filepath.Dir(j.Intent.StatePath)) != nil {
		return nil, errUpgradeApply
	}
	return result, nil
}

func runUpgradeApply(ctx context.Context, args []string, recover bool, output io.Writer, d upgradeApplyDeps) error {
	if d.now == nil || d.verify == nil || d.probe == nil || d.manager == nil || d.checkpoint == nil {
		return errUpgradeApply
	}
	name := "apply-enterprise-upgrade"
	if recover {
		name = "recover-enterprise-upgrade"
	}
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	confirm := fs.String("confirm-upgrade-sha256", "", "")
	var o upgradeReviewOptions
	direction := "target"
	if recover {
		fs.StringVar(&direction, "direction", "", "")
	} else {
		fs.StringVar(&o.plan, "plan", "", "")
		fs.StringVar(&o.from, "from-stage", "", "")
		fs.StringVar(&o.to, "to-stage", "", "")
		fs.StringVar(&o.tenant, "tenant", "", "")
	}
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, err = io.WriteString(output, name+" --confirm-upgrade-sha256 DIGEST "+map[bool]string{true: "--direction target|previous", false: "--plan FILE --from-stage DIR --to-stage DIR --tenant ID"}[recover]+"\nRequires an already stopped user service and compatible signed Edge sources. Changes configuration only; never starts a service or grants business permissions.\n")
			return err
		}
		return errUpgradeApply
	}
	if fs.NArg() != 0 || len(*confirm) != 64 || (direction != "target" && direction != "previous") || ctx.Err() != nil {
		return errUpgradeApply
	}
	unlock, err := acquireRawTaskLock()
	if err != nil {
		return err
	}
	defer unlock()
	var j *upgradeJournal
	if recover {
		j, err = readUpgradeJournal(ctx, d.verify)
		if err != nil || j.Confirmation != *confirm {
			return errUpgradeApply
		}
	} else {
		if requireNoUpgradePending() != nil {
			return errUpgradePending
		}
		review, e := inspectUpgrade(ctx, o, d.now, d.verify)
		if e != nil || review.Confirmation != *confirm {
			return errUpgradeApply
		}
		preview := &upgradeJournal{Intent: review.Intent}
		if e := upgradePreflight(ctx, preview, d); e != nil {
			return e
		}
		if requireUpgradeStopped(ctx, review.Intent.UnitPath, true, d.manager) != nil {
			return errUpgradeStopped
		}
		j, err = prepareUpgradeJournal(ctx, o, *confirm, d.now, d.verify)
		if err != nil {
			return err
		}
	}
	result, err := finishUpgrade(ctx, j, direction, d)
	if err != nil {
		return err
	}
	raw, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return errUpgradeApply
	}
	raw = append(raw, '\n')
	if n, err := output.Write(raw); err != nil || n != len(raw) {
		return errUpgradeApply
	}
	return nil
}
func cmdApplyEnterpriseUpgrade(ctx context.Context, args []string) error {
	return runUpgradeApply(ctx, args, false, os.Stdout, realUpgradeDeps())
}
func cmdRecoverEnterpriseUpgrade(ctx context.Context, args []string) error {
	return runUpgradeApply(ctx, args, true, os.Stdout, realUpgradeDeps())
}

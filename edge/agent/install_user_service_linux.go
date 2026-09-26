//go:build linux

package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

const enterpriseUnitName = "siq-edge-discovery.service"

var errUserServiceInstall = errors.New("user_service_install_failed; preserve existing state and staged files")
var errUserServiceSchedule = errors.New("user_service_schedule_unconfirmed; recover the original discovery confirmation before installing the service")
var errUserServicePlanWindow = errors.New("user_service_install_plan_outside_window; obtain and explicitly confirm a current installation plan; preserve device identity and staged files")

func cmdInstallUserService(ctx context.Context, args []string) error {
	if ctx.Err() != nil {
		return errUserServiceInstall
	}
	fs := flag.NewFlagSet("install-user-service", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	releasePath := fs.String("release", "", "")
	stage := fs.String("stage", "", "")
	start := fs.Bool("start", false, "")
	if fs.Parse(args) != nil || fs.NArg() != 0 {
		return errUserServiceInstall
	}
	if ctx.Err() != nil {
		return errUserServiceInstall
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errUserServiceInstall
	}
	locked := true
	defer func() {
		if locked {
			unlock()
		}
	}()
	path, err := StateFilePath()
	if err != nil {
		return errUserServiceInstall
	}
	var state State
	if readPrivateJSON(path, &state, installplan.MaxBytes+8192) != nil || state.Secret == "" || state.DeviceIdentity == "" {
		return errUserServiceInstall
	}
	// Validate exactly the same durable consent that serve will load before
	// writing a unit or invoking systemd. Building the callback performs no I/O
	// beyond reading consent; it is deliberately not executed during install.
	if _, err := scheduledHeartbeat(&state, nil, func(context.Context) error { return nil }); err != nil {
		return errUserServiceSchedule
	}
	p, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil || p.ServiceMode != "user" || p.EnvironmentID != state.EnvironmentID || p.ControlPlaneOrigin != state.ControlPlaneURL || p.TargetArch != runtime.GOARCH {
		return errUserServiceInstall
	}
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return errUserServiceInstall
	}
	if p.RequireCurrent(time.Now().UTC(), p.TenantID, state.EnvironmentID, state.ControlPlaneURL, runtime.GOARCH) != nil {
		return errUserServicePlanWindow
	}
	release, err := readInstallDocument(*releasePath)
	if err != nil || installplan.VerifyStagedBundle(*p, release, *stage) != nil {
		return errUserServiceInstall
	}
	dir, err := StateDir()
	if err != nil {
		return errUserServiceInstall
	}
	binDir := filepath.Join(*stage, "bin", p.TargetArch)
	unit, err := renderUserService(filepath.Join(binDir, "edge-agent"), dir, binDir)
	if err != nil {
		return errUserServiceInstall
	}
	config, err := os.UserConfigDir()
	if err != nil {
		return errUserServiceInstall
	}
	if ctx.Err() != nil {
		return errUserServiceInstall
	}
	if err := writeUserUnit(filepath.Join(config, "systemd", "user"), []byte(unit)); err != nil {
		return errUserServiceInstall
	}
	// serve takes this same lock; release before asking systemd to start it.
	unlock()
	locked = false
	if ctx.Err() != nil {
		return errUserServiceInstall
	}
	if *start {
		if err := activateUserUnit(ctx, func(ctx context.Context, args ...string) error {
			bounded, cancel := context.WithTimeout(ctx, 20*time.Second)
			defer cancel()
			// No shell, PATH discovery, sudo, linger, system scope or raw output.
			return exec.CommandContext(bounded, "/usr/bin/systemctl", args...).Run()
		}); err != nil {
			return errUserServiceInstall
		}
	}
	return nil
}

func activateUserUnit(ctx context.Context, run func(context.Context, ...string) error) error {
	for _, args := range [][]string{{"--user", "daemon-reload"}, {"--user", "enable", "--now", enterpriseUnitName}, {"--user", "is-active", "--quiet", enterpriseUnitName}} {
		if ctx.Err() != nil {
			return errUserServiceInstall
		}
		if run(ctx, args...) != nil || ctx.Err() != nil {
			return errUserServiceInstall
		}
	}
	return nil
}

// No replacement of differing existing units. Identical retries are safe, and
// service-manager failure leaves this configuration intact for retry. The user
// controls stable ancestors; this does not defend against same-user/root writes.
func writeUserUnit(dir string, body []byte) error {
	if !filepath.IsAbs(dir) || filepath.Clean(dir) != dir || dir == "/" {
		return errUserServiceInstall
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return errUserServiceInstall
	}
	for _, part := range strings.Split(strings.TrimPrefix(dir, "/"), "/") {
		next, e := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if e == syscall.ENOENT {
			if e = syscall.Mkdirat(fd, part, 0700); e == nil || e == syscall.EEXIST {
				next, e = syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
			}
		}
		syscall.Close(fd)
		if e != nil {
			return errUserServiceInstall
		}
		fd = next
		var ancestor syscall.Stat_t
		if syscall.Fstat(fd, &ancestor) != nil ||
			(int(ancestor.Uid) != os.Geteuid() && ancestor.Uid != 0) ||
			(ancestor.Mode&0022 != 0 && !(ancestor.Uid == 0 && ancestor.Mode&syscall.S_ISVTX != 0)) {
			syscall.Close(fd)
			return errUserServiceInstall
		}
	}
	defer syscall.Close(fd)
	var st syscall.Stat_t
	if syscall.Fstat(fd, &st) != nil || int(st.Uid) != os.Geteuid() || st.Mode&0022 != 0 {
		return errUserServiceInstall
	}
	final := filepath.Join(dir, enterpriseUnitName)
	if _, err := os.Lstat(final); err == nil {
		if sameUserUnit(final, body) != nil || syscall.Fsync(fd) != nil {
			return errUserServiceInstall
		}
		return nil
	} else if !os.IsNotExist(err) {
		return errUserServiceInstall
	}
	f, err := os.CreateTemp(dir, ".siq-unit-*.tmp")
	if err != nil {
		return errUserServiceInstall
	}
	defer os.Remove(f.Name()) // Only the temporary file created by this call.
	if n, err := f.Write(body); err != nil || n != len(body) {
		f.Close()
		return errUserServiceInstall
	}
	if f.Sync() != nil {
		f.Close()
		return errUserServiceInstall
	}
	if f.Close() != nil {
		return errUserServiceInstall
	}
	// Link is atomic and never overwrites a concurrently installed unit.
	if err := os.Link(f.Name(), final); err != nil {
		if os.IsExist(err) {
			return sameUserUnit(final, body)
		}
		return errUserServiceInstall
	}
	if os.Remove(f.Name()) != nil || syscall.Fsync(fd) != nil {
		return errUserServiceInstall
	}
	return nil
}

func sameUserUnit(path string, expected []byte) error {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return errUserServiceInstall
	}
	f := os.NewFile(uintptr(fd), "user-unit")
	defer f.Close()
	var st syscall.Stat_t
	if syscall.Fstat(fd, &st) != nil || st.Mode&syscall.S_IFMT != syscall.S_IFREG || st.Nlink != 1 || int(st.Uid) != os.Geteuid() || st.Mode&0022 != 0 || st.Size != int64(len(expected)) {
		return errUserServiceInstall
	}
	raw, err := io.ReadAll(io.LimitReader(f, int64(len(expected))+1))
	if err != nil || !bytes.Equal(raw, expected) {
		return errUserServiceInstall
	}
	return nil
}

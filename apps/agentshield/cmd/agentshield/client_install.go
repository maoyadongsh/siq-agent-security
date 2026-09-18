package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"strings"
	"time"
)

func cmdClientInstall(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("client-install", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	manifest := fs.String("manifest", "", "signed client release manifest")
	binary := fs.String("binary", "", "downloaded client binary")
	confirm := fs.Bool("confirm-install", false, "install verified binary and start local user service")
	port := fs.Int("port", 0, "initial local port")
	runtimeOnly := fs.Bool("runtime", false, "register for current login session")
	openUI := fs.Bool("open-ui", false, "open management page after installation")
	if err := fs.Parse(args); err != nil {
		return err
	}
	explicit := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "port" {
			explicit = true
		}
	})
	if !*confirm || *manifest == "" || *binary == "" || fs.NArg() != 0 || *port < 0 || *port > 65535 || (explicit && *port == 0) {
		return errors.New("client-install: --manifest FILE --binary FILE --confirm-install and optional valid --port required")
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		return errors.New("client-install: Linux user service or Windows current-user task installation required")
	}
	if runtime.GOOS == "windows" && *runtimeOnly {
		return errors.New("client-install: Windows does not support --runtime; omit this option")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	dir, err = filepath.Abs(dir)
	if err != nil {
		return err
	}
	staged, version, err := prepareClientInstallation(dir, *manifest, *binary, checkUpgradeForCurrentState, clientrelease.Stage)
	if err != nil {
		return err
	}
	dir, err = filepath.EvalSymlinks(dir)
	if err != nil {
		return err
	}
	setupArgs := []string{"setup", "--confirm-setup"}
	if explicit {
		setupArgs = append(setupArgs, "--port", strconv.Itoa(*port))
	}
	if *runtimeOnly {
		setupArgs = append(setupArgs, "--runtime")
	}
	// No credentials in arguments or child output; setup independently rechecks
	// existing service ownership before any registration or start.
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, staged, setupArgs...)
	command.Env = installationEnvironment(os.Environ(), dir)
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	command.WaitDelay = time.Second
	if err = command.Run(); err != nil {
		if runtime.GOOS == "windows" {
			return errors.New("client-install: installation not confirmed; staged program retained, inspect task-runtime/task-query before retrying")
		}
		return errors.New("client-install: installation not confirmed; staged program retained, inspect service-status before retrying")
	}
	st := &state.Store{Dir: dir}
	if runtime.GOOS == "windows" {
		if err := verifyInstalledWindowsClient(st, staged); err != nil {
			return err
		}
	} else {
		unit, err := renderUserUnit(staged, dir)
		if err != nil {
			return err
		}
		_, props, err := ownedService(st, []byte(unit), runUserSystemctl)
		if err != nil {
			return err
		}
		if !serviceRunning(props) {
			return errors.New("client-install: installed service is not running")
		}
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	client := localClient()
	defer client.CloseIdleConnections()
	health, err := probeLocalInstance(client, endpoint, st)
	if err != nil {
		return err
	}
	if health.Version != version {
		return errors.New("client-install: running version differs from verified release")
	}
	if _, err = fmt.Fprintf(out, "已安装并启动本机管理服务。\n程序：%s\n管理页面：%s/\n首次连接请使用已安装程序的 pair 命令。\n", staged, endpoint); err != nil {
		return err
	}
	if *openUI {
		return cmdUI(nil, out)
	}
	return nil
}

// Production callers always use the embedded release root and Stage; hooks are
// passed directly by tests and cannot be selected through flags or environment.
func prepareClientInstallation(dir, manifest, binary string, check func(string, string) (string, error), stage func(string, string, string) (string, error)) (string, string, error) {
	version, err := check(manifest, binary)
	if err != nil {
		return "", "", err
	}
	if runtime.GOOS == "windows" {
		// Stage publishes non-bootstrap history. Establish the first identity
		// only after release verification, before those files can strand setup.
		// Existing identities need no primary writer: setup may reuse the
		// healthy instance that currently holds it.
		if err := prepareWindowsClientInstallationIdentity(dir); err != nil {
			return "", "", err
		}
	}
	staged, err := stage(dir, manifest, binary)
	if err != nil {
		return "", "", err
	}
	staged, err = filepath.Abs(staged)
	if err != nil {
		return "", "", err
	}
	info, err := os.Lstat(staged)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
		return "", "", errors.New("client-install: staged program is not a regular file")
	}
	verified, err := check(manifest, staged)
	if err != nil {
		return "", "", err
	}
	if verified != version {
		return "", "", errors.New("client-install: release changed during staging")
	}
	digest, err := clientrelease.Digest(staged)
	if err != nil {
		return "", "", err
	}
	name := "siq-agent-security"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	expected := filepath.Join(dir, "client-releases", digest, name)
	stagedCanon, stagedErr := filepath.EvalSymlinks(staged)
	expectedCanon, expectedErr := filepath.EvalSymlinks(expected)
	if staged != expected && (stagedErr != nil || expectedErr != nil || stagedCanon != expectedCanon) {
		return "", "", errors.New("client-install: staged program identity or location mismatch")
	}
	return staged, version, nil
}

func prepareWindowsClientInstallationIdentity(dir string) error {
	// A readable identity must not bypass the state writer-version or migration
	// barrier. Stage independently checks it again before publishing files.
	if err := state.RequireStateCompatibility(dir); err != nil {
		return err
	}
	_, err := signing.LoadExisting(dir)
	if err == nil || !errors.Is(err, os.ErrNotExist) {
		return err
	}
	// Do not interpret a missing prerequisite from the read path as permission
	// to bootstrap an existing identity. Only this exact absent file qualifies;
	// the writer-protected Load repeats the full historical-identity guard.
	if _, missingErr := os.Lstat(filepath.Join(dir, "keys", "signing.seed")); !errors.Is(missingErr, os.ErrNotExist) {
		if missingErr != nil {
			return missingErr
		}
		return err
	}
	_, err = loadWindowsTaskPreparationKey(dir)
	return err
}

func installationEnvironment(environment []string, dir string) []string {
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		if runtime.GOOS == "windows" {
			name = strings.ToUpper(name)
		}
		if name != "SIQ_AGENT_SECURITY_STATE_DIR" && name != "AGENTSHIELD_STATE_DIR" {
			result = append(result, entry)
		}
	}
	return append(result, "SIQ_AGENT_SECURITY_STATE_DIR="+dir)
}

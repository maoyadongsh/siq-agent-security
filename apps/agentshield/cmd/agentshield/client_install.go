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
	if runtime.GOOS != "linux" {
		return errors.New("client-install: Linux user service installation required; other OS installers remain unavailable")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	dir, err = filepath.Abs(dir)
	if err != nil {
		return err
	}
	staged, version, err := prepareClientInstallation(dir, *manifest, *binary, clientrelease.CheckUpgrade, clientrelease.Stage)
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
		return errors.New("client-install: installation not confirmed; staged program retained, inspect service-status before retrying")
	}
	st := &state.Store{Dir: dir}
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
	staged, err := stage(dir, manifest, binary)
	if err != nil {
		return "", "", err
	}
	staged, err = filepath.Abs(staged)
	if err != nil {
		return "", "", err
	}
	staged, err = filepath.EvalSymlinks(staged)
	if err != nil {
		return "", "", err
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
	canonical, err := filepath.EvalSymlinks(dir)
	if err != nil {
		return "", "", err
	}
	expected := filepath.Join(canonical, "client-releases", digest, "siq-agent-security")
	if staged != expected {
		return "", "", errors.New("client-install: staged program identity or location mismatch")
	}
	return staged, version, nil
}
func installationEnvironment(environment []string, dir string) []string {
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		if name != "SIQ_AGENT_SECURITY_STATE_DIR" && name != "AGENTSHIELD_STATE_DIR" {
			result = append(result, entry)
		}
	}
	return append(result, "SIQ_AGENT_SECURITY_STATE_DIR="+dir)
}

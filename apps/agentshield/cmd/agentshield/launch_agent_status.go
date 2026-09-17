package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"strings"
	"time"
)

func runUserLaunchctl(args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "/bin/launchctl", args...)
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if name != "LAUNCHD_SOCKET" {
			command.Env = append(command.Env, entry)
		}
	}
	var output serviceOutput
	command.Stdout = &output
	command.Stderr = &output
	command.WaitDelay = time.Second
	if err := command.Run(); err != nil {
		return "", errors.New("launch-agent: launchctl command failed or timed out; state is unconfirmed")
	}
	return output.String(), nil
}
func verifyLaunchUserDomain(control userSystemctl, uid int) error {
	if uid <= 0 {
		return errors.New("launch-agent: non-root user session required")
	}
	managerUID, err := control("manageruid")
	if err != nil {
		return err
	}
	if strings.TrimSpace(managerUID) != strconv.Itoa(uid) {
		return errors.New("launch-agent: wrong user domain")
	}
	manager, err := control("managername")
	if err != nil {
		return err
	}
	if strings.TrimSpace(manager) != "Aqua" {
		return errors.New("launch-agent: GUI user session required")
	}
	return nil
}
func cmdLaunchAgentStatus(args []string, out io.Writer) error {
	var plist bytes.Buffer
	if err := cmdLaunchAgentPlist(args, &plist); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		return err
	}
	record, err := st.VerifyLaunchAgent(key, plist.Bytes())
	if err != nil {
		return err
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	home, err = filepath.EvalSymlinks(home)
	if err != nil {
		return err
	}
	directory := filepath.Join(home, "Library", "LaunchAgents")
	for _, path := range []string{home, filepath.Dir(directory), directory} {
		if err := ordinaryLaunchDirectory(path, false); err != nil {
			return err
		}
	}
	source, err := launchAgentSource(st.Dir, record.Label)
	if err != nil {
		return err
	}
	if err := verifyLaunchRegistration(filepath.Join(directory, record.Label+".plist"), source); err != nil {
		return err
	}
	loaded, pid, err := inspectLaunchAgent(runUserLaunchctl, os.Getuid(), record.Label, plist.Bytes(), source)
	if err != nil {
		return err
	}
	if !loaded {
		_, err = fmt.Fprintln(out, "本实例配置已注册，查询时当前用户域未加载；尚未确认保护服务就绪。")
		return err
	}
	if pid == 0 {
		_, err = fmt.Fprintln(out, "本实例配置已加载，未报告运行 PID；尚未确认保护服务就绪。")
		return err
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	client := localClient()
	defer client.CloseIdleConnections()
	if _, err := probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st); err != nil {
		return err
	}
	if _, err := st.VerifyLaunchAgent(key, plist.Bytes()); err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "本实例配置已加载并报告运行进程，本地 API 目录健康检查通过。")
	return err
}

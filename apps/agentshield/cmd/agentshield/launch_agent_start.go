package main

import (
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"time"
)

func cmdLaunchAgentStart(args []string, out io.Writer) error {
	err := withLaunchAgentCommand(args, "--confirm-start", func(st *state.Store, key *signing.Key, plist []byte, home string, uid int, control userSystemctl) error {
		cfg, err := st.LoadConfig()
		if err != nil {
			return err
		}
		client := localClient()
		defer client.CloseIdleConnections()
		health := func() error {
			_, err := probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st)
			return err
		}
		return startRegisteredLaunchAgent(st, key, plist, home, uid, control, health, 10*time.Second)
	})
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "当前实例已报告运行进程，本地 API 目录健康检查通过；可运行 ui 打开管理页面。")
	return err
}

func startRegisteredLaunchAgent(st *state.Store, key *signing.Key, plist []byte, home string, uid int, control userSystemctl, health func() error, wait time.Duration) error {
	if err := loadRegisteredLaunchAgent(st, key, plist, home, uid, control); err != nil {
		return err
	}
	record, err := st.VerifyLaunchAgent(key, plist)
	if err != nil {
		return err
	}
	source, err := filepath.Abs(filepath.Join(st.Dir, record.Label+".plist"))
	if err != nil {
		return err
	}
	directory := filepath.Join(home, "Library", "LaunchAgents")
	verify := func() error {
		for _, path := range []string{home, filepath.Dir(directory), directory} {
			if err := ordinaryLaunchDirectory(path, false); err != nil {
				return err
			}
		}
		if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
			return err
		}
		return verifyLaunchRegistration(filepath.Join(directory, record.Label+".plist"), source)
	}
	pid, err := readLoadedLaunchAgent(control, uid, plist)
	if err != nil {
		return err
	}
	if pid == 0 {
		writer, err := state.AcquireWriter(st.Dir)
		if err != nil {
			return err
		}
		if err := writer.Release(); err != nil {
			return err
		}
		if err := verify(); err != nil {
			return err
		}
		pid, err = readLoadedLaunchAgent(control, uid, plist)
		if err != nil {
			return err
		}
		if pid == 0 {
			if _, err := control("kickstart", "gui/"+strconv.Itoa(uid)+"/"+record.Label); err != nil {
				return errors.New("launch-agent: start failed or timed out; inspect launch-agent-status before retrying")
			}
		}
	}
	deadline := time.Now().Add(wait)
	for {
		if err := verify(); err != nil {
			return err
		}
		pid, err = readLoadedLaunchAgent(control, uid, plist)
		if err != nil {
			return err
		}
		if pid > 0 && health() == nil {
			return verify()
		}
		if !time.Now().Before(deadline) {
			return errors.New("launch-agent: instance health not confirmed before timeout; configuration and task preserved")
		}
		time.Sleep(100 * time.Millisecond)
	}
}

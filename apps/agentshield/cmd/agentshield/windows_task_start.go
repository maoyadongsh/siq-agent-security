package main

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

//go:embed windows_task_start.ps1
var windowsTaskStartScript string

func cmdWindowsTaskStart(args []string, out io.Writer) error {
	if windowsTaskHelpRequested("task-start", args) {
		_, err := fmt.Fprintln(out, "Usage: siq-agent-security task-start --confirm-start\nStart only this owned Windows task and verify service health. This does not enable login startup.\n--help, -h: show help without reading state or starting a task.")
		return err
	}
	if len(args) != 1 || args[0] != "--confirm-start" {
		return errors.New("task-start: --confirm-start required, no other arguments accepted")
	}
	err := withWindowsTaskIdentity(nil, func(st *state.Store, key *signing.Key, expected []byte, sid string) (resultErr error) {
		lock, err := state.AcquireScopedWriter(st.Dir, "service-control")
		if err != nil {
			return err
		}
		defer func() { resultErr = errors.Join(resultErr, lock.Release()) }()
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
		return startOwnedWindowsTask(st, key, expected, sid, runWindowsTaskQuery, runWindowsTaskStart, health, 10*time.Second)
	})
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "当前实例配置已核对，本地 API 目录健康检查通过；可运行 ui 打开管理页面。")
	return err
}

func startOwnedWindowsTask(st *state.Store, key *signing.Key, expected []byte, sid string, query func(string) ([]byte, error), start func(string, string) error, health func() error, wait time.Duration) error {
	if err := st.CheckServiceSwitchPending(); err != nil {
		return err
	}
	verify := func() error { return queryOwnedWindowsTask(st, key, expected, sid, query, io.Discard) }
	if err := verify(); err != nil {
		return err
	}
	if health() == nil {
		return verify()
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	if err := w.Release(); err != nil {
		return err
	}
	if err := verify(); err != nil {
		return err
	}
	record, err := st.VerifyWindowsTask(key, expected, sid)
	if err != nil {
		return err
	}
	if err := start(record.TaskName, sid); err != nil {
		return errors.New("task-start: start request failed; task and state preserved")
	}
	deadline := time.Now().Add(wait)
	for {
		if err := verify(); err != nil {
			return err
		}
		if health() == nil {
			return verify()
		}
		if !time.Now().Before(deadline) {
			return errors.New("task-start: directory health not confirmed before timeout; task and state preserved")
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func runWindowsTaskStart(name, sid string) error {
	input, err := json.Marshal(map[string]string{"task_name": name, "user_sid": sid})
	if err != nil {
		return err
	}
	stdout, err := runWindowsTaskScript(windowsTaskStartScript, input)
	if err != nil || stdout != "SIQ_TASK_RUN_REQUESTED" {
		return errors.New("task-start: system start request not confirmed")
	}
	return nil
}

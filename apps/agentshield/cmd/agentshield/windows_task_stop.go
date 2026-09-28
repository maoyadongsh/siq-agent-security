package main

import (
	"errors"
	"fmt"
	"io"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdWindowsTaskStop(args []string, out io.Writer) error {
	if windowsTaskHelpRequested("task-stop", args) {
		_, err := fmt.Fprintln(out, "Usage: siq-agent-security task-stop --confirm-stop\nGracefully stop only this owned Windows task and verify idle state. Configuration and authorizations are retained.\n--help, -h: show help without reading state or stopping a task.")
		return err
	}
	if len(args) != 1 || args[0] != "--confirm-stop" {
		return errors.New("task-stop: --confirm-stop required, no other arguments accepted")
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
		request := func() (state.ServiceStopAcceptance, error) {
			return requestSignedLocalStop(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st, key)
		}
		return stopOwnedWindowsTask(st, key, expected, sid, runWindowsTaskQuery, runWindowsTaskRuntime, request, 35*time.Second)
	})
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "当前任务已确认空闲，状态写锁已释放；任务配置和数据已保留。")
	return err
}

func stopOwnedWindowsTask(st *state.Store, key *signing.Key, expected []byte, sid string, query func(string) ([]byte, error), runtime func(string, string) (string, error), request func() (state.ServiceStopAcceptance, error), wait time.Duration) error {
	if err := st.CheckServiceSwitchPending(); err != nil {
		return err
	}
	read := func() (windowsTaskRuntime, error) {
		return readOwnedWindowsTaskRuntime(st, key, expected, sid, query, runtime)
	}
	initial, err := read()
	if err != nil {
		return err
	}
	if initial.State == "queued" {
		return errors.New("task-stop: task is queued; runtime is not ready for graceful stop")
	}
	var accepted state.ServiceStopAcceptance
	var drained state.ServiceStopResult
	requested := initial.State == "running"
	if requested {
		accepted, err = request()
		if err != nil {
			return err
		}
		drained, err = waitLocalStopResult(st, key, accepted, wait)
		if err != nil {
			return err
		}
	}
	deadline := time.Now().Add(wait)
	for {
		current, err := read()
		if err != nil {
			return err
		}
		if current.State == "ready" {
			if requested && current.LastResult != 0 {
				return errors.New("task-stop: task exit result is not successful")
			}
			writer, err := state.AcquireWriter(st.Dir)
			if err == nil {
				final, readErr := read()
				if readErr == nil && (final.State != "ready" || (requested && final.LastResult != 0)) {
					readErr = errors.New("task-stop: task state changed during final verification")
				}
				if readErr == nil && requested {
					saved, acceptErr := st.ReadServiceStopAcceptance(key, accepted.BootID)
					result, resultErr := st.ReadServiceStopResult(key, accepted.BootID)
					if acceptErr != nil || resultErr != nil || saved != accepted || result != drained {
						readErr = errors.New("task-stop: stop records changed during final verification")
					}
				}
				return errors.Join(readErr, writer.Release())
			}
			if !errors.Is(err, state.ErrWriterBusy) {
				return err
			}
		}
		if !time.Now().Before(deadline) {
			return errors.New("task-stop: task idle state or writer release not confirmed; state preserved")
		}
		time.Sleep(100 * time.Millisecond)
	}
}

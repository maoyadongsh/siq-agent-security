package main

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

//go:embed windows_task_runtime.ps1
var windowsTaskRuntimeScript string

type windowsTaskRuntime struct {
	State      string
	Instances  int
	LastResult int64
}

func decodeWindowsTaskRuntime(raw string) (windowsTaskRuntime, error) {
	invalid := errors.New("task-runtime: invalid or inconsistent task state")
	parts := strings.Split(raw, ":")
	if len(parts) != 4 || parts[0] != "SIQ_TASK_RUNTIME" {
		return windowsTaskRuntime{}, invalid
	}
	var values [3]int64
	for i, s := range parts[1:] {
		n, err := strconv.ParseInt(s, 10, 64)
		if err != nil || strconv.FormatInt(n, 10) != s {
			return windowsTaskRuntime{}, invalid
		}
		values[i] = n
	}
	if values[2] < -2147483648 || values[2] > 4294967295 {
		return windowsTaskRuntime{}, invalid
	}
	var name string
	switch {
	case values[0] == 3 && values[1] == 0:
		name = "ready"
	case values[0] == 4 && values[1] == 1:
		name = "running"
	case values[0] == 2 && values[1] == 0:
		name = "queued"
	default:
		return windowsTaskRuntime{}, invalid
	}
	return windowsTaskRuntime{State: name, Instances: int(values[1]), LastResult: values[2]}, nil
}

func readOwnedWindowsTaskRuntime(st *state.Store, key *signing.Key, expected []byte, sid string, query func(string) ([]byte, error), runtime func(string, string) (string, error)) (windowsTaskRuntime, error) {
	if err := queryOwnedWindowsTask(st, key, expected, sid, query, io.Discard); err != nil {
		return windowsTaskRuntime{}, err
	}
	record, err := st.VerifyWindowsTask(key, expected, sid)
	if err != nil {
		return windowsTaskRuntime{}, err
	}
	raw, err := runtime(record.TaskName, sid)
	if err != nil {
		return windowsTaskRuntime{}, errors.New("task-runtime: runtime state unconfirmed")
	}
	result, err := decodeWindowsTaskRuntime(raw)
	if err != nil {
		return windowsTaskRuntime{}, err
	}
	if err := queryOwnedWindowsTask(st, key, expected, sid, query, io.Discard); err != nil {
		return windowsTaskRuntime{}, err
	}
	return result, nil
}

func runWindowsTaskRuntime(name, sid string) (string, error) {
	input, err := json.Marshal(map[string]string{"task_name": name, "user_sid": sid})
	if err != nil {
		return "", err
	}
	return runWindowsTaskScript(windowsTaskRuntimeScript, input)
}

func cmdWindowsTaskRuntime(args []string, out io.Writer) error {
	return withWindowsTaskIdentity(args, func(st *state.Store, key *signing.Key, expected []byte, sid string) error {
		result, err := readOwnedWindowsTaskRuntime(st, key, expected, sid, runWindowsTaskQuery, runWindowsTaskRuntime)
		if err != nil {
			return err
		}
		return writeWindowsTaskRuntime(out, result)
	})
}

func writeWindowsTaskRuntime(out io.Writer, result windowsTaskRuntime) error {
	kind := "scheduler_result"
	if result.LastResult == 267009 {
		kind = "scheduler_running"
	}
	_, err := fmt.Fprintf(out, "state=%s instances=%d last_result=%d\nlast_result_kind=%s health=unverified\n", result.State, result.Instances, result.LastResult, kind)
	return err
}

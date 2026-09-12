package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

type userSystemctl func(...string) (string, error)

type serviceOutput struct{ bytes.Buffer }

func (b *serviceOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 65536 {
		return 0, errors.New("service manager output limit")
	}
	return b.Buffer.Write(p)
}

func runUserSystemctl(args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "systemctl", append([]string{"--user", "--no-pager"}, args...)...)
	cmd.WaitDelay = time.Second
	var output serviceOutput
	cmd.Stdout = &output
	cmd.Stderr = io.Discard
	if err := cmd.Run(); err != nil {
		return "", errors.New("service: system manager command failed or timed out; operation may be incomplete, inspect service-status before retrying")
	}
	return output.String(), nil
}

func readUserUnit(control userSystemctl, name string) (map[string]string, error) {
	raw, err := control("show", "--property=LoadState,FragmentPath,DropInPaths,UnitFileState,ActiveState,MainPID,Result", "--", name)
	if err != nil {
		return nil, err
	}
	props := map[string]string{}
	for _, line := range strings.Split(strings.TrimSuffix(raw, "\n"), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return nil, errors.New("service-register: invalid manager response")
		}
		if _, exists := props[key]; exists {
			return nil, errors.New("service-register: duplicate manager property")
		}
		props[key] = value
	}
	for _, key := range []string{"LoadState", "FragmentPath", "DropInPaths", "UnitFileState"} {
		if _, ok := props[key]; !ok {
			return nil, errors.New("service-register: incomplete manager response")
		}
	}
	return props, nil
}

func verifyUserUnit(props map[string]string, path string, runtimeOnly bool) error {
	expected := "linked"
	if runtimeOnly {
		expected = "linked-runtime"
	}
	enabled := "enabled"
	if runtimeOnly {
		enabled = "enabled-runtime"
	}
	if props["LoadState"] != "loaded" || props["DropInPaths"] != "" || (props["UnitFileState"] != expected && props["UnitFileState"] != enabled) {
		return errors.New("service-register: unexpected unit state, scope or overrides; refusing to modify it")
	}
	actual, err := filepath.EvalSymlinks(props["FragmentPath"])
	wanted, wantErr := filepath.EvalSymlinks(path)
	if err != nil || wantErr != nil || actual != wanted {
		return errors.New("service-register: unit belongs to another configuration")
	}
	if props["UnitFileState"] == enabled {
		return verifyLoginLink(props["FragmentPath"], path)
	}
	return nil
}

func registerUserUnit(control userSystemctl, path, name string, runtimeOnly bool) error {
	props, err := readUserUnit(control, name)
	if err != nil {
		return err
	}
	if props["LoadState"] == "not-found" && props["FragmentPath"] == "" && props["DropInPaths"] == "" && props["UnitFileState"] == "" {
		args := []string{"link"}
		if runtimeOnly {
			args = append(args, "--runtime")
		}
		args = append(args, "--", path)
		if _, err := control(args...); err != nil {
			return err
		}
	} else if err := verifyUserUnit(props, path, runtimeOnly); err != nil {
		return err
	}
	// Retry reload even for an existing owned link: a previous invocation could
	// have stopped between link publication and manager reload.
	if _, err = control("daemon-reload"); err != nil {
		return err
	}
	props, err = readUserUnit(control, name)
	if err != nil {
		return err
	}
	return verifyUserUnit(props, path, runtimeOnly)
}

func cmdServiceRegister(args []string, out io.Writer) error {
	runtimeOnly := false
	if len(args) == 1 && args[0] == "--runtime" {
		runtimeOnly = true
	} else if len(args) != 0 {
		return errors.New("service-register: expected only optional --runtime")
	}
	return withPreparedUserService(nil, func(path string, record state.UserServiceRecord) error {
		if err := registerUserUnit(runUserSystemctl, path, record.UnitName, runtimeOnly); err != nil {
			return err
		}
		_, err := fmt.Fprintf(out, "已确认用户服务注册 %s；保留现有运行与登录自启状态。\n", record.UnitName)
		return err
	})
}

package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
)

func withLaunchAgentCommand(args []string, confirmation string, apply func(*state.Store, *signing.Key, []byte, string, int, userSystemctl) error) (resultErr error) {
	if len(args) != 1 || args[0] != confirmation {
		return fmt.Errorf("launch-agent: %s required", confirmation)
	}
	var plist bytes.Buffer
	if err := cmdLaunchAgentPlist(nil, &plist); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	lifecycle, err := state.AcquireWriter(filepath.Join(dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lifecycle.Release()) }()
	key, err := signing.LoadExisting(dir)
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
	return apply(&state.Store{Dir: dir}, key, plist.Bytes(), home, os.Getuid(), runUserLaunchctl)
}

func cmdLaunchAgentLoad(args []string, out io.Writer) error {
	if err := withLaunchAgentCommand(args, "--confirm-load", loadRegisteredLaunchAgent); err != nil {
		return err
	}
	_, err := fmt.Fprintln(out, "本实例 LaunchAgent 已加载并通过配置归属核对；本命令未请求启动，保护服务是否就绪请运行 launch-agent-status 检查。")
	return err
}

// Caller holds the lifecycle lock. Reusing a loaded job does not need its writer.
func loadRegisteredLaunchAgent(st *state.Store, key *signing.Key, plist []byte, home string, uid int, control userSystemctl) (resultErr error) {
	record, err := st.VerifyLaunchAgent(key, plist)
	if err != nil {
		return err
	}
	source, err := filepath.Abs(filepath.Join(st.Dir, record.Label+".plist"))
	if err != nil {
		return err
	}
	directory := filepath.Join(home, "Library", "LaunchAgents")
	link := filepath.Join(directory, record.Label+".plist")
	verify := func() error {
		for _, path := range []string{home, filepath.Dir(directory), directory} {
			if err := ordinaryLaunchDirectory(path, false); err != nil {
				return err
			}
		}
		if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
			return err
		}
		return verifyLaunchRegistration(link, source)
	}
	if err := verify(); err != nil {
		return err
	}
	loaded, _, err := inspectLaunchAgent(control, uid, record.Label, plist)
	if err != nil {
		return err
	}
	if loaded {
		return verify()
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, writer.Release()) }()
	loaded, _, err = inspectLaunchAgent(control, uid, record.Label, plist)
	if err != nil {
		return err
	}
	if err := verify(); err != nil {
		return err
	}
	if loaded {
		return nil
	}
	if _, err := control("bootstrap", "gui/"+strconv.Itoa(uid), link); err != nil {
		return errors.New("launch-agent: loading failed or timed out; inspect launch-agent-status before retrying, configuration preserved")
	}
	if err := verify(); err != nil {
		return err
	}
	loaded, _, err = inspectLaunchAgent(control, uid, record.Label, plist)
	if err != nil {
		return err
	}
	if !loaded {
		return errors.New("launch-agent: loaded task not confirmed after bootstrap")
	}
	return verify()
}

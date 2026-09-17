package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"strconv"
)

func cmdLaunchAgentUnregister(args []string, out io.Writer) error {
	if err := withLaunchAgentCommand(args, "--confirm-unregister", unregisterLaunchAgent); err != nil {
		return err
	}
	_, err := fmt.Fprintln(out, "当前用户域本实例已无 LaunchAgent 注册；程序、配置、密钥和历史已保留。")
	return err
}

func unregisterLaunchAgent(st *state.Store, key *signing.Key, plist []byte, home string, uid int, control userSystemctl) (resultErr error) {
	record, err := st.VerifyLaunchAgent(key, plist)
	if err != nil {
		return err
	}
	source, err := launchAgentSource(st.Dir, record.Label)
	if err != nil {
		return err
	}
	directory := filepath.Join(home, "Library", "LaunchAgents")
	link := filepath.Join(directory, record.Label+".plist")
	verify := func() (bool, error) {
		for _, path := range []string{home, filepath.Dir(directory), directory} {
			if err := ordinaryLaunchDirectory(path, false); err != nil {
				return false, err
			}
		}
		if _, err := st.VerifyLaunchAgent(key, plist); err != nil {
			return false, err
		}
		if _, err := os.Lstat(link); errors.Is(err, os.ErrNotExist) {
			return false, nil
		} else if err != nil {
			return false, err
		}
		return true, verifyLaunchRegistration(link, source)
	}
	linked, err := verify()
	if err != nil {
		return err
	}
	loaded, pid, err := inspectLaunchAgent(control, uid, record.Label, plist, source)
	if err != nil {
		return err
	}
	if loaded && (!linked || pid > 0) {
		return errors.New("launch-agent: loaded task requires owned registration and stopped process; run launch-agent-stop first")
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, writer.Release()) }()
	linked, err = verify()
	if err != nil {
		return err
	}
	loaded, pid, err = inspectLaunchAgent(control, uid, record.Label, plist, source)
	if err != nil {
		return err
	}
	if loaded {
		if !linked || pid > 0 {
			return errors.New("launch-agent: task changed before unregister; inspect status")
		}
		if linked, err = verify(); err != nil {
			return err
		} else if !linked {
			return errors.New("launch-agent: registration disappeared before unload")
		}
		if _, err := control("bootout", "gui/"+strconv.Itoa(uid)+"/"+record.Label); err != nil {
			return errors.New("launch-agent: unload failed or timed out; configuration preserved, inspect status before retrying")
		}
	}
	loaded, _, err = inspectLaunchAgent(control, uid, record.Label, plist, source)
	if err != nil {
		return err
	}
	if loaded {
		return errors.New("launch-agent: task absence not confirmed after unload")
	}
	linked, err = verify()
	if err != nil {
		return err
	}
	if linked {
		if err := statefs.Remove(link); err != nil {
			return err
		}
	}
	if err := syncLaunchAgentDirectory(directory); err != nil {
		return err
	}
	linked, err = verify()
	if err != nil {
		return err
	}
	if linked {
		return errors.New("launch-agent: registration reappeared during removal")
	}
	return nil
}

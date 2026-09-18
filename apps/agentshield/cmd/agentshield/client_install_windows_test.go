//go:build windows

package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestWindowsClientInstallPreflight(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "uncreated")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	args := []string{"--confirm-install", "--manifest", "../../testdata/contracts/skill-manifest.v2.sample.json", "--binary", "../../testdata/contracts/skill-manifest.v2.sample.json"}
	if err := cmdClientInstall(append(append([]string(nil), args...), "--runtime"), io.Discard); err == nil || !strings.Contains(err.Error(), "Windows does not support --runtime") {
		t.Fatal("runtime must fail before staging", err)
	}
	if err := cmdClientInstall(args, io.Discard); err == nil || strings.Contains(err.Error(), "installation required") || strings.Contains(err.Error(), "installers remain unavailable") {
		t.Fatal("Windows must reach trusted release verification and refuse the untrusted fixture", err)
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("invalid install created state", err)
	}
}

func TestWindowsInstallationEnvironmentCaseInsensitiveState(t *testing.T) {
	got := installationEnvironment([]string{"Path=C:\\Windows", "siq_agent_security_state_dir=C:\\other", "AgentShield_State_Dir=C:\\legacy"}, `C:\selected`)
	want := []string{"Path=C:\\Windows", `SIQ_AGENT_SECURITY_STATE_DIR=C:\selected`}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("case-confused state override inherited")
	}
}

func TestWindowsClientInstallTask(t *testing.T) {
	// Keep fixture paths within the same 260-unit task path boundary as users.
	root := t.TempDir()
	for index, scenario := range []string{"running", "ready", "queued", "multiple", "runtime error", "initial drift", "final drift", "wrong binary", "wrong sid"} {
		t.Run(scenario, func(t *testing.T) {
			st, err := state.Open(filepath.Join(root, strconv.Itoa(index)))
			if err != nil {
				t.Fatal(err)
			}
			w, err := state.AcquireWriter(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			defer w.Release()
			if _, err := st.Initialize(w, 0); err != nil {
				t.Fatal(err)
			}
			instance, err := st.ReadLocalInstance()
			if err != nil {
				t.Fatal(err)
			}
			key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
			if err != nil {
				t.Fatal(err)
			}
			const sid = "S-1-5-21-100-200-300-1001"
			staged := filepath.Join(st.Dir, "client-releases", strings.Repeat("a", 64), "siq-agent-security.exe")
			expected, err := renderWindowsTask(staged, st.Dir, instance.InstanceID, sid)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := st.PrepareWindowsTask(w, key, []byte(expected), sid); err != nil {
				t.Fatal(err)
			}
			queries, runtimes := 0, 0
			query := func(name string) ([]byte, error) {
				queries++
				if name != `\SIQ-Agent-Security-`+instance.InstanceID {
					t.Fatal("queried foreign instance")
				}
				if scenario == "initial drift" || (scenario == "final drift" && queries == 2) {
					return []byte(strings.Replace(expected, staged, `C:\foreign.exe`, 1)), nil
				}
				return []byte(expected), nil
			}
			runtime := func(name, user string) (string, error) {
				runtimes++
				if name != `\SIQ-Agent-Security-`+instance.InstanceID || user != sid {
					t.Fatal("queried foreign runtime")
				}
				switch scenario {
				case "ready":
					return "SIQ_TASK_RUNTIME:3:0:0", nil
				case "queued":
					return "SIQ_TASK_RUNTIME:2:0:0", nil
				case "multiple":
					return "SIQ_TASK_RUNTIME:4:2:0", nil
				case "runtime error":
					return "", errors.New("unavailable")
				}
				return "SIQ_TASK_RUNTIME:4:1:0", nil
			}
			verifySID := sid
			if scenario == "wrong sid" {
				verifySID = "S-1-5-21-100-200-300-1002"
			}
			if scenario == "wrong binary" {
				staged = filepath.Join(st.Dir, "download.exe")
			}
			err = verifyInstalledWindowsClientTask(st, key, staged, verifySID, query, runtime)
			if scenario == "running" {
				if err != nil || queries != 2 || runtimes != 1 {
					t.Fatal("owned staged task not verified", err)
				}
			} else if err == nil {
				t.Fatal("unconfirmed installation accepted")
			}
			if (scenario == "wrong sid" || scenario == "wrong binary" || scenario == "initial drift") && runtimes != 0 {
				t.Fatal("runtime inspected before task ownership confirmed")
			}
		})
	}
}

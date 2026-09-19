//go:build windows

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

const windowsStatePathCanary = "synthetic-state-path-private-canary"

type windowsStatePathEntry struct {
	Mode   fs.FileMode
	Size   int64
	Digest [sha256.Size]byte
}

// This snapshot detects persistent fixture changes, not transient filesystem
// calls. Early lexical rejection before writers is a separate control-flow rule.
func windowsStatePathSnapshot(t *testing.T, root string) map[string]windowsStatePathEntry {
	t.Helper()
	entries := make(map[string]windowsStatePathEntry)
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		if !info.IsDir() && !info.Mode().IsRegular() {
			return errors.New("unexpected non-regular fixture entry")
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		entry := windowsStatePathEntry{Mode: info.Mode(), Size: info.Size()}
		if info.Mode().IsRegular() {
			content, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			entry.Digest = sha256.Sum256(content)
		}
		entries[rel] = entry
		return nil
	})
	if err != nil {
		t.Fatal("cannot inspect private test fixture")
	}
	return entries
}

func windowsStatePathAssertUnchanged(t *testing.T, root string, before map[string]windowsStatePathEntry) {
	t.Helper()
	if !reflect.DeepEqual(windowsStatePathSnapshot(t, root), before) {
		t.Error("rejected path changed an alias, fallback, or parent fixture")
	}
}

func windowsStatePathFixture(t *testing.T) (root, target, legacy string) {
	t.Helper()
	root = t.TempDir()
	target = filepath.Join(root, "target")
	legacy = filepath.Join(root, "legacy")
	for _, dir := range []string{target, legacy, filepath.Join(root, "good")} {
		if err := os.Mkdir(dir, 0o700); err != nil {
			t.Fatal("cannot create private test fixture")
		}
	}
	if err := os.WriteFile(filepath.Join(root, "parent-canary"), []byte(windowsStatePathCanary), 0o600); err != nil {
		t.Fatal("cannot create parent canary")
	}
	t.Setenv("LOCALAPPDATA", filepath.Join(root, "default-base"))
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", target)
	t.Setenv("AGENTSHIELD_STATE_DIR", legacy)
	return root, target, legacy
}

func windowsStatePathInputs(target string) []struct{ name, raw string } {
	// Concatenate raw strings: filepath.Join would erase the navigation cases.
	return []struct{ name, raw string }{
		{"trailing-dot", target + "."},
		{"trailing-space", target + " "},
		{"middle-dot", target + `.\child`},
		{"middle-space-forward-slash", filepath.ToSlash(target) + " /child"},
		{"trailing-separator", target + " \\"},
		{"erased-dot", target + `.\..\good`},
		{"erased-space", target + ` \..\good`},
		{"nonempty-whitespace", " "},
	}
}

func TestWindowsServeStatePathAliasSelection(t *testing.T) {
	root, target, legacy := windowsStatePathFixture(t)
	selected := filepath.Join(root, "中文 状态")
	if err := os.Mkdir(selected, 0o700); err != nil {
		t.Fatal("cannot create selected fixture")
	}
	before := windowsStatePathSnapshot(t, root)
	defer windowsStatePathAssertUnchanged(t, root, before)
	for _, tc := range windowsStatePathInputs(target) {
		t.Run(tc.name, func(t *testing.T) {
			if got, err := serveStateDirectory(tc.raw, true); err == nil || got != "" {
				t.Error("explicit invalid path was accepted or fell back to the environment")
			}
		})
	}
	if got, err := serveStateDirectory("", true); err == nil || got != "" {
		t.Error("explicit empty path fell back to the environment")
	}

	canonical, err := filepath.EvalSymlinks(selected)
	if err != nil {
		t.Fatal("cannot resolve selected fixture")
	}
	// The explicit valid selector must not validate or fall back to ambient state.
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", target+" ")
	t.Setenv("AGENTSHIELD_STATE_DIR", legacy+".")
	if got, err := serveStateDirectory(canonical, true); err != nil || got != canonical {
		t.Error("valid explicit Unicode/space path did not override invalid environment")
	}
	if os.Getenv("SIQ_AGENT_SECURITY_STATE_DIR") != target+" " || os.Getenv("AGENTSHIELD_STATE_DIR") != legacy+"." {
		t.Error("serve selector changed the environment")
	}
}

func TestWindowsStatePathAliasCommandsRejectBeforeMutation(t *testing.T) {
	for _, command := range []struct {
		name string
		run  func([]string, *bytes.Buffer) error
	}{
		{"init", func(args []string, out *bytes.Buffer) error { return cmdInitialize(args, out) }},
		{"state-status", func(args []string, out *bytes.Buffer) error { return cmdStateStatus(args, out) }},
	} {
		t.Run(command.name, func(t *testing.T) {
			root, target, _ := windowsStatePathFixture(t)
			for _, tc := range windowsStatePathInputs(target) {
				t.Run(tc.name, func(t *testing.T) {
					t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", tc.raw)
					before := windowsStatePathSnapshot(t, root)
					defer windowsStatePathAssertUnchanged(t, root, before)
					var out bytes.Buffer
					if err := command.run(nil, &out); !errors.Is(err, stateformat.ErrCorrupt) {
						t.Error("invalid raw environment did not return the path rejection category")
					}
					if out.Len() != 0 {
						t.Error("invalid raw environment produced a successful initialization or status payload")
					}
				})
			}
		})
	}
}

func TestWindowsStatePathAliasHookFailsClosedWithoutFallback(t *testing.T) {
	for _, tcName := range []string{"trailing-dot", "trailing-space", "nonempty-whitespace"} {
		t.Run(tcName, func(t *testing.T) {
			root, target, legacy := windowsStatePathFixture(t)
			// Both possible old targets have valid advisory configuration, but no
			// token, so even a regressed fallback cannot create a network client.
			for _, dir := range []string{target, legacy} {
				if _, err := state.Open(dir); err != nil {
					t.Fatal("cannot prepare advisory fixture")
				}
				if err := os.WriteFile(filepath.Join(dir, "config.json"), []byte(`{"enforcement_mode":"warn","port":47611}`), 0o600); err != nil {
					t.Fatal("cannot prepare advisory configuration")
				}
			}
			for _, tc := range windowsStatePathInputs(target) {
				if tc.name == tcName {
					t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", tc.raw)
				}
			}
			before := windowsStatePathSnapshot(t, root)
			defer windowsStatePathAssertUnchanged(t, root, before)
			for _, event := range []string{"PreToolUse", "PostToolUse"} {
				var out bytes.Buffer
				input := `{"session_id":"state-alias-fixture","tool_use_id":"state-alias-call","hook_event_name":"` + event + `","tool_name":"Read","tool_input":{"file_path":"/fixture"}}`
				if err := runCodeBuddyHook(strings.NewReader(input), &out); err != nil {
					t.Fatal("hook must emit structured output instead of a non-blocking exit error")
				}
				var response adapters.CodeBuddyOutput
				if err := json.Unmarshal(out.Bytes(), &response); err != nil {
					t.Fatal("hook did not emit valid structured output")
				}
				if response.HookSpecificOutput.HookEventName != event {
					t.Error("hook event identity changed")
				}
				if event == "PreToolUse" {
					if response.HookSpecificOutput.PermissionDecision != "deny" || !strings.Contains(response.HookSpecificOutput.PermissionDecisionReason, "fail-closed") {
						t.Error("invalid primary state fell back to an advisory configuration")
					}
				} else if response.HookSpecificOutput.PermissionDecision != "" {
					t.Error("unavailable post hook fabricated a permission decision")
				}
				for _, value := range []string{root, windowsStatePathCanary} {
					encoded, err := json.Marshal(value)
					if err != nil {
						t.Fatal("cannot encode fixture canary")
					}
					if bytes.Contains(out.Bytes(), encoded[1:len(encoded)-1]) || strings.Contains(out.String(), value) {
						t.Error("hook leaked private fixture diagnostics")
					}
				}
				windowsStatePathAssertUnchanged(t, root, before)
			}
		})
	}
}

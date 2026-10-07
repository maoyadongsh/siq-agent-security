//go:build linux

package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestVerifiedConnectorExecutesPinnedNativeFile(t *testing.T) {
	path, digest := connectorFixture(t)
	t.Setenv("PATH", "/poisoned-path")
	t.Setenv("SIQ_SYNTHETIC_DEVICE_SECRET", "PRIVATE_DIAGNOSTIC_MUST_NOT_LEAK")
	t.Setenv("LD_LIBRARY_PATH", "/poisoned-loader")
	c, err := NewVerifiedSubprocessConnector(context.Background(), path, digest, SubprocessOptions{Name: "hermes"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	var health map[string]any
	if err := c.call(context.Background(), "health", nil, &health); err != nil {
		t.Fatal(err)
	}
	if health["alive"] != true || health["secret_absent"] != true || health["loader_absent"] != true || health["path"] != "/usr/bin:/bin" {
		t.Fatal("unsafe child environment", health)
	}
	if err := c.call(context.Background(), "unknown", nil, nil); !errors.Is(err, ErrUnsupported) || strings.Contains(err.Error(), "PRIVATE") {
		t.Fatal("diagnostic body escaped", err)
	}
}

func TestVerifiedConnectorRejectsUntrustedFiles(t *testing.T) {
	for _, scenario := range []string{"missing_digest", "wrong_digest", "writable", "group_writable", "parent_writable", "symlink", "parent_symlink", "hardlink", "fifo", "script", "wrong_name", "relative"} {
		t.Run(scenario, func(t *testing.T) {
			path, digest := connectorFixture(t)
			must := func(err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			switch scenario {
			case "missing_digest":
				digest = ""
			case "wrong_digest":
				digest = strings.Repeat("0", 64)
			case "writable":
				must(os.Chmod(path, 0700))
			case "group_writable":
				must(os.Chmod(path, 0520))
			case "parent_writable":
				must(os.Chmod(filepath.Dir(path), 0777))
				defer os.Chmod(filepath.Dir(path), 0700)
			case "symlink":
				target := path + ".real"
				must(os.Rename(path, target))
				must(os.Symlink(target, path))
			case "parent_symlink":
				parent := t.TempDir()
				must(os.Chmod(parent, 0700))
				link := filepath.Join(parent, "alias")
				must(os.Symlink(filepath.Dir(path), link))
				path = filepath.Join(link, "hermes-connector")
			case "hardlink":
				must(os.Link(path, path+".link"))
			case "fifo":
				must(os.Remove(path))
				must(syscall.Mkfifo(path, 0500))
			case "script":
				must(os.Remove(path))
				body := []byte("#!/bin/sh\nexit 0\n")
				must(os.WriteFile(path, body, 0500))
				digest = fmt.Sprintf("%x", sha256.Sum256(body))
			case "wrong_name":
				moved := path + ".other"
				must(os.Rename(path, moved))
				path = moved
			case "relative":
				path = "hermes-connector"
			}
			c, err := NewVerifiedSubprocessConnector(context.Background(), path, digest, SubprocessOptions{Name: "hermes"})
			if c != nil {
				c.Close()
				t.Fatal("untrusted child started")
			}
			if !errors.Is(err, ErrConnectorTrust) {
				t.Fatal("wrong trust failure", err)
			}
		})
	}
}

func TestVerifiedDescriptorSurvivesPathReplacement(t *testing.T) {
	path, digest := connectorFixture(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd, pinned, err := connectorCommand(ctx, path, "hermes", digest)
	if err != nil {
		t.Fatal(err)
	}
	defer pinned.Close()
	if err = os.Rename(path, path+".original"); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("#!/bin/sh\nexit 93\n"), 0500); err != nil {
		t.Fatal(err)
	}
	cmd.Env = []string{"PATH=/usr/bin:/bin"}
	cmd.Stdin = strings.NewReader("{\"id\":\"probe\",\"op\":\"health\"}\n")
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal("pinned program did not run", err)
	}
	var reply struct {
		Result map[string]any `json:"result"`
	}
	if json.Unmarshal(raw, &reply) != nil || reply.Result["alive"] != true {
		t.Fatal("replacement executed")
	}
	if _, err = openVerifiedConnector(path, "hermes", digest); !errors.Is(err, ErrConnectorTrust) {
		t.Fatal("later launch trusted replaced path")
	}
}

func TestVerifiedConnectorAcceptsExplicitNewDigest(t *testing.T) {
	path, old := connectorFixture(t)
	if err := os.Chmod(path, 0700); err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	f.WriteString("synthetic upgrade marker")
	f.Close()
	os.Chmod(path, 0500)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if c, err := NewVerifiedSubprocessConnector(context.Background(), path, old, SubprocessOptions{Name: "hermes"}); c != nil || !errors.Is(err, ErrConnectorTrust) {
		if c != nil {
			c.Close()
		}
		t.Fatal("old pin accepted upgrade")
	}
	c, err := NewVerifiedSubprocessConnector(context.Background(), path, fmt.Sprintf("%x", sha256.Sum256(raw)), SubprocessOptions{Name: "hermes"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Describe(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestNoPATHFallbackForManagedOrDevelopmentResolution(t *testing.T) {
	path, _ := connectorFixture(t)
	t.Setenv("PATH", filepath.Dir(path))
	t.Setenv("SIQ_CONNECTOR_BIN_DIR", "")
	if _, err := ResolveConnectorBin("hermes", ""); err == nil {
		t.Fatal("PATH selected implicitly")
	}
	if got, err := ResolveConnectorBin("hermes", path); err != nil || got != path {
		t.Fatal("explicit development path rejected", err)
	}
	t.Setenv("SIQ_CONNECTOR_BIN_DIR", t.TempDir())
	if _, err := ResolveConnectorBin("hermes", ""); err == nil {
		t.Fatal("missing directory entry fell back to PATH")
	}
	t.Setenv("SIQ_CONNECTOR_BIN_DIR", filepath.Dir(path))
	if got, err := ResolveConnectorBin("hermes", ""); err != nil || got != path {
		t.Fatal("explicit development directory rejected", err)
	}
	if _, _, err := resolveManagedConnector(&State{}, "hermes"); !errors.Is(err, ErrConnectorTrust) {
		t.Fatal("legacy state selected unsigned program")
	}
}

func TestVerifiedConnectorBoundsUnterminatedOutput(t *testing.T) {
	path, digest := connectorFixture(t)
	c, err := NewVerifiedSubprocessConnector(context.Background(), path, digest, SubprocessOptions{Name: "hermes", Version: "overflow", MaxOutputBytes: 8192, Timeout: 3 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	start := time.Now()
	if _, err = c.Describe(context.Background()); !errors.Is(err, ErrOutputLimit) {
		t.Fatal("unterminated output was not bounded", err)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("output waited for operation timeout")
	}
	if _, err = c.Health(context.Background()); !errors.Is(err, ErrConnectorClosed) {
		t.Fatal("oversized child reused")
	}
}

func TestConnectorLineLimitPreservesFollowingResponse(t *testing.T) {
	r := bufio.NewReaderSize(strings.NewReader("1234567\nnext\n"), 16)
	if b, err := readBoundedConnectorLine(r, 8); err != nil || string(b) != "1234567\n" {
		t.Fatal("exact limit rejected")
	}
	if b, err := readBoundedConnectorLine(r, 8); err != nil || string(b) != "next\n" {
		t.Fatal("next message lost")
	}
	if _, err := readBoundedConnectorLine(bufio.NewReader(strings.NewReader("12345678\n")), 8); !errors.Is(err, ErrOutputLimit) {
		t.Fatal("limit plus one accepted")
	}
}

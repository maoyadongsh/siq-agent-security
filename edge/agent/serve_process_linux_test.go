//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestServeProcessChild(t *testing.T) {
	if os.Getenv("SIQ_TEST_SERVE_CHILD") != "1" {
		return
	}
	os.Args = []string{"edge-agent", "serve"}
	main()
	os.Exit(0)
}

func TestServeProcessSingletonSignalAndRestart(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	heartbeats := make(chan struct{}, 8)
	tasks := make(chan struct{}, 8)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer synthetic-process-secret" || r.Header.Get("X-Edge-Identity") != "fixture-process-device" {
			t.Error("lost fixture identity")
			w.WriteHeader(401)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/edge/v1/heartbeat" && r.Method == http.MethodPost:
			var body struct {
				Capabilities struct {
					Connectors []string `json:"connectors"`
				} `json:"capabilities"`
			}
			if json.NewDecoder(io.LimitReader(r.Body, 8192)).Decode(&body) != nil || len(body.Capabilities.Connectors) != 0 {
				t.Error("unverified connectors advertised")
			}
			_, _ = io.WriteString(w, `{}`)
			heartbeats <- struct{}{}
		case r.URL.Path == "/edge/v1/tasks" && r.Method == http.MethodGet:
			_, _ = io.WriteString(w, `[]`)
			tasks <- struct{}{}
		default:
			t.Error("unexpected enrollment/scan/upload request")
			w.WriteHeader(400)
		}
	}))
	defer server.Close()
	state := &State{ControlPlaneURL: server.URL, DeviceIdentity: "fixture-process-device", Secret: "synthetic-process-secret"}
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	statePath := filepath.Join(dir, "state.json")
	before, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	start := func() (*exec.Cmd, <-chan error, *bytes.Buffer) {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		t.Cleanup(cancel)
		cmd := exec.CommandContext(ctx, binary, "-test.run=^TestServeProcessChild$")
		cmd.Env = []string{"SIQ_TEST_SERVE_CHILD=1", "SIQ_EDGE_STATE_DIR=" + dir, "PATH=/usr/bin:/bin"}
		var output bytes.Buffer
		cmd.Stdout = &output
		cmd.Stderr = &output
		if err := cmd.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = cmd.Process.Kill() })
		done := make(chan error, 1)
		go func() { done <- cmd.Wait() }()
		return cmd, done, &output
	}
	waitEvent := func(ch <-chan struct{}) {
		t.Helper()
		select {
		case <-ch:
		case <-time.After(5 * time.Second):
			t.Fatal("process did not reach local fixture")
		}
	}
	waitExit := func(done <-chan error) error {
		t.Helper()
		select {
		case err := <-done:
			return err
		case <-time.After(5 * time.Second):
			t.Fatal("process did not exit")
			return nil
		}
	}
	first, firstDone, firstOutput := start()
	waitEvent(heartbeats)
	waitEvent(tasks)
	_, duplicateDone, duplicateOutput := start()
	if err := waitExit(duplicateDone); err == nil || !strings.Contains(duplicateOutput.String(), "already active") {
		t.Fatal("duplicate serve was not denied")
	}
	if err := first.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	if err := waitExit(firstDone); err != nil {
		t.Fatal("SIGTERM was not graceful", err)
	}
	second, secondDone, secondOutput := start()
	waitEvent(heartbeats)
	waitEvent(tasks)
	if err := second.Process.Signal(syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	if err := waitExit(secondDone); err == nil {
		t.Fatal("crash simulation unexpectedly exited successfully")
	}
	third, thirdDone, thirdOutput := start()
	waitEvent(heartbeats)
	waitEvent(tasks)
	if err := third.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	if err := waitExit(thirdDone); err != nil {
		t.Fatal("post-crash restart exit failed", err)
	}
	after, err := os.ReadFile(statePath)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("restart altered device state")
	}
	for _, out := range []*bytes.Buffer{firstOutput, duplicateOutput, secondOutput, thirdOutput} {
		if strings.Contains(out.String(), state.Secret) || strings.Contains(out.String(), server.URL) {
			t.Fatal("private service context leaked")
		}
	}
}

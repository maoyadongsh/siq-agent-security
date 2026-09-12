package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

func freeStartPort(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := strconv.Itoa(ln.Addr().(*net.TCPAddr).Port)
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	return port
}

func TestStartInitializesBeforeServeAndPreservesConfiguration(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	port := freeStartPort(t)
	want := errors.New("serve stopped")
	called := 0
	serve := func(args []string) error {
		called++
		if strings.Join(args, " ") != "--port "+port {
			t.Fatal("incorrect serve arguments")
		}
		if _, err := (&state.Store{Dir: dir}).ReadLocalInstance(); err != nil {
			t.Fatal(err)
		}
		return want
	}
	if err := startLocal([]string{"--port", port}, io.Discard, serve); !errors.Is(err, want) {
		t.Fatal(err)
	}
	before, err := os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := startLocal(nil, io.Discard, serve); !errors.Is(err, want) {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if called != 2 || !bytes.Equal(before, after) {
		t.Fatal("configuration changed")
	}
}

func TestStartOccupiedPortDoesNotInitializeOrServe(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "other service") }))
	defer srv.Close()
	port := strings.TrimPrefix(srv.URL, "http://127.0.0.1:")
	if err := startLocal([]string{"--port", port}, io.Discard, func([]string) error { t.Fatal("started over occupied port"); return nil }); err == nil {
		t.Fatal("occupied port accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("occupied port created state")
	}
}

func TestStartReusesOnlyMatchingInstance(t *testing.T) {
	for _, match := range []bool{true, false} {
		t.Run(strconv.FormatBool(match), func(t *testing.T) {
			dir := t.TempDir()
			t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
			st := &state.Store{Dir: dir}
			id, err := st.DirectoryID()
			if err != nil {
				t.Fatal(err)
			}
			if !match {
				id = strings.Repeat("0", 64)
			}
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method != "GET" || r.URL.Path != "/healthz/instance" || r.Header.Get("Authorization") != "" {
					t.Error("reuse attempted mutation or credentials")
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(localHealth{SchemaVersion: "local-service-instance-health/v1", Product: "siq-agent-security", Version: "test", LocalMode: true, Status: "ready", StateDirectoryID: id})
			}))
			defer srv.Close()
			port := strings.TrimPrefix(srv.URL, "http://127.0.0.1:")
			if err := cmdInitialize([]string{"--port", port}, io.Discard); err != nil {
				t.Fatal(err)
			}
			writer, err := state.AcquireWriter(dir)
			if err != nil {
				t.Fatal(err)
			}
			defer writer.Release()
			var out bytes.Buffer
			err = startLocal(nil, &out, func([]string) error { t.Fatal("reuse started another service"); return nil })
			if (err == nil) != match {
				t.Fatalf("unexpected reuse: %v", err)
			}
			if match && !strings.Contains(out.String(), "local-service-instance-health/v1") {
				t.Fatal("missing verified health")
			}
		})
	}
}

func TestStartRejectsArgumentsAndActiveWriter(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	serve := func([]string) error { t.Fatal("invalid startup reached serve"); return nil }
	for _, args := range [][]string{{"--port", "0"}, {"--port", "-1"}, {"--port", "65536"}, {"--mode", "warn"}, {"extra"}} {
		if err := startLocal(args, io.Discard, serve); err == nil {
			t.Fatal("invalid argument accepted")
		}
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("invalid args created state")
	}
	port := freeStartPort(t)
	if err := cmdInitialize([]string{"--port", port}, io.Discard); err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if err := startLocal(nil, io.Discard, serve); !errors.Is(err, state.ErrWriterBusy) {
		t.Fatalf("active lock not respected: %v", err)
	}
}

package main

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestEnrollmentStdinBoundary(t *testing.T) {
	for _, input := range []string{"enr-synthetic\n", "enr-synthetic\r\n", "enr-synthetic"} {
		code, err := readEnrollmentCode(strings.NewReader(input))
		if err != nil || code != "enr-synthetic" {
			t.Fatal("valid bounded code rejected")
		}
	}
	for _, input := range []string{"", " \n", "enr bad\n", strings.Repeat("s", 1025)} {
		code, err := readEnrollmentCode(strings.NewReader(input))
		if err == nil || code != "" || strings.Contains(err.Error(), strings.TrimSpace(input)) && len(input) > 10 {
			t.Fatal("invalid input accepted or echoed")
		}
	}
}
func TestEnrollmentPreservesExistingState(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	p := filepath.Join(dir, "state.json")
	before := []byte("synthetic existing state")
	if err := os.WriteFile(p, before, 0600); err != nil {
		t.Fatal(err)
	}
	err := cmdRegister(context.Background(), []string{"--control-plane", "http://127.0.0.1:1", "--enrollment-code", "synthetic"})
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatal("registration attempted despite existing state", err)
	}
	after, _ := os.ReadFile(p)
	if string(after) != string(before) {
		t.Fatal("existing state changed")
	}
}

type enteredEnrollmentReader struct {
	io.Reader
	entered chan struct{}
	once    sync.Once
}

func (r *enteredEnrollmentReader) Read(p []byte) (int, error) {
	r.once.Do(func() { close(r.entered) })
	return r.Reader.Read(p)
}

func TestEnrollmentInputCancellation(t *testing.T) {
	input, writer := io.Pipe()
	defer input.Close()
	defer writer.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	reader := &enteredEnrollmentReader{Reader: input, entered: make(chan struct{})}
	go func() {
		code, err := readEnrollmentCodeContext(ctx, reader)
		if code != "" {
			done <- errors.New("cancel returned code")
			return
		}
		done <- err
	}()
	select {
	case <-reader.entered:
	case <-time.After(time.Second):
		t.Fatal("stdin read did not begin")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatal("cancel not propagated")
		}
	case <-time.After(time.Second):
		t.Fatal("cancelled input remained blocked")
	}
	code, err := readEnrollmentCodeContext(context.Background(), strings.NewReader("enr-fixture\n"))
	if err != nil || code != "enr-fixture" {
		t.Fatal("normal stdin read failed")
	}
}

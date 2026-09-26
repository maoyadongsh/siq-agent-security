package main

import (
	"bytes"
	"fmt"
	"io"
	"strings"
	"testing"
)

func TestConsoleBrowserAvailability(t *testing.T) {
	for _, tc := range []struct {
		goos string
		env  map[string]string
		want bool
	}{
		{"linux", nil, false},
		{"linux", map[string]string{"DISPLAY": ":0"}, true},
		{"linux", map[string]string{"WAYLAND_DISPLAY": "wayland-0"}, true},
		{"linux", map[string]string{"DISPLAY": ":0", "SSH_CONNECTION": "present"}, false},
		{"darwin", nil, true},
		{"windows", nil, true},
		{"darwin", map[string]string{"SSH_TTY": "present"}, false},
		{"windows", map[string]string{"SSH_CLIENT": "present"}, false},
	} {
		if got := consoleBrowserAvailable(tc.goos, func(key string) string { return tc.env[key] }); got != tc.want {
			t.Fatalf("availability %s %v: %v", tc.goos, tc.env, got)
		}
	}
}

func TestConsoleAccessGuidePreservesLoopbackAndMatchingPort(t *testing.T) {
	for _, port := range []int{1, 47611, 47823, 65535} {
		var out bytes.Buffer
		if err := writeConsoleAccessGuide(&out, port); err != nil {
			t.Fatal(err)
		}
		command := fmt.Sprintf("ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:%d:127.0.0.1:%d SSH_USER@SSH_HOST", port, port)
		if !strings.Contains(out.String(), command) || strings.Contains(out.String(), "0.0.0.0") {
			t.Fatal("unsafe or mismatched forwarding", out.String())
		}
	}
	for _, port := range []int{-1, 0, 65536} {
		var out bytes.Buffer
		if writeConsoleAccessGuide(&out, port) == nil || out.Len() != 0 {
			t.Fatal("invalid port emitted")
		}
	}
	if writeConsoleAccessGuide(failingConsoleWriter{}, 47611) == nil {
		t.Fatal("output error ignored")
	}
}

type failingConsoleWriter struct{}

func (failingConsoleWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

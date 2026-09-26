//go:build linux

package main

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

func TestUserServiceStatusReadOnlyAndNotHealthProof(t *testing.T) {
	for _, state := range []string{"active", "inactive", "failed", "activating"} {
		calls := 0
		status, err := readUserServiceStatus(context.Background(), func(_ context.Context, args ...string) ([]byte, error) {
			calls++
			want := []string{"--user", "show", "--no-pager", "--property=LoadState,ActiveState,UnitFileState", enterpriseUnitName}
			if !reflect.DeepEqual(args, want) {
				t.Fatalf("unexpected command: %v", args)
			}
			return []byte("LoadState=loaded\nActiveState=" + state + "\nUnitFileState=enabled\n"), nil
		})
		if err != nil || calls != 1 || status.ActiveState != state || status.LoadState != "loaded" || status.UnitFileState != "enabled" {
			t.Fatalf("%+v %v", status, err)
		}
		if status.HeartbeatVerified || status.DiscoveryVerified || status.ProtectionVerified {
			t.Fatal("invented health proof")
		}
	}
}

func TestUserServiceStatusMissingAndUnknownValues(t *testing.T) {
	status, err := readUserServiceStatus(context.Background(), func(context.Context, ...string) ([]byte, error) {
		return []byte("LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"), nil
	})
	if err != nil || status.LoadState != "not-found" || status.UnitFileState != "unknown" {
		t.Fatal(status, err)
	}
	status, err = readUserServiceStatus(context.Background(), func(context.Context, ...string) ([]byte, error) {
		return []byte("LoadState=/private/path\nActiveState=future-state\nUnitFileState=secret\n"), nil
	})
	if err != nil || status.LoadState != "unknown" || status.ActiveState != "unknown" || status.UnitFileState != "unknown" {
		t.Fatal(status, err)
	}
}

func TestUserServiceStatusRejectsIncompleteOrLeakingOutput(t *testing.T) {
	for _, raw := range []string{"", "LoadState=loaded\n", "private diagnostic", strings.Repeat("x", 4097),
		"LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nEnvironment=secret\n",
		"LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nActiveState=inactive\n"} {
		_, err := readUserServiceStatus(context.Background(), func(context.Context, ...string) ([]byte, error) { return []byte(raw), nil })
		if err != errUserServiceStatus {
			t.Fatalf("invalid manager output accepted: %v", err)
		}
	}
	_, err := readUserServiceStatus(context.Background(), func(context.Context, ...string) ([]byte, error) {
		return []byte("secret"), errors.New("private diagnostic")
	})
	if err != errUserServiceStatus {
		t.Fatal(err)
	}
}

func TestUserServiceStatusCancellationFlagsAndOutputBound(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := readUserServiceStatus(ctx, func(context.Context, ...string) ([]byte, error) {
		t.Fatal("called after cancellation")
		return nil, nil
	})
	if err != errUserServiceStatus {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"--start"}, {"other.service"}, {"--system"}, {"extra"}} {
		if cmdUserServiceStatus(context.Background(), args) != errUserServiceStatus {
			t.Fatal("accepted mutation/target flag")
		}
	}
	var output serviceStatusBuffer
	if _, err := output.Write([]byte(strings.Repeat("x", 4096))); err != nil {
		t.Fatal(err)
	}
	if _, err := output.Write([]byte("x")); err != errUserServiceStatus || output.Len() != 4096 {
		t.Fatal("output unbounded", err)
	}
}

func TestUserServiceStatusCancelAfterRunnerReturns(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	_, err := readUserServiceStatus(ctx, func(context.Context, ...string) ([]byte, error) {
		cancel()
		return []byte("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"), nil
	})
	if err != errUserServiceStatus {
		t.Fatal("canceled query treated as success:", err)
	}
}

func TestUserServiceStatusHelpDoesNotRunSystemctl(t *testing.T) {
	for _, args := range [][]string{{"-h"}, {"--help"}} {
		calls := 0
		var out strings.Builder
		err := runUserServiceStatus(context.Background(), args, &out, func(context.Context, ...string) ([]byte, error) {
			calls++
			return nil, nil
		})
		if err != nil || calls != 0 {
			t.Fatalf("help handled wrong: err=%v calls=%d", err, calls)
		}
		text := out.String()
		if !strings.Contains(text, "Read-only") || !strings.Contains(text, enterpriseUnitName) || !strings.Contains(text, "not proof of") {
			t.Fatal("help missing read-only/evidence-boundary text:", text)
		}
	}
}

func TestUserServiceStatusJSONOnlyOnStdoutAndEncodeFailure(t *testing.T) {
	var out strings.Builder
	calls := 0
	err := runUserServiceStatus(context.Background(), nil, &out, func(context.Context, ...string) ([]byte, error) {
		calls++
		return []byte("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"), nil
	})
	if err != nil || calls != 1 {
		t.Fatalf("status query failed: err=%v calls=%d", err, calls)
	}
	if text := out.String(); !strings.HasPrefix(text, "{\"schema_version\":\"enterprise-user-service-status/v1\"") || strings.Contains(text, "Read-only") {
		t.Fatal("stdout is not pure status JSON:", text)
	}
	if err := runUserServiceStatus(context.Background(), nil, errWriter{}, func(context.Context, ...string) ([]byte, error) {
		return []byte("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"), nil
	}); err == nil {
		t.Fatal("encode failure swallowed")
	}
}

type errWriter struct{}

func (errWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

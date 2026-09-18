package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

func TestWindowsProfileCommandConfirmationBeforeStateAccess(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "missing-state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	for _, args := range [][]string{nil, {"--confirm=false"}, {"--confirm", "unexpected"}, {"--unknown"}} {
		var out bytes.Buffer
		if err := cmdStateEnableWindowsResources(args, &out); err == nil {
			t.Fatal("invalid confirmation accepted")
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("unconfirmed access created state", err)
		}
	}
}

func TestWindowsProfileCommandContractAndRetry(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native Windows activation only")
	}
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", filepath.Join(t.TempDir(), "state"))
	var out bytes.Buffer
	if err := cmdInitialize(nil, &out); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &out); err != nil {
		t.Fatal(err)
	}
	fixture, err := os.ReadFile("../../testdata/contracts/local-state-windows-profile-result.json")
	var got, expected map[string]any
	if err != nil || json.Unmarshal(out.Bytes(), &got) != nil || json.Unmarshal(fixture, &expected) != nil || !reflect.DeepEqual(got, expected) {
		t.Fatal("activation result contract differs", err)
	}
	out.Reset()
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &out); err != nil {
		t.Fatal(err)
	}
	if json.Unmarshal(out.Bytes(), &got) != nil || got["status"] != "up_to_date" {
		t.Fatal("retry result")
	}
}

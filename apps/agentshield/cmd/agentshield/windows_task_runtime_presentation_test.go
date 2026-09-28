package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestTaskRuntimeDoesNotClaimExitOrHealth(t *testing.T) {
	var out bytes.Buffer
	if err := writeWindowsTaskRuntime(&out, windowsTaskRuntime{State: "running", Instances: 1, LastResult: 267009}); err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{"state=running instances=1 last_result=267009", "last_result_kind=scheduler_running", "health=unverified"} {
		if !strings.Contains(out.String(), value) {
			t.Fatalf("missing %s", value)
		}
	}
}

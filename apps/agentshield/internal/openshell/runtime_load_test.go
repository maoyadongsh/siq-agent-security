package openshell

import (
	"strings"
	"testing"
)

func TestSandboxLoadedInstanceRejectsAmbiguousOrUnreadyReadback(t *testing.T) {
	const valid = `[{"id":"de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2","name":"s1","phase":"Ready","current_policy_version":1}]`
	cases := []struct {
		name, output string
		wantOK       bool
	}{
		{"ready_exact", valid, true},
		{"not_ready", strings.Replace(valid, `"Ready"`, `"Provisioning"`, 1), false},
		{"wrong_revision", strings.Replace(valid, `"current_policy_version":1`, `"current_policy_version":2`, 1), false},
		{"wrong_target", strings.Replace(valid, `"name":"s1"`, `"name":"other"`, 1), false},
		{"bad_id", strings.Replace(valid, `de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2`, `not-an-id`, 1), false},
		{"duplicate_target", strings.TrimSuffix(valid, "]") + "," + strings.TrimPrefix(valid, "["), false},
		{"trailing_document", valid + `{}`, false},
		{"malformed", `[{`, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := New(Options{Runner: func(args []string) (int, string, string) {
				if !taskSandboxListArgs(args) {
					t.Fatalf("unexpected CLI args %q", args)
				}
				return 0, tc.output, ""
			}})
			id, err := c.sandboxLoadedInstance("s1", "1")
			if tc.wantOK {
				if err != nil || id != "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2" {
					t.Fatalf("ready exact sandbox refused: id=%q err=%v", id, err)
				}
			} else if err == nil || id != "" {
				t.Fatalf("bad runtime state accepted: id=%q err=%v", id, err)
			}
		})
	}
}

func TestExecTaskReadOnlyLoadProofBindsSandboxIDAndInvalidatesOnReplacement(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	c := taskClient(0, taskFixtureOutput, spy)
	snap, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	req := TaskExecRequest{
		Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
		OutputLimit: 64 << 10, PolicyRevision: snap.Revision, PolicyDigest: snap.PolicyDigest,
	}
	list := taskSandboxList(taskFixtureOutput)
	c.Runner = func(args []string) (int, string, string) {
		if taskSandboxListArgs(args) {
			return 0, list, ""
		}
		return 0, taskFixtureOutput, ""
	}
	if out, err := c.ExecTask(req, allowAll); err != nil || out.State != TaskStateSucceeded || spy.calls() != 1 {
		t.Fatalf("fresh read-only load proof did not authorize task: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	list = strings.Replace(list, "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2", "ae99ab6a-8e47-487d-8f69-6e5b6ae9c7a2", 1)
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("replacement sandbox reused old proof: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	list = taskSandboxList(taskFixtureOutput)
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("old sandbox ID resurrected invalidated proof: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

func TestExecTaskEffectivePolicyRequiresIndependentSandboxLoadReadback(t *testing.T) {
	// The real 0.0.83 gateway reports a pre-existing loaded policy as
	// Status: Effective without a Loaded timestamp. The sandbox row supplies
	// the separate load acknowledgement for that exact revision and instance.
	effective := strings.Replace(taskFixtureOutput, "Status:       Loaded\n", "Status:       Effective\n", 1)
	effective = strings.Replace(effective, "Loaded:       1001 ms\n", "", 1)
	for _, tc := range []struct {
		name, phase, version, status string
		wantSpawn                    bool
	}{
		{"ready_current", "Ready", "1", "Effective", true},
		{"provisioning", "Provisioning", "1", "Effective", false},
		{"old_loaded_version", "Ready", "2", "Effective", false},
		{"pending_status", "Ready", "1", "Pending", false},
		{"unknown_status", "Ready", "1", "Unknown", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output := strings.Replace(effective, "Status:       Effective", "Status:       "+tc.status, 1)
			spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
			c := taskClient(0, output, spy)
			list := taskSandboxList(output)
			list = strings.Replace(list, `"phase":"Ready"`, `"phase":"`+tc.phase+`"`, 1)
			list = strings.Replace(list, `"current_policy_version":1`, `"current_policy_version":`+tc.version, 1)
			c.Runner = func(args []string) (int, string, string) {
				if taskSandboxListArgs(args) {
					return 0, list, ""
				}
				return 0, output, ""
			}
			snap, err := c.ReadEffective("s1")
			if err != nil {
				t.Fatal(err)
			}
			if snap.LoadEpoch != "" || snap.PolicyStatus != tc.status {
				t.Fatalf("status evidence misparsed: %+v", snap)
			}
			req := TaskExecRequest{
				Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
				OutputLimit: 64 << 10, PolicyRevision: snap.Revision, PolicyDigest: snap.PolicyDigest,
			}
			out, err := c.ExecTask(req, allowAll)
			if tc.wantSpawn {
				if err != nil || out.State != TaskStateSucceeded || spy.calls() != 1 {
					t.Fatalf("effective loaded policy refused: out=%+v err=%v calls=%d", out, err, spy.calls())
				}
			} else if err == nil || out.Spawned || spy.calls() != 0 {
				t.Fatalf("unloaded policy spawned task: out=%+v err=%v calls=%d", out, err, spy.calls())
			}
		})
	}
}

func TestExecTaskNewLoadedRevisionNeedsNewApprovalAndSameSandboxInstance(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	c := taskClient(0, taskFixtureOutput, spy)
	first, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	request := TaskExecRequest{Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
		OutputLimit: 64 << 10, PolicyRevision: first.Revision, PolicyDigest: first.PolicyDigest}
	current := taskFixtureOutput
	instance := taskSandboxList(current)
	c.Runner = func(args []string) (int, string, string) {
		if taskSandboxListArgs(args) {
			return 0, instance, ""
		}
		return 0, current, ""
	}
	if _, err := c.ExecTask(request, allowAll); err != nil {
		t.Fatal(err)
	}
	current = strings.ReplaceAll(taskFixtureOutput, "1", "2")
	instance = taskSandboxList(current)
	second, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	if second.Revision == first.Revision || second.PolicyDigest == first.PolicyDigest {
		t.Fatal("fixture did not change the policy identity")
	}
	if out, err := c.ExecTask(request, allowAll); err == nil || out.Spawned || spy.calls() != 1 {
		t.Fatalf("old approval survived a new revision: out=%+v err=%v", out, err)
	}
	request.PolicyRevision, request.PolicyDigest = second.Revision, second.PolicyDigest
	if out, err := c.ExecTask(request, allowAll); err != nil || out.State != TaskStateSucceeded || spy.calls() != 2 {
		t.Fatalf("fresh approval for independently loaded revision refused: out=%+v err=%v", out, err)
	}
	instance = strings.Replace(instance, "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2", "ae99ab6a-8e47-487d-8f69-6e5b6ae9c7a2", 1)
	if out, err := c.ExecTask(request, allowAll); err == nil || out.Spawned || spy.calls() != 2 {
		t.Fatalf("replacement instance reused a fresh approval: out=%+v err=%v", out, err)
	}
}

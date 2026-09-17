package openshell

// O05 v6 D02 task-execution primitive tests.
//
// Evidence level: 单测（注入 TaskRunner）. The injected runner replaces ONLY
// the process spawn, so every gate, ordering rule and refusal decision below
// is the same code path production uses. Nothing here proves a real sandbox
// command ran; that is D05's job against a live sandbox.
//
// Each check has a positive case (the request is allowed through and the
// argv/limits are exactly the approved ones), a negative case (authority or
// binding is wrong and nothing spawns) and, where the outcome is a fact about
// the world rather than about us, a fault case (the local bound fires and the
// result must stay uncertain rather than being reported as success or failure).

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// taskSpy records every spawn attempt so a refusal can be proven to have
// happened before any process was started.
type taskSpy struct {
	mu      sync.Mutex
	argv    [][]string
	timeout time.Duration
	limit   int
	result  TaskRunResult
}

func (s *taskSpy) runner() TaskRunner {
	return func(ctx context.Context, args []string, timeout time.Duration, limit int) TaskRunResult {
		s.mu.Lock()
		defer s.mu.Unlock()
		s.argv = append(s.argv, append([]string(nil), args...))
		s.timeout, s.limit = timeout, limit
		return s.result
	}
}

func (s *taskSpy) calls() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.argv)
}

func (s *taskSpy) lastArgv() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.argv) == 0 {
		return nil
	}
	return s.argv[len(s.argv)-1]
}

// taskClient builds a client bound to the fixture env pair (so
// InvocationFingerprint is non-empty) whose `policy get` returns readRC/output.
// spy == nil leaves TaskRunner unset: the default subprocess path would spawn a
// real process, so those tests must never reach a spawn.
func taskClient(readRC int, output string, spy *taskSpy) *Client {
	opts := Options{
		policyCoordinator: newPolicyCoordinator(),
		LookupEnv: func(key string) (string, bool) {
			switch key {
			case envCLIBin:
				return "/fixture/openshell", true
			case envEndpoint:
				return "https://127.0.0.1:17671", true
			}
			return "", false
		},
		Runner: func(args []string) (int, string, string) {
			if len(args) == 4 && args[0] == "policy" && args[1] == "get" && args[3] == "--full" {
				return readRC, output, ""
			}
			if taskSandboxListArgs(args) {
				return 0, taskSandboxList(output), ""
			}
			return 1, "", "unexpected args: " + strings.Join(args, " ")
		},
		PollInterval: -1,
	}
	if spy != nil {
		opts.TaskRunner = spy.runner()
	}
	return New(opts)
}

const taskFixtureOutput = "Version:      1\nStatus:       Loaded\nActive:       1\nLoaded:       1001 ms\n---\nversion: 1\nfilesystem_policy:\n  include_workdir: true\n  read_only:\n  - /usr\n"

func taskSandboxListArgs(args []string) bool {
	return reflect.DeepEqual(args, []string{"sandbox", "list", "--limit", "1000", "--output", "json"})
}

func taskSandboxList(policyOutput string) string {
	revision, _ := parseActiveRevision(policyOutput)
	return fmt.Sprintf(`[{"id":"de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2","name":"s1","phase":"Ready","current_policy_version":%s}]`, revision)
}

func TestExecTaskRejectsStaleLoadedTimestampWithNonLoadedStatus(t *testing.T) {
	for _, status := range []string{"Pending", "Failed", "Unknown", ""} {
		t.Run(status, func(t *testing.T) {
			spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
			c := taskClient(0, taskFixtureOutput, spy)
			req := taskRequest(t, c)
			current := strings.Replace(taskFixtureOutput, "Status:       Loaded\n", "Status:       "+status+"\n", 1)
			c.Runner = func(args []string) (int, string, string) { return 0, current, "" }
			if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
				t.Fatalf("non-loaded status reused old acknowledgement: outcome=%+v err=%v calls=%d", out, err, spy.calls())
			}
			current = taskFixtureOutput
			if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
				t.Fatalf("restored status resurrected old acknowledgement: outcome=%+v err=%v calls=%d", out, err, spy.calls())
			}
		})
	}
}

func TestExecTaskRejectsExpiredLoadAcknowledgement(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	c := taskClient(0, taskFixtureOutput, spy)
	req := taskRequest(t, c)
	key := c.loadedPolicyKey(req.Target)
	c.policy.operationsMu.Lock()
	old := c.policy.loaded[key]
	old.confirmedAt = time.Now().Add(-loadedPolicyMaxAge - time.Second)
	c.policy.loaded[key] = old
	c.policy.operationsMu.Unlock()
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("expired --wait proof started task: outcome=%+v err=%v calls=%d", out, err, spy.calls())
	}
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("expired proof resurrected: outcome=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

func TestTaskCancellerDuplicateReleasePreservesObservedRun(t *testing.T) {
	c := newTaskCanceller()
	first, releaseFirst, firstRegistered := c.begin("reservation-1")
	second, releaseSecond, secondRegistered := c.begin("reservation-1")
	if !firstRegistered || secondRegistered {
		t.Fatal("duplicate execution key was not rejected")
	}
	defer releaseFirst()
	releaseSecond()
	if !c.observing("reservation-1") {
		t.Fatal("duplicate release removed the original run's stop handle")
	}
	if !c.stop("reservation-1") || first.Err() != context.Canceled {
		t.Fatal("stop did not cancel the original observed run")
	}
	if second.Err() != context.Canceled {
		t.Fatal("released duplicate context was not cancelled")
	}
	releaseFirst()
	if c.observing("reservation-1") {
		t.Fatal("completed run retained a stop handle")
	}
}

func TestExecTaskDuplicateExecutionKeyCannotSpawnUnstoppableRun(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	c := taskClient(0, taskFixtureOutput, spy)
	req := taskRequest(t, c)
	req.ExecutionKey = "reservation-duplicate"
	_, release, registered := c.canceller().begin(req.ExecutionKey)
	if !registered {
		t.Fatal("fixture did not register the first run")
	}
	defer release()
	out, err := c.ExecTask(req, allowAll)
	if err == nil || err.Error() != errTaskDuplicateKey || out.State != TaskStateFailed ||
		out.TaskExecuted != TaskExecutedUnknown || out.Spawned || spy.calls() != 0 {
		t.Fatalf("duplicate started or closed a possible concurrent run: outcome=%+v err=%v calls=%d", out, err, spy.calls())
	}
	if !c.IsObservingLocalTask(req.ExecutionKey) {
		t.Fatal("duplicate refusal removed the first run's handle")
	}
}

func TestTaskCancellerDoesNotCancelWhenStopRecordFails(t *testing.T) {
	c := newTaskCanceller()
	run, release, registered := c.begin("reservation-2")
	if !registered {
		t.Fatal("first execution key registration was rejected")
	}
	defer release()
	wantErr := errors.New("record unavailable")
	stopped, err := c.stopRecorded("reservation-2", func(active bool) error {
		if !active {
			return errors.New("lost observed run")
		}
		return wantErr
	})
	if stopped || !errors.Is(err, wantErr) || run.Err() != nil {
		t.Fatalf("failed record caused cancellation: stopped=%v err=%v runErr=%v", stopped, err, run.Err())
	}
	stopped, err = c.stopRecorded("reservation-2", func(active bool) error {
		if !active {
			return errors.New("lost observed run")
		}
		return nil
	})
	if !stopped || err != nil || run.Err() != context.Canceled {
		t.Fatalf("recorded stop did not cancel: stopped=%v err=%v runErr=%v", stopped, err, run.Err())
	}
}

func TestTaskCancellerKeepsHandleStableUntilRecordedStopCancels(t *testing.T) {
	c := newTaskCanceller()
	run, release, registered := c.begin("reservation-3")
	if !registered {
		t.Fatal("first execution key registration was rejected")
	}
	entered := make(chan struct{})
	unblock := make(chan struct{})
	type result struct {
		stopped bool
		err     error
	}
	stopped := make(chan result, 1)
	go func() {
		ok, err := c.stopRecorded("reservation-3", func(active bool) error {
			if !active {
				return errors.New("lost observed run")
			}
			close(entered)
			<-unblock
			return nil
		})
		stopped <- result{ok, err}
	}()
	<-entered
	released := make(chan struct{})
	go func() { release(); close(released) }()
	close(unblock)
	select {
	case got := <-stopped:
		if !got.stopped || got.err != nil || run.Err() != context.Canceled {
			t.Fatalf("stop did not cancel held handle: %+v runErr=%v", got, run.Err())
		}
	case <-time.After(5 * time.Second):
		t.Fatal("recorded stop deadlocked")
	}
	select {
	case <-released:
	case <-time.After(5 * time.Second):
		t.Fatal("run release deadlocked")
	}
}

// taskRequest builds a request whose approved revision/digest match what the
// fixture backend currently reports, so only the field under test can make it
// fail.
func taskRequest(t *testing.T, c *Client) TaskExecRequest {
	t.Helper()
	snap, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	// This fixture models a successful earlier policy set --wait and matching
	// readback. Dedicated tests below prove that readback without this separate
	// confirmation cannot launch a task.
	c.rememberLoadedPolicy("s1", snap.Revision, snap.PolicyDigest, snap.LoadEpoch)
	return TaskExecRequest{
		Target: "s1", Argv: []string{"/bin/echo", "canary"},
		TimeoutSeconds: 30, OutputLimit: 64 << 10,
		PolicyRevision: snap.Revision, PolicyDigest: snap.PolicyDigest,
	}
}

func allowAll() error { return nil }

// TestTaskExecArgsKeepTheCommandAfterTheSeparator pins the one structural
// property that keeps an approved command from being re-read as CLI options:
// everything the caller approved appears strictly after "--", in argv order,
// and the string is never handed to a shell.
func TestTaskExecArgsKeepTheCommandAfterTheSeparator(t *testing.T) {
	hostile := []string{"--gateway-endpoint", "https://evil.example", "-n", "other-sandbox", "; rm -rf /"}
	got := taskExecArgs(TaskExecRequest{Target: "s1", Argv: hostile, TimeoutSeconds: 30})
	want := []string{"sandbox", "exec", "-n", "s1", "--timeout", "30", "--no-tty", "--"}
	want = append(want, hostile...)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("argv mismatch\n got %q\nwant %q", got, want)
	}
	if i := indexOf(got, "--"); i < 0 || i != len(got)-len(hostile)-1 {
		t.Fatalf("separator must sit immediately before the command: %q", got)
	}
	// No element may carry shell metacharacters re-interpretation: the command
	// arrives as discrete argv elements and the worst element is preserved
	// verbatim rather than being split or quoted.
	if got[len(got)-1] != "; rm -rf /" {
		t.Fatalf("argv element was rewritten: %q", got)
	}
	for _, a := range got {
		if a == "-c" || strings.HasSuffix(a, "bash") || strings.HasSuffix(a, "sh") {
			t.Fatalf("a shell appeared in the CLI argv: %q", got)
		}
	}
	// The workdir flag, when approved, is also emitted before the separator.
	withDir := taskExecArgs(TaskExecRequest{Target: "s1", Argv: []string{"/bin/true"}, Workdir: "/sandbox/work", TimeoutSeconds: 5})
	if !reflect.DeepEqual(withDir, []string{"sandbox", "exec", "-n", "s1", "--workdir", "/sandbox/work", "--timeout", "5", "--no-tty", "--", "/bin/true"}) {
		t.Fatalf("workdir argv: %q", withDir)
	}
}

func indexOf(items []string, want string) int {
	for i, item := range items {
		if item == want {
			return i
		}
	}
	return -1
}

func TestExecTaskRefusesInvalidShapeBeforeSpawning(t *testing.T) {
	spy := &taskSpy{}
	c := taskClient(0, taskFixtureOutput, spy)
	valid := taskRequest(t, c)

	cases := []struct {
		name   string
		mutate func(TaskExecRequest) TaskExecRequest
	}{
		{"empty argv", func(r TaskExecRequest) TaskExecRequest { r.Argv = nil; return r }},
		{"empty argv element", func(r TaskExecRequest) TaskExecRequest { r.Argv = []string{"echo", ""}; return r }},
		{"nul in argv element", func(r TaskExecRequest) TaskExecRequest { r.Argv = []string{"echo", "a\x00b"}; return r }},
		{"argv element too long", func(r TaskExecRequest) TaskExecRequest { r.Argv = []string{strings.Repeat("a", 4097)}; return r }},
		{"too many argv elements", func(r TaskExecRequest) TaskExecRequest {
			r.Argv = make([]string, 257)
			for i := range r.Argv {
				r.Argv[i] = "x"
			}
			return r
		}},
		{"empty target", func(r TaskExecRequest) TaskExecRequest { r.Target = ""; return r }},
		{"option-shaped target", func(r TaskExecRequest) TaskExecRequest { r.Target = "-n"; return r }},
		{"relative workdir", func(r TaskExecRequest) TaskExecRequest { r.Workdir = "sandbox/work"; return r }},
		{"traversal workdir", func(r TaskExecRequest) TaskExecRequest { r.Workdir = "/tmp/../etc"; return r }},
		{"control char in workdir", func(r TaskExecRequest) TaskExecRequest { r.Workdir = "/tmp/\n"; return r }},
		{"timeout below floor", func(r TaskExecRequest) TaskExecRequest { r.TimeoutSeconds = 0; return r }},
		{"timeout above ceiling", func(r TaskExecRequest) TaskExecRequest { r.TimeoutSeconds = 901; return r }},
		{"output limit below floor", func(r TaskExecRequest) TaskExecRequest { r.OutputLimit = 1024; return r }},
		{"output limit above ceiling", func(r TaskExecRequest) TaskExecRequest { r.OutputLimit = 2 << 20; return r }},
		{"non-canonical revision", func(r TaskExecRequest) TaskExecRequest { r.PolicyRevision = "01"; return r }},
		{"empty revision", func(r TaskExecRequest) TaskExecRequest { r.PolicyRevision = ""; return r }},
		{"short digest", func(r TaskExecRequest) TaskExecRequest { r.PolicyDigest = "abc"; return r }},
		{"uppercase digest", func(r TaskExecRequest) TaskExecRequest {
			r.PolicyDigest = strings.ToUpper(r.PolicyDigest)
			return r
		}},
	}
	for _, tc := range cases {
		out, err := c.ExecTask(tc.mutate(valid), allowAll)
		if err == nil || err.Error() != errTaskInvalidShape {
			t.Fatalf("%s: err=%v want %s", tc.name, err, errTaskInvalidShape)
		}
		if out.State != TaskStateRefused || out.TaskExecuted != TaskExecutedNo || !out.PreflightRefused || out.Spawned {
			t.Fatalf("%s: shape rejection must be provably not-executed: %+v", tc.name, out)
		}
		if out.Refusal != errTaskInvalidShape {
			t.Fatalf("%s: refusal code %q", tc.name, out.Refusal)
		}
	}
	if spy.calls() != 0 {
		t.Fatalf("invalid shapes reached the runner %d times", spy.calls())
	}
}

func TestExecTaskRequiresBoundBackendAndLiveAuthorization(t *testing.T) {
	spy := &taskSpy{}
	bound := taskClient(0, taskFixtureOutput, spy)
	req := taskRequest(t, bound)

	// Cache fingerprints for invalid/unconfigured clients are not endpoint bindings.
	for _, mode := range []string{"missing", "path", "half_pair", "invalid_endpoint", "script"} {
		t.Run(mode, func(t *testing.T) {
			opts := Options{PollInterval: -1, LookPath: missingPATH(),
				LookupEnv: func(key string) (string, bool) {
					if mode == "half_pair" && key == envCLIBin {
						return "/fixture/openshell", true
					}
					if mode == "invalid_endpoint" {
						if key == envCLIBin {
							return "/fixture/openshell", true
						}
						if key == envEndpoint {
							return "not-an-endpoint", true
						}
					}
					return "", false
				},
				Runner: func([]string) (int, string, string) {
					t.Fatal("unbound client performed backend I/O")
					return 1, "", ""
				},
			}
			if mode == "path" {
				opts.LookPath = func(string) (string, error) { return "/fixture/openshell", nil }
			}
			if mode == "script" {
				opts.EnvScript = "/fixture/env.sh"
			}
			unbound := New(opts)
			out, err := unbound.ExecTask(req, allowAll)
			if err == nil || err.Error() != errTaskBackendUnbound || out.Spawned || out.TaskExecuted != TaskExecutedNo {
				t.Fatalf("unbound backend outcome=%+v err=%v", out, err)
			}
			if err := unbound.VerifyTaskPolicyLoaded(req.Target, req.PolicyRevision, req.PolicyDigest, req.NetworkTargets); err == nil || err.Error() != errTaskBackendUnbound {
				t.Fatalf("unbound policy check err=%v", err)
			}
			if _, err := unbound.CurrentTaskSandboxID(req.Target, req.PolicyRevision); err == nil || err.Error() != errTaskBackendUnbound {
				t.Fatalf("unbound instance check err=%v", err)
			}
		})
	}

	// No authorization closure at all is a programming error, not a pass.
	if _, err := bound.ExecTask(req, nil); err == nil || err.Error() != errTaskNotAuthorized {
		t.Fatalf("nil authorize err=%v", err)
	}

	// A revoked approval must stop the start even though everything else is
	// still valid — the closure runs immediately before the spawn.
	calls := 0
	revoked := func() error { calls++; return errors.New("approval revoked") }
	out, err := bound.ExecTask(req, revoked)
	if err == nil || err.Error() != errTaskNotAuthorized {
		t.Fatalf("revoked authorize err=%v", err)
	}
	if calls != 1 {
		t.Fatalf("authorize must be re-checked exactly once: %d", calls)
	}
	if out.State != TaskStateRefused || out.PreflightRefused != true || out.TaskExecuted != TaskExecutedNo || out.Refusal != "approval revoked" {
		t.Fatalf("revoked outcome: %+v", out)
	}
	if spy.calls() != 0 {
		t.Fatalf("revoked approval still spawned %d times", spy.calls())
	}
}

func TestExecTaskRequiresTheApprovedPolicyToStillBeLoaded(t *testing.T) {
	spy := &taskSpy{}
	c := taskClient(0, taskFixtureOutput, spy)
	valid := taskRequest(t, c)

	drift := valid
	drift.PolicyRevision = "2"
	if _, err := c.ExecTask(drift, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded {
		t.Fatalf("revision drift err=%v", err)
	}
	digest := valid
	digest.PolicyDigest = strings.Repeat("0", 64)
	if _, err := c.ExecTask(digest, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded {
		t.Fatalf("digest drift err=%v", err)
	}
	// A backend that cannot be read at all is not "assume still loaded".
	broken := taskClient(1, "", spy)
	if _, err := broken.ExecTask(valid, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded {
		t.Fatalf("unreadable policy err=%v", err)
	}
	if spy.calls() != 0 {
		t.Fatalf("policy gate let %d spawns through", spy.calls())
	}
}

func TestExecTaskReadbackWithoutRuntimeLoadConfirmationNeverSpawns(t *testing.T) {
	spy := &taskSpy{}
	c := taskClient(0, taskFixtureOutput, spy)
	readOnly := func(args []string) (int, string, string) {
		if len(args) == 4 && args[0] == "policy" && args[1] == "get" {
			return 0, taskFixtureOutput, ""
		}
		return 1, "", "runtime load status unavailable"
	}
	c.Runner = readOnly
	snap, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	req := TaskExecRequest{
		Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
		OutputLimit: 64 << 10, PolicyRevision: snap.Revision, PolicyDigest: snap.PolicyDigest,
	}
	out, err := c.ExecTask(req, allowAll)
	if err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("readback without load proof launched task: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	// A new process cannot inherit another process's in-memory confirmation.
	other := taskClient(0, taskFixtureOutput, spy)
	other.policy = newPolicyCoordinator()
	other.Runner = readOnly
	if _, err := other.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded {
		t.Fatalf("new client accepted an unconfirmed revision: %v", err)
	}
	if spy.calls() != 0 {
		t.Fatalf("unconfirmed task reached runner %d times", spy.calls())
	}
}

func TestExecTaskNoOpPolicyApplyCannotInventLoadProof(t *testing.T) {
	spy := &taskSpy{}
	full := testdata(t, "policy_get_full_v2.txt")
	setCalls := 0
	c := New(Options{
		policyCoordinator: newPolicyCoordinator(), PollInterval: -1,
		LookupEnv: func(key string) (string, bool) {
			switch key {
			case envCLIBin:
				return "/fixture/openshell", true
			case envEndpoint:
				return "https://127.0.0.1:17671", true
			}
			return "", false
		},
		Runner: func(args []string) (int, string, string) {
			if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
				return 0, full, ""
			}
			if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
				setCalls++
				return 0, "Policy unchanged (version 2, hash: c0ffee)", ""
			}
			return 1, "", "unexpected"
		}, TaskRunner: spy.runner(),
	})
	base, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	noOp, err := c.ApplyNetwork("s1", []NetworkRule{{
		Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}, RuleName: "siq-as-rule-0",
	}}, base.Revision)
	if err != nil || noOp.Result != "no_op" || setCalls != 0 {
		t.Fatalf("fixture did not take no-op path: rec=%+v err=%v writes=%d", noOp, err, setCalls)
	}
	req := TaskExecRequest{Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
		OutputLimit: 64 << 10, PolicyRevision: base.Revision, PolicyDigest: base.PolicyDigest}
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("no-op invented load confirmation: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

func TestExecTaskRejectsEffectiveNetworkBeyondApprovedTargets(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	full := testdata(t, "policy_get_full_v2.txt")
	c := taskClient(0, full, spy)
	req := taskRequest(t, c)
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("undeclared effective network reached runner: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	// A new, separately loaded fixture with the endpoint explicitly approved
	// is allowed. Refusing the first call must not be a blanket task disable.
	c = taskClient(0, full, spy)
	req = taskRequest(t, c)
	req.NetworkTargets = []string{"api.example.com:443"}
	if out, err := c.ExecTask(req, allowAll); err != nil || out.State != TaskStateSucceeded || spy.calls() != 1 {
		t.Fatalf("approved effective network was refused: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

func TestExecTaskUnconfirmedPolicyWriteInvalidatesPriorLoad(t *testing.T) {
	spy := &taskSpy{}
	c := taskClient(0, taskFixtureOutput, spy)
	c.policy = newPolicyCoordinator()
	req := taskRequest(t, c)
	c.Runner = func(args []string) (int, string, string) {
		if len(args) == 4 && args[0] == "policy" && args[1] == "get" {
			return 0, taskFixtureOutput, ""
		}
		if len(args) >= 5 && args[0] == "policy" && args[1] == "set" {
			return 124, "Policy version 2 submitted (hash: c0ffee)", "load not confirmed"
		}
		return 1, "", "unexpected"
	}
	if _, err := c.ApplyNetwork("s1", []NetworkRule{{
		Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
	}}, req.PolicyRevision); err == nil {
		t.Fatal("unconfirmed policy write accepted")
	}
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 0 {
		t.Fatalf("stale load proof survived uncertain write: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

func TestExecTaskStartsOnlyAfterConfirmedPolicySet(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true}}
	c := taskClient(0, taskFixtureOutput, spy)
	active := taskFixtureOutput
	writes := 0
	c.Runner = func(args []string) (int, string, string) {
		if len(args) == 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if taskSandboxListArgs(args) {
			return 0, taskSandboxList(active), ""
		}
		if len(args) == 8 && args[0] == "policy" && args[1] == "set" {
			if !reflect.DeepEqual(args[5:], []string{"--wait", "--timeout", "28"}) {
				t.Errorf("load acknowledgement not bounded: %v", args)
				return 1, "", "unsupported"
			}
			body, err := os.ReadFile(args[4])
			if err != nil {
				t.Error(err)
				return 1, "", "read failed"
			}
			writes++
			active = policyOutput("2", string(body))
			return 0, "Policy version 2 submitted (hash: c0ffee)", "loaded"
		}
		return 1, "", "unexpected"
	}
	base, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	rec, err := c.ApplyNetwork("s1", []NetworkRule{{
		Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
	}}, base.Revision)
	if err != nil || rec.Result != "applied" || writes != 1 {
		t.Fatalf("confirmed policy apply: rec=%+v err=%v writes=%d", rec, err, writes)
	}
	req := TaskExecRequest{
		Target: "s1", Argv: []string{"/bin/true"}, TimeoutSeconds: 30,
		OutputLimit: 64 << 10, PolicyRevision: rec.BackendRevision, PolicyDigest: rec.AppliedPolicyDigest,
		NetworkTargets: []string{"api.example.com:443"},
	}
	if out, err := c.ExecTask(req, allowAll); err != nil || out.State != TaskStateSucceeded || spy.calls() != 1 {
		t.Fatalf("confirmed task: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	// The same policy content may be reloaded by a different gateway lifetime.
	// A changed or missing Loaded marker must not reuse the earlier --wait fact.
	confirmed := active
	active = strings.Replace(confirmed, "Loaded:       2 ms", "Loaded:       3 ms", 1)
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("changed load epoch reused old proof: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	active = confirmed
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("old marker resurrected invalidated proof: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	active = strings.Replace(confirmed, "Loaded:       2 ms\n", "", 1)
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("missing load epoch reused old proof: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	active = confirmed
	// A fresh process cannot inherit a prior --wait fact, and policy readback
	// without a current sandbox runtime status must still fail closed.
	c.policy = newPolicyCoordinator()
	savedRunner := c.Runner
	c.Runner = func(args []string) (int, string, string) {
		if taskSandboxListArgs(args) {
			return 1, "", "runtime status unavailable"
		}
		return savedRunner(args)
	}
	if out, err := c.ExecTask(req, allowAll); err == nil || err.Error() != errTaskPolicyNotLoaded || out.Spawned || spy.calls() != 1 {
		t.Fatalf("restart reused proof without runtime status: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
	// A separate fresh process may establish a new read-only proof when the
	// gateway again reports this exact sandbox ID, Ready phase and revision.
	c.policy = newPolicyCoordinator()
	c.Runner = savedRunner
	if out, err := c.ExecTask(req, allowAll); err != nil || out.State != TaskStateSucceeded || spy.calls() != 2 {
		t.Fatalf("fresh runtime load proof was not accepted: out=%+v err=%v calls=%d", out, err, spy.calls())
	}
}

// TestExecTaskOutcomeHonesty is the core contract: rc == 0 is the only status
// that proves the command ran and succeeded; every other result is reported as
// unknown rather than being rounded to success or to a clean failure.
func TestExecTaskOutcomeHonesty(t *testing.T) {
	cases := []struct {
		name            string
		result          TaskRunResult
		wantState       string
		wantExecuted    string
		wantUncertain   bool
		wantAttribution string
		wantErr         string
	}{
		{"remote success", TaskRunResult{ExitCode: 0, Spawned: true, Stdout: "ok\n"}, TaskStateSucceeded, TaskExecutedYes, false, TaskExitRemote, ""},
		{"remote nonzero exit", TaskRunResult{ExitCode: 7, Spawned: true, Stderr: "boom"}, TaskStateFailed, TaskExecutedUnknown, false, TaskExitRemoteOrLocal, ""},
		{"cli-side not found", TaskRunResult{ExitCode: 1, Spawned: true, Stderr: "sandbox not found"}, TaskStateFailed, TaskExecutedUnknown, false, TaskExitRemoteOrLocal, ""},
		{"missing remote binary", TaskRunResult{ExitCode: 127, Spawned: true}, TaskStateFailed, TaskExecutedUnknown, false, TaskExitRemoteOrLocal, ""},
		{"foreign gateway output", TaskRunResult{ExitCode: 0, Spawned: true, Stdout: "other gateway", Foreign: true}, TaskStateFailed, TaskExecutedUnknown, true, TaskExitRemoteOrLocal, ""},
		{"local time bound", TaskRunResult{BoundFired: TaskBoundTime, Spawned: true}, TaskStateTimedOut, TaskExecutedUnknown, true, TaskExitNone, ""},
		{"local output bound", TaskRunResult{BoundFired: TaskBoundOutput, Spawned: true}, TaskStateOutputLimited, TaskExecutedUnknown, true, TaskExitNone, ""},
		{"local pipe bound", TaskRunResult{BoundFired: TaskBoundPipe, Spawned: true}, TaskStateTimedOut, TaskExecutedUnknown, true, TaskExitNone, ""},
		{"process never started", TaskRunResult{ExitCode: -1, Spawned: false}, TaskStateRefused, TaskExecutedNo, false, TaskExitNone, errTaskSpawnFailed},
	}
	for _, tc := range cases {
		spy := &taskSpy{result: tc.result}
		c := taskClient(0, taskFixtureOutput, spy)
		out, err := c.ExecTask(taskRequest(t, c), allowAll)
		if tc.wantErr == "" {
			if err != nil {
				t.Fatalf("%s: unexpected error %v", tc.name, err)
			}
		} else if err == nil || err.Error() != tc.wantErr {
			t.Fatalf("%s: err=%v want %s", tc.name, err, tc.wantErr)
		}
		if out.State != tc.wantState || out.TaskExecuted != tc.wantExecuted || out.ExecutionUncertain != tc.wantUncertain {
			t.Fatalf("%s: state=%s executed=%s uncertain=%v (want %s/%s/%v)",
				tc.name, out.State, out.TaskExecuted, out.ExecutionUncertain, tc.wantState, tc.wantExecuted, tc.wantUncertain)
		}
		if out.ExitCodeAttribution != tc.wantAttribution {
			t.Fatalf("%s: attribution=%s want %s", tc.name, out.ExitCodeAttribution, tc.wantAttribution)
		}
		if spy.calls() != 1 {
			t.Fatalf("%s: expected exactly one spawn, got %d", tc.name, spy.calls())
		}
		// A fired local bound must never be reported as a clean remote outcome.
		if tc.wantUncertain && out.TaskExecuted == TaskExecutedYes {
			t.Fatalf("%s: uncertain outcome claimed execution success", tc.name)
		}
	}
}

// TestExecTaskPassesOnlyApprovedLimitsToTheRunner proves the observed window is
// derived from the approved request (plus the fixed local grace) and that the
// server-rebuilt request is what actually reaches the CLI.
func TestExecTaskPassesOnlyApprovedLimitsToTheRunner(t *testing.T) {
	spy := &taskSpy{result: TaskRunResult{ExitCode: 0, Spawned: true, Stdout: "hello"}}
	c := taskClient(0, taskFixtureOutput, spy)
	req := taskRequest(t, c)
	req.TimeoutSeconds = 45
	req.OutputLimit = 8192
	out, err := c.ExecTask(req, allowAll)
	if err != nil {
		t.Fatal(err)
	}
	spy.mu.Lock()
	timeout, limit := spy.timeout, spy.limit
	spy.mu.Unlock()
	if timeout != 45*time.Second+taskExecGrace {
		t.Fatalf("observation window %s must be the approved timeout plus the local grace", timeout)
	}
	if limit != 8192 {
		t.Fatalf("output limit %d not taken from the approved request", limit)
	}
	if want := taskExecArgs(req); !reflect.DeepEqual(spy.lastArgv(), want) {
		t.Fatalf("runner argv %q want %q", spy.lastArgv(), want)
	}
	// Only digests and byte counts leave this path.
	if out.StdoutBytes != len("hello") || out.StdoutDigest != taskDigest("hello") {
		t.Fatalf("stdout accounting: %+v", out)
	}
	if out.PolicyRevision != req.PolicyRevision || out.PolicyDigest != req.PolicyDigest {
		t.Fatalf("outcome must carry the policy it executed under: %+v", out)
	}
}

// TestRunBoundedTaskFaultCases exercises the real process path so the bounds
// are proven to fire rather than only to be returned by a fake.
func TestRunBoundedTaskFaultCases(t *testing.T) {
	trueBin, err := exec.LookPath("true")
	if err != nil {
		t.Skip("no true(1) on this host")
	}
	res := runBoundedTask(context.Background(), []string{trueBin}, nil, 5*time.Second, 4096)
	if !res.Spawned || res.ExitCode != 0 || res.BoundFired != TaskBoundNone {
		t.Fatalf("successful command: %+v", res)
	}

	falseBin, err := exec.LookPath("false")
	if err != nil {
		t.Skip("no false(1) on this host")
	}
	if res := runBoundedTask(context.Background(), []string{falseBin}, nil, 5*time.Second, 4096); !res.Spawned || res.ExitCode != 1 || res.BoundFired != TaskBoundNone {
		t.Fatalf("nonzero exit must survive as data: %+v", res)
	}

	sleepBin, err := exec.LookPath("sleep")
	if err != nil {
		t.Skip("no sleep(1) on this host")
	}
	start := time.Now()
	res = runBoundedTask(context.Background(), []string{sleepBin, "30"}, nil, 300*time.Millisecond, 4096)
	if res.BoundFired != TaskBoundTime || res.ExitCode != -1 || !res.Spawned {
		t.Fatalf("time bound: %+v", res)
	}
	if time.Since(start) > 10*time.Second {
		t.Fatalf("time bound did not cancel the child promptly")
	}

	headBin, err := exec.LookPath("head")
	if err != nil {
		t.Skip("no head(1) on this host")
	}
	res = runBoundedTask(context.Background(), []string{headBin, "-c", "1048576", "/dev/zero"}, nil, 10*time.Second, 4096)
	if res.BoundFired != TaskBoundOutput || res.ExitCode != -1 || !res.Spawned {
		t.Fatalf("output bound: %+v", res)
	}
}

func TestExecTaskRejectsRevocationDuringPolicyRead(t *testing.T) {
	spy := &taskSpy{}
	c := taskClient(0, taskFixtureOutput, spy)
	req := taskRequest(t, c)
	revoked := false
	c.Runner = func(args []string) (int, string, string) {
		revoked = true // Authority disappears while backend I/O is pending.
		if taskSandboxListArgs(args) {
			return 0, taskSandboxList(taskFixtureOutput), ""
		}
		return 0, taskFixtureOutput, ""
	}
	checks := 0
	out, err := c.ExecTask(req, func() error {
		checks++
		if revoked {
			return errors.New("revoked during readback")
		}
		return nil
	})
	if err == nil || checks != 2 || spy.calls() != 0 || out.Spawned || out.TaskExecuted != TaskExecutedNo {
		t.Fatalf("revoked task spawned: checks=%d calls=%d out=%+v err=%v", checks, spy.calls(), out, err)
	}
}

func TestExecTaskHoldsPolicyWriterLockUntilLocalRunSettles(t *testing.T) {
	c := taskClient(0, taskFixtureOutput, nil)
	req := taskRequest(t, c)
	entered, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	c.TaskRunner = func(ctx context.Context, args []string, timeout time.Duration, limit int) TaskRunResult {
		close(entered)
		<-release
		return TaskRunResult{ExitCode: 0, Spawned: true}
	}
	go func() { defer close(finished); _, _ = c.ExecTask(req, allowAll) }()
	defer func() { close(release); <-finished }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("task did not enter runner")
	}
	// ApplyNetwork and RollbackAuthorized take this exact coordinator lock.
	lock := c.targetPolicyLock(req.Target)
	if lock.TryLock() {
		lock.Unlock()
		t.Fatal("policy writer can alter policy while task is running")
	}
}

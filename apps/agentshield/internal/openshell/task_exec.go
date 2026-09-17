package openshell

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Bounded real task execution inside an EXISTING sandbox.
//
// This file adds execution; it does not add authority. Every gate that decides
// whether a command may run lives in the caller (the control plane) and is
// re-checked immediately before this function is allowed to spawn anything.
//
// Honesty rules encoded here:
//   - rc == 0 is the only exit status the CLI documents as the remote command's
//     own result, so it is the only status that can prove the command ran and
//     succeeded. Any other rc is ambiguous between "the remote command ran and
//     exited nonzero" and "the CLI itself failed before reaching the sandbox";
//     it proves the command did not succeed and nothing more.
//   - A local bound (timeout / output limit / local stop) firing means we stopped
//     observing, not that the remote command stopped. That is recorded as
//     uncertain and is never reconciled automatically.
//   - Preflight refusals are facts about our own control flow (we never spawned),
//     so they are the only outcomes that can be proven not_occurred.
//   - Killing the local CLI process is not a remote stop. SIQ does not have a
//     verified per-task remote stop confirmation path, so a local stop is
//     reported as stop_requested with an unknown remote outcome.

const (
	errTaskInvalidShape    = "openshell_task_invalid_shape"
	errTaskBackendUnbound  = "openshell_task_backend_unbound"
	errTaskNotAuthorized   = "openshell_task_not_authorized"
	errTaskPolicyNotLoaded = "openshell_task_policy_not_loaded"
	errTaskSpawnFailed     = "openshell_task_spawn_failed"
	errTaskDuplicateKey    = "openshell_task_duplicate_execution_key"
	// errTaskStopBeforeSpawn is the one stop outcome that is fully provable: a
	// stop arrived before the child existed, so nothing was started here.
	errTaskStopBeforeSpawn = "openshell_task_stop_before_spawn"
)

// TaskRefusalStopBeforeSpawn exposes errTaskStopBeforeSpawn to callers that
// must separate a provably-not-spawned stop from an unresolved one. Server-side
// evidence readers need that distinction to avoid two opposite errors: calling
// a denied binding a stop, or reporting uncertainty where a proof exists.
const TaskRefusalStopBeforeSpawn = errTaskStopBeforeSpawn

// Task execution states. These describe what WE can prove, not what we hope.
const (
	TaskStateSucceeded     = "succeeded"
	TaskStateFailed        = "failed"
	TaskStateTimedOut      = "timed_out"
	TaskStateOutputLimited = "output_limited"
	TaskStateRefused       = "refused"
	// TaskStateStopped is the outcome of a local stop request. It names what was
	// requested, not what happened remotely: the sandbox command may still run.
	TaskStateStopped = "stop_requested"
)

// TaskExecuted* is the tri-state answer to "did the command run in the sandbox".
// It is never collapsed into a boolean: "unknown" is a real answer.
const (
	TaskExecutedYes     = "yes"
	TaskExecutedNo      = "no"
	TaskExecutedUnknown = "unknown"
)

// Local bounds that can fire while the CLI is being observed.
const (
	TaskBoundNone   = ""
	TaskBoundTime   = "timeout"
	TaskBoundOutput = "output_limit"
	TaskBoundPipe   = "pipe_timeout"
	// TaskBoundStop is our own local termination, requested out of band. It is a
	// bound on observation like the others, not evidence about the remote side.
	TaskBoundStop = "stop_local"
)

// Exit-code attribution. "remote" is only claimable for a documented rc == 0.
const (
	TaskExitRemote        = "remote"
	TaskExitRemoteOrLocal = "remote_or_cli"
	TaskExitNone          = "none"
)

// taskExecGrace bounds the local observation window beyond the approved
// timeout, so a fired local bound is unambiguously our own bound and not the
// approved one.
const taskExecGrace = 15 * time.Second

// TaskExecRequest is the server-rebuilt plan. Every field is re-derived from
// signed state by the caller before this struct is constructed; nothing here
// is trusted merely because it arrived over HTTP.
type TaskExecRequest struct {
	Target         string
	Argv           []string
	NetworkTargets []string
	Workdir        string
	TimeoutSeconds int
	OutputLimit    int
	PolicyRevision string
	PolicyDigest   string
	// ExecutionKey is the reservation receipt id this run belongs to. It is the
	// only handle a stop request can use to reach this process, and it is not
	// authority: possessing the key lets a caller stop local observation, never
	// start or authorize anything.
	ExecutionKey string
}

// TaskExecOutcome carries only digests and byte counts: raw output is never
// retained on this path.
type TaskExecOutcome struct {
	State               string `json:"state"`
	TaskExecuted        string `json:"task_executed"`
	ExecutionUncertain  bool   `json:"execution_uncertain"`
	BoundFired          string `json:"bound_fired,omitempty"`
	Spawned             bool   `json:"spawned"`
	PreflightRefused    bool   `json:"preflight_refused"`
	Refusal             string `json:"refusal,omitempty"`
	ExitCode            int    `json:"exit_code"`
	ExitCodeAttribution string `json:"exit_code_attribution"`
	ForeignBackend      bool   `json:"foreign_backend,omitempty"`
	StdoutDigest        string `json:"stdout_digest"`
	StderrDigest        string `json:"stderr_digest"`
	StdoutBytes         int    `json:"stdout_bytes"`
	StderrBytes         int    `json:"stderr_bytes"`
	StartedAt           string `json:"started_at"`
	FinishedAt          string `json:"finished_at"`
	PolicyRevision      string `json:"policy_revision,omitempty"`
	PolicyDigest        string `json:"policy_digest,omitempty"`
}

// TaskRunResult preserves exactly what runBoundedCommand deliberately collapses
// for the policy path: the exit code as data and which bound fired. It never
// carries command arguments, and callers must not surface the raw text.
type TaskRunResult struct {
	ExitCode   int
	Stdout     string
	Stderr     string
	BoundFired string
	Foreign    bool
	Spawned    bool
}

// TaskRunner executes one bounded CLI argv. Tests inject a fake; production
// spawns the real CLI. Both go through ExecTask, so the binding, ordering and
// refusal logic under test is the same code that runs in production.
//
// ctx is a termination channel owned by the caller. Cancelling it stops local
// observation of the child; it never authorizes anything and never retries.
type TaskRunner func(ctx context.Context, args []string, timeout time.Duration, limit int) TaskRunResult

// runBoundedTask is runBoundedCommand's outcome-preserving sibling. It keeps
// the same budget/cancel discipline and the same rule that command arguments
// and backend text never leave this function except as raw buffers the caller
// digests.
//
// parent is checked before the exit-error branch on purpose: a killed child
// also yields *exec.ExitError, so treating that as an ordinary nonzero exit
// would report a requested stop as "the command ran and failed".
func runBoundedTask(parent context.Context, argv, env []string, timeout time.Duration, limit int) TaskRunResult {
	if len(argv) == 0 || limit <= 0 || timeout <= 0 {
		return TaskRunResult{ExitCode: -1, Spawned: false}
	}
	if parent == nil {
		parent = context.Background()
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	budget := &outputBudget{remaining: limit, cancel: cancel}
	out, diagnostic := &budgetWriter{budget: budget}, &budgetWriter{budget: budget}
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = env
	cmd.WaitDelay = 200 * time.Millisecond
	if timeout < cmd.WaitDelay {
		cmd.WaitDelay = timeout
	}
	cmd.Stdout, cmd.Stderr = out, diagnostic
	err := cmd.Run()
	rawOut, rawErr := out.buf.String(), diagnostic.buf.String()
	switch {
	case budget.exceeded:
		return TaskRunResult{ExitCode: -1, BoundFired: TaskBoundOutput, Spawned: true}
	case parent.Err() == context.Canceled:
		// A local stop was requested while we were observing. Spawned reports
		// only whether the child process existed; it says nothing about whether
		// the sandbox command ran or is still running.
		return TaskRunResult{ExitCode: -1, BoundFired: TaskBoundStop, Spawned: cmd.Process != nil}
	case ctx.Err() == context.DeadlineExceeded:
		return TaskRunResult{ExitCode: -1, BoundFired: TaskBoundTime, Spawned: true}
	case errors.Is(err, exec.ErrWaitDelay):
		return TaskRunResult{ExitCode: -1, BoundFired: TaskBoundPipe, Spawned: true}
	}
	foreign := looksLikeForeignGateway(rawOut + rawErr)
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return TaskRunResult{ExitCode: exitErr.ExitCode(), Stdout: rawOut, Stderr: rawErr, Foreign: foreign, Spawned: true}
	}
	if err != nil {
		// The child never produced an exit status: nothing was observed to run.
		return TaskRunResult{ExitCode: -1, Stdout: rawOut, Stderr: rawErr, Foreign: foreign, Spawned: false}
	}
	return TaskRunResult{ExitCode: 0, Stdout: rawOut, Stderr: rawErr, Foreign: foreign, Spawned: true}
}

func (c *Client) taskSubprocess(ctx context.Context, args []string, timeout time.Duration, limit int) TaskRunResult {
	cmdLine, err := c.BuildCommand(args)
	if err != nil {
		return TaskRunResult{ExitCode: -1, Spawned: false}
	}
	return runBoundedTask(ctx, cmdLine, c.cleanEnv(), timeout, limit)
}

// TaskCanceller is a process-local registry of in-flight local CLI processes,
// keyed by reservation receipt id. It exists for one purpose: letting a stop
// request terminate the local observation of a task this process is running.
//
// Deliberately not a permission system, not a dedup marker, and not durable:
//   - it grants nothing; the caller must reach it only after the same
//     authorization and ownership checks every other route performs;
//   - an empty registry is never evidence that a task did not run, only that
//     this process is not observing it (restart, another process, or already
//     settled);
//   - losing it degrades to "cannot terminate", never to "re-execute".
type TaskCanceller struct {
	mu       sync.Mutex
	inflight map[string]*taskHandle
}

type taskHandle struct{ cancel context.CancelFunc }

func newTaskCanceller() *TaskCanceller {
	return &TaskCanceller{inflight: map[string]*taskHandle{}}
}

// begin registers one in-flight execution and returns the context, release
// function and whether registration succeeded. An empty key disables local
// termination for that run. A duplicate nonempty key must be refused before
// spawn: letting an unaddressable second run continue would make local stop
// report success while another command under the same reservation still ran.
func (t *TaskCanceller) begin(key string) (context.Context, func(), bool) {
	if t == nil {
		return context.Background(), func() {}, false
	}
	ctx, cancel := context.WithCancel(context.Background())
	handle := &taskHandle{cancel: cancel}
	if key == "" {
		return ctx, cancel, true
	}
	t.mu.Lock()
	if t.inflight == nil {
		t.inflight = map[string]*taskHandle{}
	}
	if _, exists := t.inflight[key]; exists {
		t.mu.Unlock()
		cancel()
		return ctx, func() {}, false
	}
	t.inflight[key] = handle
	t.mu.Unlock()
	return ctx, func() {
		t.mu.Lock()
		if t.inflight[key] == handle {
			delete(t.inflight, key)
		}
		t.mu.Unlock()
		cancel()
	}, true
}

// stop terminates the local CLI process registered under key. It reports
// whether a handle existed: false means "this process is not observing that
// task", which is not the same as "the task is not running".
func (t *TaskCanceller) stop(key string) bool {
	stopped, _ := t.stopRecorded(key, nil)
	return stopped
}

// stopRecorded keeps the local handle stable while the caller durably records
// the stop request. If recording fails, no cancellation is issued. The callback
// must not call another TaskCanceller method or wait for task completion.
func (t *TaskCanceller) stopRecorded(key string, record func(bool) error) (bool, error) {
	if t == nil {
		if record != nil {
			return false, record(false)
		}
		return false, nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	handle, observing := t.inflight[key]
	if key == "" {
		observing = false
	}
	if record != nil {
		if err := record(observing); err != nil {
			return false, err
		}
	}
	if observing {
		handle.cancel()
	}
	return observing, nil
}

// StopLocalTask terminates local observation of the task reserved under
// reservationReceiptID, if this process is observing it. Callers must have
// already verified task ownership; this function re-checks nothing and
// authorizes nothing.
func (c *Client) StopLocalTask(reservationReceiptID string) bool {
	return c.canceller().stop(reservationReceiptID)
}

// StopLocalTaskRecorded binds a durable request record to this process's
// observation and cancellation decision. It never claims the remote task
// stopped. The caller must verify ownership before entering this method.
func (c *Client) StopLocalTaskRecorded(reservationReceiptID string, record func(bool) error) (bool, error) {
	return c.canceller().stopRecorded(reservationReceiptID, record)
}

// IsObservingLocalTask reports whether THIS process is currently observing an
// in-flight child for the reservation. False means "not observed here" — it
// settled, this process restarted, or another process owns it — and is never
// evidence that the remote command is not running.
func (c *Client) IsObservingLocalTask(reservationReceiptID string) bool {
	return c.canceller().observing(reservationReceiptID)
}

func (t *TaskCanceller) observing(key string) bool {
	if t == nil || key == "" {
		return false
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	_, ok := t.inflight[key]
	return ok
}

func (c *Client) canceller() *TaskCanceller {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.taskCancels == nil {
		c.taskCancels = newTaskCanceller()
	}
	return c.taskCancels
}

// taskExecArgs builds the CLI argv. The command is passed as argv elements and
// never through a shell; the "--" separator is mandatory so an argv[0] starting
// with "-" cannot be re-interpreted as a CLI option.
func taskExecArgs(req TaskExecRequest) []string {
	args := []string{"sandbox", "exec", "-n", req.Target}
	if req.Workdir != "" {
		args = append(args, "--workdir", req.Workdir)
	}
	args = append(args, "--timeout", strconv.Itoa(req.TimeoutSeconds), "--no-tty", "--")
	return append(args, req.Argv...)
}

func validTaskTarget(target string) bool {
	if target == "" || len(target) > 63 {
		return false
	}
	for i, r := range target {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case (r == '.' || r == '_' || r == '-') && i > 0:
		default:
			return false
		}
	}
	return true
}

func canonicalTaskRevision(revision string) bool {
	if revision == "" || revision[0] == '0' {
		return false
	}
	for _, r := range revision {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func validTaskDigest(digest string) bool {
	if len(digest) != 64 {
		return false
	}
	for _, r := range digest {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	return true
}

func validTaskWorkdir(dir string) bool {
	if dir == "" || len(dir) > 1024 || dir[0] != '/' {
		return false
	}
	for _, r := range dir {
		if r == 0 || r == 0x7f || r < 0x20 {
			return false
		}
	}
	for _, part := range strings.Split(dir, "/") {
		if part == ".." {
			return false
		}
	}
	return true
}

// validateTaskExecRequest mirrors the request contract field for field. An
// empty argv element is rejected here as well as in the contract: it would
// otherwise be forwarded verbatim into the sandbox argv.
func validateTaskExecRequest(req TaskExecRequest) error {
	if !validTaskTarget(req.Target) {
		return fmt.Errorf("target")
	}
	if len(req.Argv) == 0 || len(req.Argv) > 256 {
		return fmt.Errorf("argv")
	}
	for _, a := range req.Argv {
		if a == "" || len(a) > 4096 || strings.ContainsRune(a, 0) {
			return fmt.Errorf("argv")
		}
	}
	if req.Workdir != "" && !validTaskWorkdir(req.Workdir) {
		return fmt.Errorf("workdir")
	}
	if req.TimeoutSeconds < 1 || req.TimeoutSeconds > 900 {
		return fmt.Errorf("timeout_seconds")
	}
	if req.OutputLimit < 4096 || req.OutputLimit > 1048576 {
		return fmt.Errorf("output_limit_bytes")
	}
	if !canonicalTaskRevision(req.PolicyRevision) {
		return fmt.Errorf("policy_revision")
	}
	if !validTaskDigest(req.PolicyDigest) {
		return fmt.Errorf("policy_digest")
	}
	return nil
}

func taskDigest(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

func refusedTaskOutcome(reason string) TaskExecOutcome {
	return TaskExecOutcome{
		State: TaskStateRefused, TaskExecuted: TaskExecutedNo, PreflightRefused: true,
		Spawned: false, Refusal: reason, ExitCode: -1, ExitCodeAttribution: TaskExitNone,
		StdoutDigest: taskDigest(""), StderrDigest: taskDigest(""),
		StartedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}
}

// VerifyTaskPolicyLoaded checks the execution prerequisite before the server
// consumes a one-use approval. This is only a preflight: ExecTask checks again
// under the target lock immediately before spawning, because policy or backend
// state can change between the two calls.
func (c *Client) VerifyTaskPolicyLoaded(target, revision, digest string, networkTargets []string) error {
	if c.InvocationFingerprint() == "" {
		return fail(errTaskBackendUnbound)
	}
	lock := c.targetPolicyLock(target)
	lock.Lock()
	defer lock.Unlock()
	return c.verifyTaskPolicyLoadedLocked(target, revision, digest, networkTargets)
}

func (c *Client) verifyTaskPolicyLoadedLocked(target, revision, digest string, networkTargets []string) error {
	snap, err := c.ReadEffective(target)
	if err != nil || snap.Revision != revision || snap.PolicyDigest != digest ||
		(snap.LoadEpoch == "" && snap.PolicyStatus != "Effective") {
		// Once any inconsistency is observed, even a later return to the old
		// bytes cannot resurrect an earlier --wait acknowledgement.
		c.forgetLoadedPolicy(target)
		return fail(errTaskPolicyNotLoaded)
	}
	sandboxID, err := c.sandboxLoadedInstance(target, revision)
	// A pre-existing policy in OpenShell 0.0.83 is reported as Effective with
	// no Loaded timestamp. Its load proof comes from the independent sandbox
	// Ready/current_policy_version readback above, whose version advances only
	// after the sandbox reports that it loaded the policy. Keep the proof
	// distinct from a real Loaded timestamp in process-local state.
	loadProof := snap.LoadEpoch
	if snap.PolicyStatus == "Effective" {
		loadProof = "effective:" + sandboxID + ":" + revision
	}
	if err != nil || !c.confirmOrObserveLoadedPolicy(target, revision, digest, loadProof, sandboxID) {
		c.forgetLoadedPolicy(target)
		return fail(errTaskPolicyNotLoaded)
	}
	approved := make(map[string]bool, len(networkTargets))
	for _, endpoint := range networkTargets {
		approved[endpoint] = true
	}
	for _, rule := range snap.Network {
		if rule.Effect != "allow" || !approved[rule.Endpoint] {
			return fail(errTaskPolicyNotLoaded)
		}
	}
	return nil
}

// ExecTask performs the real bounded execution. It refuses unless the caller's
// authorize closure and the approved policy readback both pass immediately
// before the spawn; it never writes policy and never falls back to a local
// native execution when the required backend is unavailable.
//
// The returned error is non-nil only when nothing was spawned (a refusal) or
// when the process could not be started. A task that ran and failed returns a
// nil error with a terminal state carrying task_succeeded == false.
func (c *Client) ExecTask(req TaskExecRequest, authorize func() error) (TaskExecOutcome, error) {
	if err := validateTaskExecRequest(req); err != nil {
		return refusedTaskOutcome(errTaskInvalidShape), fail(errTaskInvalidShape)
	}
	if c.InvocationFingerprint() == "" {
		return refusedTaskOutcome(errTaskBackendUnbound), fail(errTaskBackendUnbound)
	}
	if authorize == nil {
		return refusedTaskOutcome(errTaskNotAuthorized), fail(errTaskNotAuthorized)
	}
	lock := c.targetPolicyLock(req.Target)
	lock.Lock()
	defer lock.Unlock()
	// Re-check current authority after the reservation was written and before
	// any external side effect. A revoked approval or a lost session must stop
	// the start here.
	if err := authorize(); err != nil {
		out := refusedTaskOutcome(errTaskNotAuthorized)
		out.Refusal = err.Error()
		return out, fail(errTaskNotAuthorized)
	}
	// Reading the approved revision/digest is necessary but does not prove the
	// sandbox loaded it. A successful policy set --wait on this bound endpoint,
	// followed by matching readback and a stable Loaded marker, is the separate
	// prerequisite. A restarted daemon deliberately has no such proof.
	if err := c.verifyTaskPolicyLoadedLocked(req.Target, req.PolicyRevision, req.PolicyDigest, req.NetworkTargets); err != nil {
		return refusedTaskOutcome(errTaskPolicyNotLoaded), fail(errTaskPolicyNotLoaded)
	}
	// Backend I/O can outlive the authorization checked above. Recheck after
	// that I/O, while still holding the same lock as policy writers.
	if err := authorize(); err != nil {
		out := refusedTaskOutcome(errTaskNotAuthorized)
		out.Refusal = err.Error()
		return out, fail(errTaskNotAuthorized)
	}
	runner := c.TaskRunner
	if runner == nil {
		runner = c.taskSubprocess
	}
	out := TaskExecOutcome{
		Spawned: true, ExitCodeAttribution: TaskExitNone,
		StartedAt:      time.Now().UTC().Format(time.RFC3339Nano),
		PolicyRevision: req.PolicyRevision, PolicyDigest: req.PolicyDigest,
	}
	// Register the local termination handle before spawning so a stop request
	// that arrives during the run reaches this process. The handle is released
	// unconditionally when the run settles: a settled execution is not
	// stoppable, and a stale handle must never outlive its reservation.
	runCtx, releaseRun, registered := c.canceller().begin(req.ExecutionKey)
	if !registered {
		// A concurrent run may already have reached the sandbox. This call
		// spawned nothing, but the reservation as a whole is uncertain; never
		// auto-reconcile it as not_occurred.
		out.State = TaskStateFailed
		out.TaskExecuted = TaskExecutedUnknown
		out.Spawned = false
		out.ExitCode = -1
		out.Refusal = errTaskDuplicateKey
		out.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)
		out.StdoutDigest, out.StderrDigest = taskDigest(""), taskDigest("")
		return out, fail(errTaskDuplicateKey)
	}
	res := runner(runCtx, taskExecArgs(req), time.Duration(req.TimeoutSeconds)*time.Second+taskExecGrace, req.OutputLimit)
	releaseRun()
	out.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)
	out.ExitCode = res.ExitCode
	out.BoundFired = res.BoundFired
	out.ForeignBackend = res.Foreign
	out.Spawned = res.Spawned
	out.StdoutDigest = taskDigest(res.Stdout)
	out.StderrDigest = taskDigest(res.Stderr)
	out.StdoutBytes = len(res.Stdout)
	out.StderrBytes = len(res.Stderr)
	switch {
	case res.BoundFired == TaskBoundStop:
		// A local stop terminated our observation. We know what we requested,
		// not what the sandbox is doing now: SIQ has no verified remote stop confirmation, so
		// the remote outcome stays unknown and the reservation stays unresolved
		// for reconciliation. If the child had not been spawned yet, the only
		// provable statement is that nothing was started here.
		out.State = TaskStateStopped
		out.ExecutionUncertain = true
		out.TaskExecuted = TaskExecutedUnknown
		if !res.Spawned {
			out.TaskExecuted = TaskExecutedNo
			out.PreflightRefused = true
			out.Refusal = errTaskStopBeforeSpawn
		}
	case !res.Spawned:
		// The CLI never started: our own control flow proves no execution.
		out.State = TaskStateRefused
		out.TaskExecuted = TaskExecutedNo
		out.PreflightRefused = true
		out.Refusal = errTaskSpawnFailed
		out.ExitCode = -1
		return out, fail(errTaskSpawnFailed)
	case res.BoundFired == TaskBoundTime:
		// We stopped observing; the sandbox command may still be running.
		out.State = TaskStateTimedOut
		out.TaskExecuted = TaskExecutedUnknown
		out.ExecutionUncertain = true
	case res.BoundFired == TaskBoundOutput:
		out.State = TaskStateOutputLimited
		out.TaskExecuted = TaskExecutedUnknown
		out.ExecutionUncertain = true
	case res.BoundFired == TaskBoundPipe:
		out.State = TaskStateTimedOut
		out.TaskExecuted = TaskExecutedUnknown
		out.ExecutionUncertain = true
	case res.ExitCode == 0 && !res.Foreign:
		out.State = TaskStateSucceeded
		out.TaskExecuted = TaskExecutedYes
		out.ExitCodeAttribution = TaskExitRemote
	default:
		// rc != 0 is ambiguous by construction, and a foreign backend means the
		// output cannot be attributed to this sandbox at all.
		out.State = TaskStateFailed
		out.TaskExecuted = TaskExecutedUnknown
		out.ExitCodeAttribution = TaskExitRemoteOrLocal
		out.ExecutionUncertain = res.Foreign
	}
	return out, nil
}

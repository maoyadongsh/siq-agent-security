package openshell

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"sync"
	"time"
)

const (
	errOutputLimit    = "openshell_output_limit"
	errCommandTimeout = "openshell_command_timeout"
	errCommandFailed  = "openshell_command_failed"
	errPipeTimeout    = "openshell_pipe_timeout"
)

// Both pipe copy goroutines charge the same budget before allocating. On
// overflow cancel the owned child; WaitDelay bounds inherited pipe handles.
type outputBudget struct {
	mu        sync.Mutex
	remaining int
	exceeded  bool
	cancel    context.CancelFunc
}

type budgetWriter struct {
	budget *outputBudget
	buf    bytes.Buffer
}

func (w *budgetWriter) Write(p []byte) (int, error) {
	w.budget.mu.Lock()
	defer w.budget.mu.Unlock()
	if w.budget.exceeded || len(p) > w.budget.remaining {
		w.budget.exceeded = true
		w.budget.cancel()
		return 0, errors.New(errOutputLimit)
	}
	w.budget.remaining -= len(p)
	return w.buf.Write(p)
}

func runBoundedCommand(argv, env []string, timeout time.Duration, limit int) (int, string, string) {
	if len(argv) == 0 || limit <= 0 || timeout <= 0 {
		return 1, "", errCommandFailed
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
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
	if budget.exceeded {
		return 1, "", errOutputLimit
	}
	if ctx.Err() == context.DeadlineExceeded {
		return 1, "", errCommandTimeout
	}
	if errors.Is(err, exec.ErrWaitDelay) {
		return 1, "", errPipeTimeout
	}
	if err != nil {
		// Preserve only the diagnosis, never command arguments or backend text.
		if looksLikeForeignGateway(out.buf.String() + diagnostic.buf.String()) {
			return 1, "", errNotOpenShell
		}
		return 1, "", errCommandFailed
	}
	return 0, out.buf.String(), diagnostic.buf.String()
}

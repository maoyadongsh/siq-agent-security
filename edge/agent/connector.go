package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// Connector is the Edge-side contract for a connector plugin
// (connector-protocol.v1.md). Connectors run as subprocesses started with
// `--serve` and exchange NDJSON on stdio: stdout carries only protocol
// messages, diagnostics go to stderr.
type Connector interface {
	Describe(ctx context.Context) (*protocol.ConnectorCapabilities, error)
	ValidateScope(ctx context.Context, scope *protocol.Scope) (*protocol.ValidationResult, error)
	PlanScan(ctx context.Context, scope *protocol.Scope, cursor string) (*protocol.ScanPlan, error)
	Collect(ctx context.Context, plan *protocol.ScanPlan) (*protocol.EvidenceBatch, error)
	Checkpoint(ctx context.Context) (string, error)
	Health(ctx context.Context) (*protocol.HealthReport, error)
}

// Typed errors on the Edge side; the code→error mapping mirrors contract §3.
var (
	ErrScopeInvalid     = errors.New("connector: scope_invalid")
	ErrLimitExceeded    = errors.New("connector: limit_exceeded")
	ErrRedactionFailure = errors.New("connector: redaction_failure")
	ErrTimeout          = errors.New("connector: timeout")
	ErrUnsupported      = errors.New("connector: unsupported")
	ErrOutputLimit      = errors.New("connector: output limit exceeded")
	ErrConnectorClosed  = errors.New("connector: subprocess closed")
	ErrConnectorTrust   = errors.New("connector trust unavailable; verify the confirmed setup-enterprise plan, signed release and private installation; do not delete device state; development scans require run-once --connector-bin with an absolute path")
)

// mapCodeToError translates a connector error code into the typed error.
func mapCodeToError(code string) error {
	switch code {
	case protocol.CodeScopeInvalid:
		return ErrScopeInvalid
	case protocol.CodeLimitExceeded:
		return ErrLimitExceeded
	case protocol.CodeRedactionFailure:
		return ErrRedactionFailure
	case protocol.CodeTimeout:
		return ErrTimeout
	case protocol.CodeUnsupported:
		return ErrUnsupported
	default:
		return errors.New("connector: unknown error code")
	}
}

// codeOf maps a typed error back to a receipt error_code string.
func codeOf(err error) string {
	switch {
	case errors.Is(err, ErrScopeInvalid):
		return protocol.CodeScopeInvalid
	case errors.Is(err, ErrLimitExceeded), errors.Is(err, ErrOutputLimit):
		return protocol.CodeLimitExceeded
	case errors.Is(err, ErrRedactionFailure):
		return protocol.CodeRedactionFailure
	case errors.Is(err, ErrTimeout):
		return protocol.CodeTimeout
	case errors.Is(err, ErrUnsupported), errors.Is(err, ErrConnectorTrust):
		return protocol.CodeUnsupported
	default:
		return "internal_error"
	}
}

// SubprocessConnector drives a connector binary over the NDJSON protocol.
// Security invariants:
//   - the child is spawned with an allowlisted environment (PATH, HOME and the
//     SIQ_CONNECTOR_* vars only) — the parent's secrets are never inherited;
//   - stdout is treated as protocol data only; diagnostics come from stderr
//     and are capped (maxStderr) so a misbehaving connector cannot exhaust
//     memory;
//   - per-op timeout (default 60s) kills the subprocess on expiry (contract:
//     timeout → cancel subprocess, task fails);
//   - total stdout per op is capped at maxOutput (default 8 MiB).
type SubprocessConnector struct {
	name           string
	binPath        string
	version        string
	artifactSHA256 string

	timeout   time.Duration
	maxOutput int64
	maxStderr int64

	mu       sync.Mutex
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	reader   *bufio.Reader
	stderr   *cappedBuffer
	seq      int64
	totalOut int64
	closed   bool
}

// SubprocessOptions configures a SubprocessConnector; zero values get the
// contract defaults.
type SubprocessOptions struct {
	Name           string
	Version        string
	Timeout        time.Duration // 0 → 60s
	MaxOutputBytes int64         // 0 → 8 MiB
	MaxStderrBytes int64         // 0 → 1 MiB
	artifactSHA256 string        // set only by the verified managed constructor
}

// NewVerifiedSubprocessConnector is for callers that already verified the
// release/plan binding. It pins the actual bytes again at the execution boundary.
func NewVerifiedSubprocessConnector(ctx context.Context, binPath, digest string, opts SubprocessOptions) (*SubprocessConnector, error) {
	if digest == "" || !isOfficialConnector(opts.Name) {
		return nil, ErrConnectorTrust
	}
	opts.artifactSHA256 = digest
	return NewSubprocessConnector(ctx, binPath, opts)
}

// NewSubprocessConnector spawns the connector binary in --serve mode.
func NewSubprocessConnector(ctx context.Context, binPath string, opts SubprocessOptions) (*SubprocessConnector, error) {
	if opts.Timeout <= 0 {
		opts.Timeout = time.Duration(protocol.DefaultCollectTimeoutMS) * time.Millisecond
	}
	if opts.MaxOutputBytes <= 0 {
		opts.MaxOutputBytes = protocol.DefaultOutputLimitBytes
	}
	if opts.MaxStderrBytes <= 0 {
		opts.MaxStderrBytes = 1 << 20
	}
	c := &SubprocessConnector{
		name:           opts.Name,
		binPath:        binPath,
		version:        opts.Version,
		artifactSHA256: opts.artifactSHA256,
		timeout:        opts.Timeout,
		maxOutput:      opts.MaxOutputBytes,
		maxStderr:      opts.MaxStderrBytes,
	}
	if err := c.start(ctx); err != nil {
		return nil, err
	}
	return c, nil
}

func (c *SubprocessConnector) start(ctx context.Context) error {
	cmd, pinned, err := connectorCommand(ctx, c.binPath, c.name, c.artifactSHA256)
	if err != nil {
		return err
	}
	if pinned != nil {
		defer pinned.Close()
	}
	// Allowlisted environment (contract §1): the connector must not see the
	// agent's environment, which may contain credentials.
	childPath := os.Getenv("PATH")
	if pinned != nil {
		childPath = "/usr/bin:/bin"
	}
	cmd.Env = []string{
		"PATH=" + childPath,
		"HOME=" + os.Getenv("HOME"),
		"SIQ_CONNECTOR_NAME=" + c.name,
		"SIQ_CONNECTOR_VERSION=" + c.version,
		"SIQ_CONNECTOR_TIMEOUT_MS=" + strconv.FormatInt(c.timeout.Milliseconds(), 10),
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return errors.New("connector: stdin pipe unavailable")
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		stdin.Close()
		return errors.New("connector: stdout pipe unavailable")
	}
	c.stderr = newCappedBuffer(c.maxStderr)
	cmd.Stderr = c.stderr
	if err := cmd.Start(); err != nil {
		stdin.Close()
		stdout.Close()
		if pinned != nil {
			return ErrConnectorTrust
		}
		return errors.New("connector: subprocess start failed")
	}
	c.cmd = cmd
	c.stdin = stdin
	c.reader = bufio.NewReader(stdout)
	return nil
}

// Close terminates the subprocess.
func (c *SubprocessConnector) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.killLocked()
	return nil
}

// killLocked kills and reaps the child. Caller must hold mu.
func (c *SubprocessConnector) killLocked() {
	if c.closed {
		return
	}
	c.closed = true
	if c.cmd != nil && c.cmd.Process != nil {
		_ = c.cmd.Process.Kill()
		_ = c.cmd.Wait()
	}
}

// call performs one NDJSON request/response round trip. Only one call runs at
// a time (mu). The parent independently enforces c.timeout over stdin write +
// response read (DEV10 / M-E1); env hints alone are not enough. On deadline the
// subprocess is killed and the connector is marked closed.
func (c *SubprocessConnector) call(ctx context.Context, op string, params any, into any) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed || c.cmd == nil {
		return ErrConnectorClosed
	}
	opCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	c.seq++
	req := protocol.Request{ID: fmt.Sprintf("req-%06d", c.seq), Op: op}
	if params == nil {
		req.Params = json.RawMessage("{}")
	} else {
		data, err := json.Marshal(params)
		if err != nil {
			return fmt.Errorf("connector: encode %s params: %w", op, err)
		}
		req.Params = data
	}
	line, err := json.Marshal(&req)
	if err != nil {
		return fmt.Errorf("connector: encode %s request: %w", op, err)
	}
	if int64(len(line))+1 > c.maxOutput {
		// Reuse output cap as a hard request-size bound so a huge params blob
		// cannot stall the pipe before the read deadline applies.
		return fmt.Errorf("%w: %s request exceeded %d bytes", ErrOutputLimit, op, c.maxOutput)
	}
	if err := c.writeLine(opCtx, op, append(line, '\n')); err != nil {
		return err
	}
	c.totalOut = 0 // output cap applies per op
	respLine, err := c.readLine(opCtx, op)
	if err != nil {
		return err
	}
	var resp struct {
		ID     string                  `json:"id"`
		OK     bool                    `json:"ok"`
		Result json.RawMessage         `json:"result"`
		Error  *protocol.ProtocolError `json:"error"`
	}
	if err := json.Unmarshal(respLine, &resp); err != nil {
		return fmt.Errorf("connector: invalid %s response", op)
	}
	if resp.ID != req.ID {
		return fmt.Errorf("connector: %s response id mismatch", op)
	}
	if !resp.OK {
		if resp.Error == nil {
			return fmt.Errorf("connector: %s failed without an error code", op)
		}
		return mapCodeToError(resp.Error.Code)
	}
	if into != nil && len(resp.Result) > 0 {
		if err := json.Unmarshal(resp.Result, into); err != nil {
			return fmt.Errorf("connector: invalid %s result", op)
		}
	}
	return nil
}

// writeLine writes one NDJSON request line under the per-op deadline.
func (c *SubprocessConnector) writeLine(ctx context.Context, op string, line []byte) error {
	ch := make(chan error, 1)
	go func() {
		_, err := c.stdin.Write(line)
		ch <- err
	}()
	select {
	case <-ctx.Done():
		c.killLocked()
		return fmt.Errorf("%w: %s op exceeded deadline during write", ErrTimeout, op)
	case err := <-ch:
		if err != nil {
			return fmt.Errorf("connector: write %s request failed", op)
		}
		return nil
	}
}

type lineResult struct {
	b   []byte
	err error
}

// readLine reads one NDJSON line, enforcing the per-op deadline and the output
// cap. On timeout or cap violation the subprocess is killed.
func (c *SubprocessConnector) readLine(ctx context.Context, op string) ([]byte, error) {
	ch := make(chan lineResult, 1)
	go func() {
		b, err := readBoundedConnectorLine(c.reader, c.maxOutput)
		ch <- lineResult{b: b, err: err}
	}()
	select {
	case <-ctx.Done():
		c.killLocked()
		return nil, fmt.Errorf("%w: %s op exceeded deadline", ErrTimeout, op)
	case r := <-ch:
		if errors.Is(r.err, ErrOutputLimit) {
			c.killLocked()
			return nil, ErrOutputLimit
		}
		if r.err != nil {
			if r.err == io.EOF {
				return nil, ErrConnectorClosed
			}
			return nil, fmt.Errorf("connector: read %s response failed", op)
		}
		c.totalOut += int64(len(r.b))
		if c.totalOut > c.maxOutput {
			c.killLocked()
			return nil, fmt.Errorf("%w: %s output exceeded %d bytes", ErrOutputLimit, op, c.maxOutput)
		}
		return r.b, nil
	}
}

func readBoundedConnectorLine(reader *bufio.Reader, limit int64) ([]byte, error) {
	var line []byte
	for {
		part, err := reader.ReadSlice('\n')
		if int64(len(line))+int64(len(part)) > limit {
			return nil, ErrOutputLimit
		}
		line = append(line, part...)
		if err == bufio.ErrBufferFull {
			continue
		}
		return line, err
	}
}

// Describe implements Connector.
func (c *SubprocessConnector) Describe(ctx context.Context) (*protocol.ConnectorCapabilities, error) {
	var out protocol.ConnectorCapabilities
	err := c.call(ctx, protocol.OpDescribe, nil, &out)
	return &out, err
}

// ValidateScope implements Connector.
func (c *SubprocessConnector) ValidateScope(ctx context.Context, scope *protocol.Scope) (*protocol.ValidationResult, error) {
	var out protocol.ValidationResult
	err := c.call(ctx, protocol.OpValidateScope, struct {
		Scope *protocol.Scope `json:"scope"`
	}{Scope: scope}, &out)
	return &out, err
}

// PlanScan implements Connector.
func (c *SubprocessConnector) PlanScan(ctx context.Context, scope *protocol.Scope, cursor string) (*protocol.ScanPlan, error) {
	var out protocol.ScanPlan
	err := c.call(ctx, protocol.OpPlanScan, struct {
		Scope  *protocol.Scope `json:"scope"`
		Cursor string          `json:"cursor,omitempty"`
	}{Scope: scope, Cursor: cursor}, &out)
	return &out, err
}

// Collect implements Connector. As defense in depth (contract §4), a non-empty
// scope is hardened locally before being sent to the connector.
func (c *SubprocessConnector) Collect(ctx context.Context, plan *protocol.ScanPlan) (*protocol.EvidenceBatch, error) {
	if plan != nil && plan.Scope != nil && len(plan.Scope.Roots) > 0 {
		if err := protocol.ValidateScopeSafety(plan.Scope); err != nil {
			return nil, fmt.Errorf("%w: %v", ErrScopeInvalid, err)
		}
	}
	var out protocol.EvidenceBatch
	err := c.call(ctx, protocol.OpCollect, struct {
		Plan *protocol.ScanPlan `json:"plan"`
	}{Plan: plan}, &out)
	return &out, err
}

// Checkpoint implements Connector.
func (c *SubprocessConnector) Checkpoint(ctx context.Context) (string, error) {
	var out protocol.CursorResult
	if err := c.call(ctx, protocol.OpCheckpoint, nil, &out); err != nil {
		return "", err
	}
	return out.Cursor, nil
}

// Health implements Connector.
func (c *SubprocessConnector) Health(ctx context.Context) (*protocol.HealthReport, error) {
	var out protocol.HealthReport
	err := c.call(ctx, protocol.OpHealth, nil, &out)
	return &out, err
}

// ResolveConnectorBin is the explicit development resolver. Managed scans use
// their verified installation instead; neither path silently searches PATH.
func ResolveConnectorBin(name, override string) (string, error) {
	if !isOfficialConnector(name) {
		return "", fmt.Errorf("connector %q is not allowlisted", name)
	}
	if override == "" {
		dir := os.Getenv("SIQ_CONNECTOR_BIN_DIR")
		if filepath.IsAbs(dir) && filepath.Clean(dir) == dir {
			override = filepath.Join(dir, name+"-connector")
		}
	}
	if filepath.IsAbs(override) && filepath.Clean(override) == override {
		if info, err := os.Lstat(override); err == nil && info.Mode().IsRegular() {
			return override, nil
		}
	}
	return "", errors.New("connector binary not found: specify an absolute --connector-bin or SIQ_CONNECTOR_BIN_DIR; PATH lookup is disabled")
}

func isOfficialConnector(name string) bool {
	switch name {
	case "hermes", "openclaw", "docker", "directory",
		"systemd", "kubernetes", "process", "mcp",
		"piagent", "workbuddy", "dify", "siq":
		return true
	default:
		return false
	}
}

// cappedBuffer is a stderr buffer that stops growing after max bytes, so a
// misbehaving connector cannot exhaust agent memory via stderr.
type cappedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
	max int64
}

func newCappedBuffer(max int64) *cappedBuffer {
	return &cappedBuffer{max: max}
}

func (b *cappedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if int64(b.buf.Len()) < b.max {
		room := b.max - int64(b.buf.Len())
		if int64(len(p)) > room {
			b.buf.Write(p[:room])
		} else {
			b.buf.Write(p)
		}
	}
	return len(p), nil // always claim success so the child keeps running
}

func (b *cappedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.buf.Len() == 0 {
		return ""
	}
	if int64(b.buf.Len()) >= b.max {
		return b.buf.String() + "...(truncated)"
	}
	return b.buf.String()
}

// Package notify implements the daemon-side desktop notification layer of the
// UX-008 background launcher. It is deliberately minimal:
//
//   - Notifications carry a count only. The desktop notification surface is
//     readable by other local applications, so no tool names, action ids,
//     digests or request metadata are included (same privacy rule as ADR-032
//     browser notifications). Clicking a notification can never approve.
//   - Delivery never blocks or fails a decision: the dispatcher logs delivery
//     errors and retries after the coalesce interval. Notification absence
//     must not gate the confirmation inbox, which stays fully usable.
//   - The notifier is a fixed argv executed without a shell. Empty platform
//     default means "unsupported here": the dispatcher stays silent instead
//     of pretending delivery happened.
package notify

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"sync"
	"time"
)

// Notification is the full desktop notification content. Count-only by design.
type Notification struct {
	Title string
	Body  string
}

// Notifier raises a desktop notification. Implementations must be safe for
// sequential use from the dispatcher goroutine only.
type Notifier interface {
	Notify(n Notification) error
}

// CommandNotifier runs Bin with Args plus the notification title and body.
type CommandNotifier struct {
	Bin     string
	Args    []string
	Timeout time.Duration
}

// ErrUnsupported is returned when no delivery mechanism exists for the
// current platform and none was configured.
var ErrUnsupported = fmt.Errorf("notify: no desktop notification mechanism on this platform")

var ErrDeliveryFailed = errors.New("notify: command failed")
var ErrDeliveryTimeout = errors.New("notify: command timed out")

// DefaultCommand returns the platform default notifier argv. The bool is
// false on platforms with no supported default: callers must not fabricate
// delivery there.
func DefaultCommand(goos string) ([]string, bool) {
	if goos == "linux" {
		if _, err := exec.LookPath("notify-send"); err == nil {
			return []string{"notify-send", "-a", "SIQ AgentShield", "-u", "normal"}, true
		}
		return nil, false
	}
	if goos == "darwin" {
		// osascript "display notification" delivers into Notification Center
		// from any terminal-origin process without a signed bundle. It cannot
		// provide click navigation: notifications are count-only and clicking
		// them never reaches this process. Navigation to the pending inbox
		// stays on the local console UI; this gap is documented, not hidden.
		if _, err := exec.LookPath("/usr/bin/osascript"); err == nil {
			return []string{"/usr/bin/osascript", "-e",
				`on run argv
display notification (item 2 of argv) with title (item 1 of argv)
end run`}, true
		}
		return nil, false
	}
	return nil, false
}

// Notify executes the configured command. Title and body are appended as the
// final arguments; no shell interpolation happens anywhere in this path.
func (c CommandNotifier) Notify(n Notification) error {
	if c.Bin == "" {
		return ErrUnsupported
	}
	timeout := c.Timeout
	if timeout <= 0 || timeout > 5*time.Second {
		timeout = 5 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	// Title is a fixed product constant and Body a count sentence, so neither
	// can start with "-" and no option-terminator is needed.
	argv := append(append([]string{}, c.Args...), n.Title, n.Body)
	cmd := exec.CommandContext(ctx, c.Bin, argv...)
	// Nil stdout/stderr go directly to the null device: no output buffer,
	// inherited terminal or pipe can expose notifier diagnostics to our logs.
	if err := cmd.Run(); err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return ErrDeliveryTimeout
		}
		return ErrDeliveryFailed
	}
	return nil
}

// DispatcherOptions tune the dispatcher. Zero values pick defaults matching
// the web layer cadence (M15/M16): 5s poll, 15s coalesce.
type DispatcherOptions struct {
	PollInterval     time.Duration
	CoalesceInterval time.Duration
	Title            string
	// Log receives delivery failures; nil drops them. The dispatcher never
	// propagates delivery errors to callers.
	Log func(error)
}

// Dispatcher polls the pending-confirmation count and raises a count-only
// desktop notification whenever the count increases, coalescing bursts.
type Dispatcher struct {
	pending  func() int
	notifier Notifier
	opts     DispatcherOptions

	mu         sync.Mutex
	lastCount  int
	lastNotify time.Time
	retryAfter time.Time
}

// NewDispatcher builds a dispatcher over a pending-count source.
func NewDispatcher(pending func() int, n Notifier, opts DispatcherOptions) *Dispatcher {
	if opts.PollInterval <= 0 {
		opts.PollInterval = 5 * time.Second
	}
	if opts.CoalesceInterval <= 0 {
		opts.CoalesceInterval = 15 * time.Second
	}
	if opts.Title == "" {
		opts.Title = "SIQ AgentShield"
	}
	if opts.Log == nil {
		opts.Log = func(error) {}
	}
	return &Dispatcher{pending: pending, notifier: n, opts: opts}
}

// Run polls until ctx is done. It is the only method intended for a goroutine.
func (d *Dispatcher) Run(ctx context.Context) {
	ticker := time.NewTicker(d.opts.PollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			d.Tick(time.Now())
		}
	}
}

// Tick performs one poll-and-maybe-notify step and reports whether a
// notification was raised. Exposed for deterministic tests.
func (d *Dispatcher) Tick(now time.Time) bool {
	count := d.pending()
	d.mu.Lock()
	defer d.mu.Unlock()
	if count <= d.lastCount || count <= 0 {
		d.lastCount = count
		if count <= 0 {
			// Fully drained: the coalesce window no longer hides anything, so
			// a brand-new pending item afterwards deserves a fresh reminder.
			d.lastNotify = time.Time{}
		}
		return false
	}
	if !d.lastNotify.IsZero() && now.Sub(d.lastNotify) < d.opts.CoalesceInterval {
		// Suppress, but keep lastCount at the already-reported value so the
		// unreported increase still fires once the coalesce window elapses.
		return false
	}
	if now.Before(d.retryAfter) {
		return false
	}
	body := fmt.Sprintf("有 %d 项待确认操作，请在本地控制台处理", count)
	err := d.notifier.Notify(Notification{Title: d.opts.Title, Body: body})
	if err != nil {
		d.retryAfter = now.Add(d.opts.CoalesceInterval)
		d.opts.Log(err)
		// Retain the unreported count, but back off failed attempts separately.
		return false
	}
	d.lastCount = count
	d.lastNotify = now
	d.retryAfter = time.Time{}
	return true
}

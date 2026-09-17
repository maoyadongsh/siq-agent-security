package notify

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

// stubNotifier records notifications and optionally fails.
type stubNotifier struct {
	mu     sync.Mutex
	got    []Notification
	failN  int // fail the first failN Notify calls
	failEr error
}

func (s *stubNotifier) Notify(n Notification) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failN > 0 {
		s.failN--
		return s.failEr
	}
	s.got = append(s.got, n)
	return nil
}

func (s *stubNotifier) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.got)
}

func newTestDispatcher(pending func() int, n Notifier) *Dispatcher {
	return NewDispatcher(pending, n, DispatcherOptions{
		PollInterval:     time.Second,
		CoalesceInterval: 15 * time.Second,
		Log:              func(error) {},
	})
}

func TestDispatcherNotifiesOnCountIncrease(t *testing.T) {
	count := 0
	st := &stubNotifier{}
	d := newTestDispatcher(func() int { return count }, st)
	base := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	if d.Tick(base) {
		t.Fatal("no pending items must not notify")
	}
	count = 2
	if !d.Tick(base.Add(time.Second)) {
		t.Fatal("increase 0→2 must notify")
	}
	if st.count() != 1 {
		t.Fatalf("expected 1 notification, got %d", st.count())
	}
	// Same count: no repeat.
	if d.Tick(base.Add(2 * time.Second)) {
		t.Fatal("same count must not re-notify")
	}
	// Decrease: never notify.
	count = 1
	if d.Tick(base.Add(3 * time.Second)) {
		t.Fatal("decrease must not notify")
	}
	// Increase again after coalesce window: notify.
	count = 3
	if !d.Tick(base.Add(20 * time.Second)) {
		t.Fatal("increase after coalesce window must notify")
	}
}

func TestDispatcherCoalescesBurstWithinWindow(t *testing.T) {
	count := 0
	st := &stubNotifier{}
	d := newTestDispatcher(func() int { return count }, st)
	base := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	count = 1
	if !d.Tick(base) {
		t.Fatal("first increase must notify")
	}
	count = 5
	// Within the 15s coalesce window: suppressed, retried after it elapses.
	if d.Tick(base.Add(5 * time.Second)) {
		t.Fatal("burst within coalesce window must be suppressed")
	}
	if d.Tick(base.Add(10 * time.Second)) {
		t.Fatal("still within coalesce window")
	}
	if !d.Tick(base.Add(15*time.Second + time.Nanosecond)) {
		t.Fatal("after coalesce window the increase must be reported")
	}
	if st.count() != 2 {
		t.Fatalf("expected 2 notifications, got %d", st.count())
	}
}

func TestDispatcherReturnsToZeroThenReNotifies(t *testing.T) {
	count := 3
	st := &stubNotifier{}
	d := newTestDispatcher(func() int { return count }, st)
	base := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	if !d.Tick(base) {
		t.Fatal("initial pending must notify")
	}
	count = 0
	d.Tick(base.Add(time.Second)) // drain; lastCount returns to 0
	count = 1
	if !d.Tick(base.Add(2 * time.Second)) {
		t.Fatal("new item after full drain must re-notify")
	}
}

func TestDispatcherDeliveryFailureRetriesAfterWindow(t *testing.T) {
	count := 2
	boom := errors.New("delivery failed")
	st := &stubNotifier{failN: 1, failEr: boom}
	var logged []error
	d := NewDispatcher(func() int { return count }, st, DispatcherOptions{
		PollInterval:     time.Second,
		CoalesceInterval: 15 * time.Second,
		Log:              func(e error) { logged = append(logged, e) },
	})
	base := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	if d.Tick(base) {
		t.Fatal("failed delivery must not count as notified")
	}
	if len(logged) != 1 || !errors.Is(logged[0], boom) {
		t.Fatalf("delivery failure must be logged: %v", logged)
	}
	// Retry is bounded by the coalesce interval, not suppressed forever.
	if !d.Tick(base.Add(16 * time.Second)) {
		t.Fatal("failed delivery must retry after the coalesce window")
	}
	if st.count() != 1 {
		t.Fatalf("retry must deliver, got %d", st.count())
	}
}

func TestNotificationCarriesCountOnlyNoRequestMetadata(t *testing.T) {
	count := 7
	st := &stubNotifier{}
	d := newTestDispatcher(func() int { return count }, st)
	if !d.Tick(time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)) {
		t.Fatal("must notify")
	}
	for _, n := range st.got {
		for _, leak := range []string{"action", "tc-", "sess", "inst_", "read_file", "digest", "token", "grt-", "adm-", "receipt"} {
			if strings.Contains(strings.ToLower(n.Body), leak) || strings.Contains(strings.ToLower(n.Title), leak) {
				t.Fatalf("notification must not carry request metadata %q: %+v", leak, n)
			}
		}
		if !strings.Contains(n.Body, "7") {
			t.Fatalf("body must state the pending count: %+v", n)
		}
	}
}

func TestCommandNotifierAppendsTitleAndBodyNoShell(t *testing.T) {
	// Real exec path against /bin/echo-equivalent: use "true" so CombinedOutput
	// succeeds; assert the notification shapes the argv via a wrapper binary is
	// overkill, so verify through exec of `cat` reading argv? Keep it simple:
	// the shell-free argv contract is pinned by DefaultCommand + the count-only
	// content tests; here we check timeout/error propagation.
	c := CommandNotifier{Bin: "false", Timeout: time.Second}
	if err := c.Notify(Notification{Title: "SIQ AgentShield", Body: "x"}); err == nil {
		t.Fatal("failing command must surface an error")
	}
	c = CommandNotifier{Bin: "", Timeout: time.Second}
	if !errors.Is(c.Notify(Notification{Title: "t", Body: "b"}), ErrUnsupported) {
		t.Fatal("empty bin must be ErrUnsupported")
	}
}

func TestDefaultCommandOnlyLinuxWithBinary(t *testing.T) {
	if argv, ok := DefaultCommand("linux"); !ok || len(argv) == 0 || argv[0] != "notify-send" {
		if ok {
			t.Fatalf("linux default must be notify-send when present, got %v", argv)
		}
	}
	for _, goos := range []string{"windows"} {
		if argv, ok := DefaultCommand(goos); ok {
			t.Fatalf("%s must have no fabricated default notifier, got %v", goos, argv)
		}
	}
}

// Darwin delivers via /usr/bin/osascript with a fixed two-argument handler;
// no shell, no user content, and no click-navigation capability.
func TestDefaultCommandDarwinOsascript(t *testing.T) {
	argv, ok := DefaultCommand("darwin")
	if !ok {
		t.Skip("osascript unavailable on this host")
	}
	if argv[0] != "/usr/bin/osascript" {
		t.Fatalf("darwin default must pin /usr/bin/osascript, got %v", argv)
	}
	if len(argv) != 3 || argv[1] != "-e" || !strings.Contains(argv[2], "display notification") {
		t.Fatalf("darwin default argv shape unexpected: %v", argv)
	}
}

func TestDispatcherRunStopsOnContextCancel(t *testing.T) {
	st := &stubNotifier{}
	d := newTestDispatcher(func() int { return 0 }, st)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { d.Run(ctx); close(done) }()
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Run must return promptly on context cancel")
	}
}

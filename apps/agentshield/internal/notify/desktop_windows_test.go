package notify

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
	"unsafe"
)

func windowsTestNotice() Notification {
	return Notification{Title: "SIQ AgentShield", Body: "有 2 项待确认操作，请在本地控制台处理"}
}

func TestWindowsNotificationNativeABI(t *testing.T) {
	var icon windowsNotifyIconData
	var class windowsWindowClass
	var message windowsMessage
	if unsafe.Sizeof(uintptr(0)) == 8 {
		if unsafe.Sizeof(icon) != 976 || unsafe.Offsetof(icon.Window) != 8 || unsafe.Offsetof(icon.Icon) != 32 || unsafe.Offsetof(icon.Info) != 304 || unsafe.Offsetof(icon.Version) != 816 || unsafe.Offsetof(icon.GUID) != 952 || unsafe.Offsetof(icon.BalloonIcon) != 968 {
			t.Fatal("NOTIFYICONDATAW does not match the 64-bit Windows ABI")
		}
		if unsafe.Sizeof(class) != 80 || unsafe.Offsetof(class.Instance) != 24 || unsafe.Offsetof(class.ClassName) != 64 || unsafe.Sizeof(message) != 48 || unsafe.Offsetof(message.WParam) != 16 || unsafe.Offsetof(message.Private) != 44 {
			t.Fatal("WNDCLASSEXW/MSG do not match the 64-bit Windows ABI")
		}
	} else {
		if unsafe.Sizeof(icon) != 956 || unsafe.Offsetof(icon.Window) != 4 || unsafe.Offsetof(icon.Icon) != 20 || unsafe.Offsetof(icon.Info) != 288 || unsafe.Offsetof(icon.Version) != 800 || unsafe.Offsetof(icon.GUID) != 936 || unsafe.Offsetof(icon.BalloonIcon) != 952 {
			t.Fatal("NOTIFYICONDATAW does not match the 32-bit Windows ABI")
		}
		if unsafe.Sizeof(class) != 48 || unsafe.Offsetof(class.Instance) != 20 || unsafe.Offsetof(class.ClassName) != 40 || unsafe.Sizeof(message) != 32 || unsafe.Offsetof(message.WParam) != 8 || unsafe.Offsetof(message.Private) != 28 {
			t.Fatal("WNDCLASSEXW/MSG do not match the 32-bit Windows ABI")
		}
	}
}

func TestWindowsNotificationFixedNavigationAndCountPrivacy(t *testing.T) {
	for _, target := range []string{"http://127.0.0.1:1/confirmations", "http://127.0.0.1:65535/confirmations"} {
		if !windowsInboxURLValid(target) {
			t.Fatal("canonical fixed inbox rejected")
		}
	}
	for _, target := range []string{
		"https://127.0.0.1:5555/confirmations", "http://localhost:5555/confirmations",
		"http://127.0.0.1:0/confirmations", "http://127.0.0.1:65536/confirmations",
		"http://127.0.0.1:05555/confirmations", "http://127.0.0.1/confirmations",
		"http://user@127.0.0.1:5555/confirmations", "http://127.0.0.1:5555/confirmations?token=secret",
		"http://127.0.0.1:5555/confirmations?", "http://127.0.0.1:5555/confirmations#approve",
		"http://127.0.0.1:5555/%63onfirmations", "http://127.0.0.1:5555/grants",
		"http://127.0.0.1:5555/confirmations/", "file:///C:/private.txt", "cmd.exe /c anything",
	} {
		if windowsInboxURLValid(target) {
			t.Fatal("noncanonical or non-inbox navigation accepted")
		}
	}
	data, valid := windowsBalloonData(42, windowsTestNotice())
	if !valid || data.Window != 42 || data.ID != winIconID || data.Flags != winNIFInfo|winNIFRealtime || data.InfoFlags != winNIIFInfo|winNIIFNoSound|winNIIFRespectQuietTime || syscall.UTF16ToString(data.Info[:]) != windowsTestNotice().Body || syscall.UTF16ToString(data.InfoTitle[:]) != "SIQ AgentShield" {
		t.Fatal("count-only balloon flags or content changed")
	}
	for _, notice := range []Notification{
		{Title: "tool: secret", Body: windowsTestNotice().Body},
		{Title: "SIQ AgentShield", Body: windowsTestNotice().Body + " C:\\private"},
		{Title: "SIQ AgentShield", Body: "有 0 项待确认操作，请在本地控制台处理"},
	} {
		if _, valid := windowsBalloonData(42, notice); valid {
			t.Fatal("metadata or invalid count reached native data")
		}
	}
	if windowsSetText(make([]uint16, 1), "xy") || windowsSetText(make([]uint16, 20), "x\x00y") {
		t.Fatal("truncated or embedded-NUL native text accepted")
	}
}

func TestWindowsNotificationCallbackFiltersIconAndEvent(t *testing.T) {
	for _, event := range []uintptr{winNINSelect, winNINKeySelect, winNINBalloonUserClick} {
		if !windowsNoticeClick(winIconID<<16|event) || windowsNoticeClick(2<<16|event) || windowsNoticeClick(event) {
			t.Fatal("version-4 callback icon/event validation failed")
		}
	}
	for _, event := range []uintptr{0, 0x200, 0x202, 0x203, 0x402, 0x403, 0x404, 0xffff} {
		if windowsNoticeClick(winIconID<<16 | event) {
			t.Fatal("non-selection event opened the inbox")
		}
	}
}

type fakeWindowsNoticeHost struct {
	mu          sync.Mutex
	onEvent     func(windowsNoticeEvent)
	events      chan windowsNoticeEvent
	operations  chan string
	openBlock   <-chan struct{}
	notifyBlock <-chan struct{}
	openError   error
	notifyError error
	closed      int
	icons       int
	iconErrors  map[int]error
	iconTimes   []time.Time
	balloons    int
	urls        []string
}

func newFakeWindowsNoticeHost() *fakeWindowsNoticeHost {
	return &fakeWindowsNoticeHost{events: make(chan windowsNoticeEvent, 16), operations: make(chan string, 64)}
}
func (f *fakeWindowsNoticeHost) Open(callback func(windowsNoticeEvent)) error {
	f.mu.Lock()
	f.onEvent = callback
	f.mu.Unlock()
	f.operations <- "open"
	if f.openBlock != nil {
		<-f.openBlock
	}
	return f.openError
}
func (f *fakeWindowsNoticeHost) Pump() error {
	for {
		select {
		case event := <-f.events:
			f.onEvent(event)
		default:
			return nil
		}
	}
}
func (f *fakeWindowsNoticeHost) AddIcon() error {
	f.mu.Lock()
	f.icons++
	f.iconTimes = append(f.iconTimes, time.Now())
	err := f.iconErrors[f.icons]
	f.mu.Unlock()
	f.operations <- "icon"
	return err
}
func (f *fakeWindowsNoticeHost) Notify(Notification) error {
	f.mu.Lock()
	f.balloons++
	f.mu.Unlock()
	f.operations <- "notify"
	if f.notifyBlock != nil {
		<-f.notifyBlock
	}
	return f.notifyError
}
func (f *fakeWindowsNoticeHost) OpenInbox(url string) error {
	f.mu.Lock()
	f.urls = append(f.urls, url)
	f.mu.Unlock()
	f.operations <- "inbox"
	return nil
}
func (f *fakeWindowsNoticeHost) Close() error {
	f.mu.Lock()
	f.closed++
	f.mu.Unlock()
	f.operations <- "close"
	return nil
}
func windowsAwaitOperation(t *testing.T, host *fakeWindowsNoticeHost, want string) {
	t.Helper()
	timer := time.NewTimer(time.Second)
	defer timer.Stop()
	for {
		select {
		case got := <-host.operations:
			if got == want {
				return
			}
		case <-timer.C:
			t.Fatalf("missing fake host operation %s", want)
		}
	}
}

func TestWindowsNotificationLazyClosedAndInvalidInputs(t *testing.T) {
	var constructed atomic.Int32
	factory := func() windowsNoticeHost { constructed.Add(1); return newFakeWindowsNoticeHost() }
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", factory, time.Second)
	if constructed.Load() != 0 || n.Close() != nil || n.Close() != nil || n.Notify(windowsTestNotice()) == nil || constructed.Load() != 0 {
		t.Fatal("constructing/closing an unused notifier created a GUI host")
	}
	for _, target := range []string{"file:///C:/private.txt", "http://127.0.0.1:5555/confirmations?approve=1"} {
		bad := newWindowsNotifier(target, factory, time.Second)
		if bad.Notify(windowsTestNotice()) == nil || bad.Close() != nil || constructed.Load() != 0 {
			t.Fatal("invalid navigation created a GUI host")
		}
	}
	bad := newWindowsNotifier("http://127.0.0.1:5555/confirmations", factory, time.Second)
	if bad.Notify(Notification{Title: "secret", Body: "secret"}) == nil || bad.Close() != nil || constructed.Load() != 0 {
		t.Fatal("invalid content created a GUI host")
	}
	if n := newWindowsNotifier("", factory, 20*time.Second); n.timeout != windowsNotifyLimit {
		t.Fatal("native timeout can exceed five seconds")
	}
}

func TestWindowsNotificationExplorerRecoveryDoesNotReplay(t *testing.T) {
	host := newFakeWindowsNoticeHost()
	inbox := "http://127.0.0.1:5555/confirmations"
	n := newWindowsNotifier(inbox, func() windowsNoticeHost { return host }, time.Second)
	t.Cleanup(func() { _ = n.Close() })
	if err := n.Notify(windowsTestNotice()); err != nil {
		t.Fatal(err)
	}
	windowsAwaitOperation(t, host, "notify")
	host.events <- windowsTaskbarCreated
	windowsAwaitOperation(t, host, "icon")
	host.events <- windowsNoticeSelected
	windowsAwaitOperation(t, host, "inbox")
	if err := n.Close(); err != nil {
		t.Fatal(err)
	}
	// Even a callback delivered after shutdown cannot navigate or restore.
	host.onEvent(windowsNoticeSelected)
	host.onEvent(windowsTaskbarCreated)
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.closed != 1 || host.icons != 2 || host.balloons != 1 || len(host.urls) != 1 || host.urls[0] != inbox {
		t.Fatal("Explorer recovery replayed content or cleanup/click escaped its lifecycle")
	}
}

func TestWindowsNotificationExpiredQueuedRequestIsDiscarded(t *testing.T) {
	host := newFakeWindowsNoticeHost()
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost { return host }, time.Second)
	t.Cleanup(func() { _ = n.Close() })
	if err := n.Notify(windowsTestNotice()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result := make(chan error, 1)
	n.requests <- windowsNoticeRequest{ctx: ctx, notice: windowsTestNotice(), result: result}
	select {
	case err := <-result:
		if !errors.Is(err, ErrDeliveryTimeout) {
			t.Fatal("expired request was accepted")
		}
	case <-time.After(time.Second):
		t.Fatal("expired request was not drained")
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.balloons != 1 {
		t.Fatal("expired request was delivered")
	}
}

func TestWindowsNotificationExplorerRecoveryRetriesWithoutBalloon(t *testing.T) {
	host := newFakeWindowsNoticeHost()
	host.iconErrors = map[int]error{2: ErrDeliveryFailed}
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost { return host }, time.Second)
	if n.restoreRetry != 15*time.Second {
		t.Fatal("production Explorer retry interval changed")
	}
	n.restoreRetry = 100 * time.Millisecond
	t.Cleanup(func() { _ = n.Close() })
	if err := n.Notify(windowsTestNotice()); err != nil {
		t.Fatal(err)
	}
	windowsAwaitOperation(t, host, "notify")
	host.events <- windowsTaskbarCreated
	windowsAwaitOperation(t, host, "icon") // First restore fails.
	// A duplicate broadcast and a new delivery request cannot bypass the
	// restore backoff. No pending-count change is needed for the retry.
	host.events <- windowsTaskbarCreated
	if err := n.Notify(windowsTestNotice()); !errors.Is(err, ErrDeliveryFailed) {
		t.Fatal("delivery bypassed Explorer recovery backoff")
	}
	windowsAwaitOperation(t, host, "icon") // Timed retry succeeds.
	host.events <- windowsNoticeSelected
	windowsAwaitOperation(t, host, "inbox")
	if err := n.Close(); err != nil {
		t.Fatal(err)
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.icons != 3 || host.balloons != 1 || len(host.urls) != 1 || host.closed != 1 {
		t.Fatal("recovery failed, replayed a balloon, or continued after success")
	}
	if host.iconTimes[2].Sub(host.iconTimes[1]) < n.restoreRetry {
		t.Fatal("failed restoration retried before its backoff expired")
	}
}

func TestWindowsNotificationCloseStopsPendingExplorerRecovery(t *testing.T) {
	host := newFakeWindowsNoticeHost()
	host.iconErrors = map[int]error{2: ErrDeliveryFailed, 3: ErrDeliveryFailed}
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost { return host }, time.Second)
	n.restoreRetry = 100 * time.Millisecond
	t.Cleanup(func() { _ = n.Close() })
	if err := n.Notify(windowsTestNotice()); err != nil {
		t.Fatal(err)
	}
	windowsAwaitOperation(t, host, "notify")
	host.events <- windowsTaskbarCreated
	windowsAwaitOperation(t, host, "icon")
	if err := n.Close(); err != nil {
		t.Fatal(err)
	}
	windowsAwaitOperation(t, host, "close")
	host.events <- windowsTaskbarCreated
	select {
	case operation := <-host.operations:
		t.Fatalf("closed notifier performed %s while restore was pending", operation)
	case <-time.After(2 * n.restoreRetry):
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.icons != 2 || host.balloons != 1 || host.closed != 1 {
		t.Fatal("shutdown retried restoration or replayed content")
	}
}

func TestWindowsNotificationTimeoutThenCloseCleansWhenOpenReturns(t *testing.T) {
	gate := make(chan struct{})
	var release sync.Once
	defer release.Do(func() { close(gate) })
	host := newFakeWindowsNoticeHost()
	host.openBlock = gate
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost { return host }, 40*time.Millisecond)
	start := time.Now()
	if err := n.Notify(windowsTestNotice()); !errors.Is(err, ErrDeliveryTimeout) {
		t.Fatal("blocked initialization did not time out")
	}
	if time.Since(start) > time.Second {
		t.Fatal("Notify exceeded its caller budget")
	}
	if err := n.Close(); !errors.Is(err, ErrDeliveryTimeout) {
		t.Fatal("blocked cleanup did not return a bounded timeout")
	}
	if err := n.Notify(windowsTestNotice()); err == nil {
		t.Fatal("closed notifier accepted a new request")
	}
	release.Do(func() { close(gate) })
	select {
	case <-n.done:
	case <-time.After(time.Second):
		t.Fatal("worker did not clean up after initialization returned")
	}
	if err := n.Close(); err != nil {
		t.Fatal(err)
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.closed != 1 || host.icons != 0 || host.balloons != 0 || len(host.urls) != 0 {
		t.Fatal("expired initialization later delivered or leaked its host")
	}
}

func TestWindowsNotificationInFlightTimeoutDoesNotStartAnotherWorker(t *testing.T) {
	gate := make(chan struct{})
	var release sync.Once
	defer release.Do(func() { close(gate) })
	host := newFakeWindowsNoticeHost()
	host.notifyBlock = gate
	var constructed atomic.Int32
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost { constructed.Add(1); return host }, 40*time.Millisecond)
	if err := n.Notify(windowsTestNotice()); !errors.Is(err, ErrDeliveryTimeout) {
		t.Fatal("blocked shell did not time out")
	}
	if err := n.Notify(windowsTestNotice()); !errors.Is(err, ErrDeliveryTimeout) {
		t.Fatal("queued request did not share its own total deadline")
	}
	if err := n.Close(); !errors.Is(err, ErrDeliveryTimeout) {
		t.Fatal("blocked shell Close was not bounded")
	}
	release.Do(func() { close(gate) })
	select {
	case <-n.done:
	case <-time.After(time.Second):
		t.Fatal("worker failed to clean up")
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if constructed.Load() != 1 || host.closed != 1 || host.balloons != 1 {
		t.Fatal("timeout spawned another worker or replayed a queued notification")
	}
}

func TestWindowsNotificationUnavailableDesktopCanRetry(t *testing.T) {
	first, second := newFakeWindowsNoticeHost(), newFakeWindowsNoticeHost()
	first.openError = ErrUnsupported
	var constructed atomic.Int32
	n := newWindowsNotifier("http://127.0.0.1:5555/confirmations", func() windowsNoticeHost {
		if constructed.Add(1) == 1 {
			return first
		}
		return second
	}, time.Second)
	t.Cleanup(func() { _ = n.Close() })
	if err := n.Notify(windowsTestNotice()); !errors.Is(err, ErrUnsupported) {
		t.Fatal("unavailable desktop was reported as delivery")
	}
	if err := n.Notify(windowsTestNotice()); err != nil {
		t.Fatal("a later request could not recover desktop availability")
	}
	if err := n.Close(); err != nil {
		t.Fatal(err)
	}
	if first.closed != 1 || first.balloons != 0 || second.closed != 1 || second.balloons != 1 {
		t.Fatal("failed initialization leaked or was counted as visible delivery")
	}
}

package notify

import (
	"context"
	"fmt"
	"net/url"
	"runtime"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unsafe"
)

const windowsNotifyLimit = 5 * time.Second

type windowsNoticeEvent uint8

const (
	windowsNoticeSelected windowsNoticeEvent = iota + 1
	windowsTaskbarCreated
	windowsNoticeClosed
)

// All host methods run on one locked OS thread. The interface also lets the
// lifecycle tests exercise failure/timeout races without creating a desktop UI.
type windowsNoticeHost interface {
	Open(func(windowsNoticeEvent)) error
	Pump() error
	AddIcon() error
	Notify(Notification) error
	OpenInbox(string) error
	Close() error
}

type windowsNoticeRequest struct {
	ctx    context.Context
	notice Notification
	result chan error
}

type windowsNotifier struct {
	inbox        string
	factory      func() windowsNoticeHost
	timeout      time.Duration
	restoreRetry time.Duration // Internal injection only; production uses 15 seconds.
	mu           sync.Mutex
	started      bool
	closed       bool
	closeErr     error
	stop         chan struct{}
	done         chan struct{}
	requests     chan windowsNoticeRequest
}

func newNativeNotifier(inboxURL string) Notifier {
	return newWindowsNotifier(inboxURL, func() windowsNoticeHost { return &win32NoticeHost{} }, windowsNotifyLimit)
}

func newWindowsNotifier(inbox string, factory func() windowsNoticeHost, timeout time.Duration) *windowsNotifier {
	if timeout <= 0 || timeout > windowsNotifyLimit {
		timeout = windowsNotifyLimit
	}
	return &windowsNotifier{inbox: inbox, factory: factory, timeout: timeout, restoreRetry: 15 * time.Second,
		stop: make(chan struct{}), done: make(chan struct{}), requests: make(chan windowsNoticeRequest, 1)}
}

// Defense in depth: even an internal caller cannot pass a command, alternative
// host, credentials, query, fragment, encoded path, or noncanonical port here.
func windowsInboxURLValid(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "http" || u.User != nil || u.Hostname() != "127.0.0.1" || u.Path != "/confirmations" || u.RawPath != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.Opaque != "" {
		return false
	}
	port, err := strconv.Atoi(u.Port())
	return err == nil && port >= 1 && port <= 65535 && raw == "http://127.0.0.1:"+strconv.Itoa(port)+"/confirmations"
}

func (n *windowsNotifier) Notify(notice Notification) error {
	if !windowsInboxURLValid(n.inbox) || !validCountOnlyNotification(notice) {
		return ErrDeliveryFailed
	}
	ctx, cancel := context.WithTimeout(context.Background(), n.timeout)
	defer cancel()
	n.mu.Lock()
	if n.closed {
		n.mu.Unlock()
		return ErrDeliveryFailed
	}
	if !n.started {
		n.started = true
		go n.run()
	}
	n.mu.Unlock()
	req := windowsNoticeRequest{ctx: ctx, notice: notice, result: make(chan error, 1)}
	select {
	case n.requests <- req:
	case <-n.stop:
		return ErrDeliveryFailed
	case <-ctx.Done():
		return ErrDeliveryTimeout
	}
	select {
	case err := <-req.result:
		return err
	case <-n.stop:
		return ErrDeliveryFailed
	case <-ctx.Done():
		return ErrDeliveryTimeout
	}
}

func (n *windowsNotifier) stopped() bool {
	select {
	case <-n.stop:
		return true
	default:
		return false
	}
}

func (n *windowsNotifier) requestClose() {
	n.mu.Lock()
	defer n.mu.Unlock()
	if !n.closed {
		n.closed = true
		close(n.stop)
		if !n.started {
			close(n.done)
		}
	}
}

// A stuck shell call is not forcibly interrupted. Close bounds its own wait;
// the sole worker still owns cleanup when that call returns. No replacement
// worker is started and no new notification or click is accepted meanwhile.
func (n *windowsNotifier) Close() error {
	n.requestClose()
	timer := time.NewTimer(n.timeout)
	defer timer.Stop()
	select {
	case <-n.done:
		n.mu.Lock()
		defer n.mu.Unlock()
		return n.closeErr
	case <-timer.C:
		return ErrDeliveryTimeout
	}
}

func (n *windowsNotifier) run() {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	var host windowsNoticeHost
	var iconReady, restoreIcon, openInbox bool
	var restoreAfter time.Time
	restoreRetry := n.restoreRetry
	if restoreRetry <= 0 {
		restoreRetry = 15 * time.Second
	}
	defer func() {
		var err error
		if host != nil {
			err = host.Close()
		}
		n.mu.Lock()
		n.closeErr = err
		close(n.done)
		n.mu.Unlock()
	}()
	// PeekMessage avoids an uninterruptible GetMessage when shutdown races
	// window creation. A bounded batch prevents posted-message floods from
	// starving Close or requests. The worker never sends Go pointers to Win32.
	tick := time.NewTicker(25 * time.Millisecond)
	defer tick.Stop()
	onEvent := func(event windowsNoticeEvent) {
		if n.stopped() {
			return
		}
		switch event {
		case windowsTaskbarCreated:
			// Repeated Explorer messages must not defeat a failed restore's
			// backoff. A fresh restart gets one immediate recovery attempt.
			if !restoreIcon {
				restoreAfter = time.Time{}
			}
			iconReady, restoreIcon = false, true
		case windowsNoticeSelected:
			openInbox = true
		case windowsNoticeClosed:
			n.requestClose()
		}
	}
	for {
		if n.stopped() {
			return
		}
		select {
		case <-n.stop:
			return
		case req := <-n.requests:
			if req.ctx.Err() != nil || n.stopped() {
				req.result <- ErrDeliveryTimeout
				continue
			}
			if host == nil {
				host = n.factory()
				if err := host.Open(onEvent); err != nil {
					_ = host.Close()
					host = nil
					req.result <- err
					continue
				}
			}
			if req.ctx.Err() != nil || n.stopped() {
				req.result <- ErrDeliveryTimeout
				continue
			}
			if !iconReady {
				if restoreIcon && time.Now().Before(restoreAfter) {
					req.result <- ErrDeliveryFailed
					continue
				}
				if err := host.AddIcon(); err != nil {
					if restoreIcon {
						restoreAfter = time.Now().Add(restoreRetry)
					}
					req.result <- err
					continue
				}
				iconReady, restoreIcon = true, false
				restoreAfter = time.Time{}
			}
			if req.ctx.Err() != nil || n.stopped() {
				req.result <- ErrDeliveryTimeout
				continue
			}
			// The caller's deadline also covers initialization and the shell
			// call. Win32 has no cancellation API for an in-flight NotifyIcon;
			// a timeout is never reported as visible delivery.
			err := host.Notify(req.notice)
			if req.ctx.Err() != nil {
				err = ErrDeliveryTimeout
			}
			req.result <- err
		case <-tick.C:
			if host == nil {
				continue
			}
			if err := host.Pump(); err != nil {
				_ = host.Close()
				host = nil
				iconReady, restoreIcon, openInbox = false, false, false
				restoreAfter = time.Time{}
				continue
			}
			if n.stopped() {
				return
			}
			if restoreIcon && !time.Now().Before(restoreAfter) {
				iconReady = host.AddIcon() == nil
				if iconReady {
					restoreIcon = false
					restoreAfter = time.Time{}
				} else {
					restoreAfter = time.Now().Add(restoreRetry)
				}
				// Explorer restart restores presence only: no old count is
				// retained here or replayed as a balloon.
			}
			if openInbox && !n.stopped() {
				openInbox = false
				_ = host.OpenInbox(n.inbox)
			}
		}
	}
}

const (
	winWMClose              = 0x0010
	winWMEndSession         = 0x0016
	winWMQuit               = 0x0012
	winNoticeCallback       = 0x8001
	winIconID               = 1
	winNIMAdd               = 0
	winNIMModify            = 1
	winNIMDelete            = 2
	winNIMSetVersion        = 4
	winNIFMessage           = 0x1
	winNIFIcon              = 0x2
	winNIFTip               = 0x4
	winNIFInfo              = 0x10
	winNIFRealtime          = 0x40
	winNIFShowTip           = 0x80
	winNIIFInfo             = 0x1
	winNIIFNoSound          = 0x10
	winNIIFRespectQuietTime = 0x80
	winNINSelect            = 0x400
	winNINKeySelect         = 0x401
	winNINBalloonUserClick  = 0x405
)

// These definitions follow the native Windows ABI, including pointer-size
// alignment and NOTIFYICONDATAW's uTimeout/uVersion union as one uint32.
type windowsNotifyIconData struct {
	Size            uint32
	Window          uintptr
	ID              uint32
	Flags           uint32
	CallbackMessage uint32
	Icon            uintptr
	Tip             [128]uint16
	State           uint32
	StateMask       uint32
	Info            [256]uint16
	Version         uint32
	InfoTitle       [64]uint16
	InfoFlags       uint32
	GUID            [16]byte
	BalloonIcon     uintptr
}

type windowsWindowClass struct {
	Size        uint32
	Style       uint32
	WindowProc  uintptr
	ClassExtra  int32
	WindowExtra int32
	Instance    uintptr
	Icon        uintptr
	Cursor      uintptr
	Background  uintptr
	MenuName    *uint16
	ClassName   *uint16
	SmallIcon   uintptr
}

type windowsMessage struct {
	Window  uintptr
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	X       int32
	Y       int32
	Private uint32
}

var (
	noticeUser32                   = syscall.NewLazyDLL("user32.dll")
	noticeShell32                  = syscall.NewLazyDLL("shell32.dll")
	noticeKernel32                 = syscall.NewLazyDLL("kernel32.dll")
	noticeOle32                    = syscall.NewLazyDLL("ole32.dll")
	noticeRegisterClass            = noticeUser32.NewProc("RegisterClassExW")
	noticeUnregisterClass          = noticeUser32.NewProc("UnregisterClassW")
	noticeCreateWindow             = noticeUser32.NewProc("CreateWindowExW")
	noticeDestroyWindow            = noticeUser32.NewProc("DestroyWindow")
	noticeDefWindowProc            = noticeUser32.NewProc("DefWindowProcW")
	noticePeekMessage              = noticeUser32.NewProc("PeekMessageW")
	noticeTranslateMessage         = noticeUser32.NewProc("TranslateMessage")
	noticeDispatchMessage          = noticeUser32.NewProc("DispatchMessageW")
	noticeRegisterMessage          = noticeUser32.NewProc("RegisterWindowMessageW")
	noticeLoadIcon                 = noticeUser32.NewProc("LoadIconW")
	noticeGetShellWindow           = noticeUser32.NewProc("GetShellWindow")
	noticeOpenInputDesktop         = noticeUser32.NewProc("OpenInputDesktop")
	noticeCloseDesktop             = noticeUser32.NewProc("CloseDesktop")
	noticeGetThreadDesktop         = noticeUser32.NewProc("GetThreadDesktop")
	noticeGetUserObjectInformation = noticeUser32.NewProc("GetUserObjectInformationW")
	noticeGetWindowStation         = noticeUser32.NewProc("GetProcessWindowStation")
	noticeGetModule                = noticeKernel32.NewProc("GetModuleHandleW")
	noticeGetThreadID              = noticeKernel32.NewProc("GetCurrentThreadId")
	noticeNotifyIcon               = noticeShell32.NewProc("Shell_NotifyIconW")
	noticeShellExecute             = noticeShell32.NewProc("ShellExecuteW")
	noticeCoInitialize             = noticeOle32.NewProc("CoInitializeEx")
	noticeCoUninitialize           = noticeOle32.NewProc("CoUninitialize")
	noticeCallbackOnce             sync.Once
	noticeCallbackPointer          uintptr
	noticeClassSequence            atomic.Uint64
	noticeWindows                  sync.Map // HWND -> *win32NoticeHost; removed before DestroyWindow.
)

type win32NoticeHost struct {
	window          uintptr
	module          uintptr
	className       *uint16
	classRegistered bool
	comInitialized  bool
	icon            uintptr // Shared LoadIcon result: never DestroyIcon.
	iconAdded       bool
	taskbarMessage  uint32
	onEvent         func(windowsNoticeEvent)
}

func windowsNoticeProc(window, message, wParam, lParam uintptr) uintptr {
	if value, ok := noticeWindows.Load(window); ok {
		h := value.(*win32NoticeHost)
		switch uint32(message) {
		case h.taskbarMessage:
			h.iconAdded = false
			h.onEvent(windowsTaskbarCreated)
			return 0
		case winNoticeCallback:
			if windowsNoticeClick(lParam) {
				h.onEvent(windowsNoticeSelected)
			}
			return 0
		case winWMClose:
			h.onEvent(windowsNoticeClosed)
			return 0
		case winWMEndSession:
			if wParam != 0 {
				h.onEvent(windowsNoticeClosed)
			}
			return 0
		}
	}
	result, _, _ := noticeDefWindowProc.Call(window, message, wParam, lParam)
	return result
}

func windowsNoticeClick(lParam uintptr) bool {
	if uint16(lParam>>16) != winIconID {
		return false
	}
	switch uint16(lParam) {
	case winNINSelect, winNINKeySelect, winNINBalloonUserClick:
		return true
	}
	return false
}

func (h *win32NoticeHost) Open(onEvent func(windowsNoticeEvent)) error {
	for _, proc := range []*syscall.LazyProc{noticeRegisterClass, noticeUnregisterClass, noticeCreateWindow, noticeDestroyWindow, noticeDefWindowProc, noticePeekMessage, noticeTranslateMessage, noticeDispatchMessage, noticeRegisterMessage, noticeLoadIcon, noticeGetShellWindow, noticeOpenInputDesktop, noticeCloseDesktop, noticeGetThreadDesktop, noticeGetUserObjectInformation, noticeGetWindowStation, noticeGetModule, noticeGetThreadID, noticeNotifyIcon, noticeShellExecute, noticeCoInitialize, noticeCoUninitialize} {
		if proc.Find() != nil {
			return ErrUnsupported
		}
	}
	if !windowsInteractiveDesktop() {
		return ErrUnsupported
	}
	hr, _, _ := noticeCoInitialize.Call(0, 0x6) // STA | DISABLE_OLE1DDE.
	if int32(hr) < 0 {
		return ErrDeliveryFailed
	}
	h.comInitialized = true
	h.onEvent = onEvent
	h.module, _, _ = noticeGetModule.Call(0)
	if h.module == 0 {
		return ErrDeliveryFailed
	}
	name, _ := syscall.UTF16PtrFromString(fmt.Sprintf("SIQ.AgentShield.Notify.%d", noticeClassSequence.Add(1)))
	h.className = name
	noticeCallbackOnce.Do(func() { noticeCallbackPointer = syscall.NewCallback(windowsNoticeProc) })
	class := windowsWindowClass{Size: uint32(unsafe.Sizeof(windowsWindowClass{})), WindowProc: noticeCallbackPointer, Instance: h.module, ClassName: name}
	atom, _, _ := noticeRegisterClass.Call(uintptr(unsafe.Pointer(&class)))
	if atom == 0 {
		return ErrDeliveryFailed
	}
	h.classRegistered = true
	// A hidden TOP-LEVEL tool window receives Explorer's TaskbarCreated
	// broadcast; HWND_MESSAGE would not. WS_VISIBLE is deliberately absent.
	h.window, _, _ = noticeCreateWindow.Call(0x80, uintptr(unsafe.Pointer(name)), 0, 0x80000000, 0, 0, 1, 1, 0, 0, h.module, 0)
	if h.window == 0 {
		return ErrDeliveryFailed
	}
	message, _ := syscall.UTF16PtrFromString("TaskbarCreated")
	registered, _, _ := noticeRegisterMessage.Call(uintptr(unsafe.Pointer(message)))
	if registered == 0 {
		return ErrDeliveryFailed
	}
	h.taskbarMessage = uint32(registered)
	h.icon, _, _ = noticeLoadIcon.Call(0, 32512) // IDI_APPLICATION, shared stock icon.
	if h.icon == 0 {
		return ErrDeliveryFailed
	}
	noticeWindows.Store(h.window, h)
	return nil
}

func windowsInteractiveDesktop() bool {
	shell, _, _ := noticeGetShellWindow.Call()
	station, _, _ := noticeGetWindowStation.Call()
	if shell == 0 || station == 0 {
		return false
	}
	var flags struct {
		Inherit  int32
		Reserved int32
		Flags    uint32
	}
	var needed uint32
	ok, _, _ := noticeGetUserObjectInformation.Call(station, 1, uintptr(unsafe.Pointer(&flags)), unsafe.Sizeof(flags), uintptr(unsafe.Pointer(&needed))) // UOI_FLAGS.
	if ok == 0 || flags.Flags&1 == 0 {                                                                                                                   // WSF_VISIBLE.
		return false
	}
	input, _, _ := noticeOpenInputDesktop.Call(0, 0, 1) // DESKTOP_READOBJECTS only.
	if input == 0 {
		return false
	}
	defer noticeCloseDesktop.Call(input)
	thread, _, _ := noticeGetThreadID.Call()
	current, _, _ := noticeGetThreadDesktop.Call(thread)
	var a, b [256]uint16
	readName := func(handle uintptr, dst *[256]uint16) bool {
		value, _, _ := noticeGetUserObjectInformation.Call(handle, 2, uintptr(unsafe.Pointer(dst)), unsafe.Sizeof(*dst), uintptr(unsafe.Pointer(&needed))) // UOI_NAME.
		return value != 0 && needed > 2 && needed <= uint32(unsafe.Sizeof(*dst))
	}
	return current != 0 && readName(input, &a) && readName(current, &b) && a == b
}

func (h *win32NoticeHost) Pump() error {
	for i := 0; i < 64; i++ {
		var message windowsMessage
		found, _, _ := noticePeekMessage.Call(uintptr(unsafe.Pointer(&message)), 0, 0, 0, 1) // PM_REMOVE.
		if found == 0 {
			return nil
		}
		if message.Message == winWMQuit {
			return ErrDeliveryFailed
		}
		noticeTranslateMessage.Call(uintptr(unsafe.Pointer(&message)))
		noticeDispatchMessage.Call(uintptr(unsafe.Pointer(&message)))
	}
	return nil
}

func (h *win32NoticeHost) iconData() windowsNotifyIconData {
	return windowsNotifyIconData{Size: uint32(unsafe.Sizeof(windowsNotifyIconData{})), Window: h.window, ID: winIconID}
}

func windowsSetText(dst []uint16, value string) bool {
	text, err := syscall.UTF16FromString(value)
	if err != nil || len(text) > len(dst) {
		return false
	}
	copy(dst, text)
	return true
}

func (h *win32NoticeHost) AddIcon() error {
	data := h.iconData()
	// A failed SETVERSION may have left this exact icon installed. Preserve
	// ownership until deletion succeeds instead of leaking it across retries.
	if h.iconAdded {
		if ok, _, _ := noticeNotifyIcon.Call(winNIMDelete, uintptr(unsafe.Pointer(&data))); ok == 0 {
			return ErrDeliveryFailed
		}
		h.iconAdded = false
	}
	data.Flags = winNIFMessage | winNIFIcon | winNIFTip | winNIFShowTip
	data.CallbackMessage, data.Icon = winNoticeCallback, h.icon
	windowsSetText(data.Tip[:], "SIQ AgentShield")
	ok, _, _ := noticeNotifyIcon.Call(winNIMAdd, uintptr(unsafe.Pointer(&data)))
	if ok == 0 {
		return ErrDeliveryFailed
	}
	h.iconAdded = true
	data.Version = 4
	ok, _, _ = noticeNotifyIcon.Call(winNIMSetVersion, uintptr(unsafe.Pointer(&data)))
	if ok == 0 {
		if deleted, _, _ := noticeNotifyIcon.Call(winNIMDelete, uintptr(unsafe.Pointer(&data))); deleted != 0 {
			h.iconAdded = false
		}
		return ErrDeliveryFailed
	}
	return nil
}

func windowsBalloonData(window uintptr, notice Notification) (windowsNotifyIconData, bool) {
	if !validCountOnlyNotification(notice) {
		return windowsNotifyIconData{}, false
	}
	data := windowsNotifyIconData{Size: uint32(unsafe.Sizeof(windowsNotifyIconData{})), Window: window, ID: winIconID,
		Flags: winNIFInfo | winNIFRealtime, InfoFlags: winNIIFInfo | winNIIFNoSound | winNIIFRespectQuietTime}
	if !windowsSetText(data.InfoTitle[:], notice.Title) || !windowsSetText(data.Info[:], notice.Body) {
		return windowsNotifyIconData{}, false
	}
	return data, true
}

func (h *win32NoticeHost) Notify(notice Notification) error {
	data, valid := windowsBalloonData(h.window, notice)
	if !valid || !h.iconAdded {
		return ErrDeliveryFailed
	}
	ok, _, _ := noticeNotifyIcon.Call(winNIMModify, uintptr(unsafe.Pointer(&data)))
	if ok == 0 {
		return ErrDeliveryFailed
	}
	return nil // Shell acceptance only, never evidence of visible delivery.
}

func (h *win32NoticeHost) OpenInbox(inbox string) error {
	if !windowsInboxURLValid(inbox) {
		return ErrDeliveryFailed
	}
	verb, _ := syscall.UTF16PtrFromString("open")
	target, _ := syscall.UTF16PtrFromString(inbox)
	result, _, _ := noticeShellExecute.Call(h.window, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(target)), 0, 0, 1)
	if result <= 32 {
		return ErrDeliveryFailed
	}
	return nil
}

func (h *win32NoticeHost) Close() error {
	var err error
	if h.window != 0 {
		noticeWindows.Delete(h.window)
		if h.iconAdded {
			data := h.iconData()
			if ok, _, _ := noticeNotifyIcon.Call(winNIMDelete, uintptr(unsafe.Pointer(&data))); ok == 0 {
				err = ErrDeliveryFailed
			}
			h.iconAdded = false
		}
		if ok, _, _ := noticeDestroyWindow.Call(h.window); ok == 0 {
			err = ErrDeliveryFailed
		}
		h.window = 0
	}
	if h.classRegistered {
		if ok, _, _ := noticeUnregisterClass.Call(uintptr(unsafe.Pointer(h.className)), h.module); ok == 0 {
			err = ErrDeliveryFailed
		}
		h.classRegistered = false
	}
	if h.comInitialized {
		noticeCoUninitialize.Call()
		h.comInitialized = false
	}
	return err
}

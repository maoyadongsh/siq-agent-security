package main

import (
	"context"
	"io"
	"runtime"
	"strings"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/notify"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

// desktopNotifier resolves the notifier for the UX-008 background launcher
// layer. Configured argv wins; otherwise the platform default is used when it
// exists. Nothing here fabricates delivery: an unsupported platform with no
// override returns nil and serve logs one line instead of claiming notify ran.
func desktopNotifier(cfg state.Config) notify.Notifier {
	if cmd := strings.Fields(cfg.DesktopNotifyCommand); len(cmd) > 0 {
		return notify.CommandNotifier{Bin: cmd[0], Args: cmd[1:], Timeout: 5 * time.Second}
	}
	return notify.DefaultNotifier(runtime.GOOS, cfg.Port)
}

// pendingConfirmations counts confirmations that are actionable right now.
// Only the count is observable by the dispatcher; request metadata never
// leaves the engine.
func pendingConfirmations(eng *receipt.Engine) func() int {
	return func() int {
		n := 0
		list := eng.Confirmations()
		for _, c := range list.Items {
			if c.Status == "pending" {
				n++
			}
		}
		return n
	}
}

// startDesktopNotify launches the dispatcher goroutine when the user opted in
// via config. It returns the cancel func (nil when disabled or unsupported)
// and writes one startup line so the log states what actually runs.
func startDesktopNotify(cfg state.Config, eng *receipt.Engine, logf func(string, ...any)) context.CancelFunc {
	if !cfg.DesktopNotify {
		return nil
	}
	notifier := desktopNotifier(cfg)
	if notifier == nil {
		logf("desktop notifications enabled but no notifier available on %s and none configured; confirmation inbox remains fully usable", runtime.GOOS)
		return nil
	}
	startupDelay := time.Duration(0)
	if runtime.GOOS == "windows" {
		startupDelay = 15 * time.Second
	}
	d := notify.NewDispatcher(pendingConfirmations(eng), notifier, notify.DispatcherOptions{
		StartupDelay: startupDelay,
		Log: func(err error) {
			logf("desktop notification delivery failed (will retry after coalesce window): %v", err)
		},
	})
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		d.Run(ctx)
	}()
	logf("desktop notification dispatcher started (count-only, coalesce 15s)")
	var closeOnce sync.Once
	return func() {
		closeOnce.Do(func() {
			cancel()
			if closer, ok := notifier.(io.Closer); ok {
				if err := closer.Close(); err != nil {
					logf("desktop notification cleanup did not finish")
				}
			}
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				logf("desktop notification dispatcher shutdown timed out")
			}
		})
	}
}

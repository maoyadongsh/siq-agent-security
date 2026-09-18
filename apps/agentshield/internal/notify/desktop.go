package notify

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// DefaultNotifier selects a platform implementation without starting it. The
// Windows target comes only from the daemon's validated listening port, never
// from notification content, window messages, or an arbitrary URL.
func DefaultNotifier(goos string, port int) Notifier {
	if goos == "windows" {
		if port < 1 || port > 65535 {
			return nil
		}
		return newNativeNotifier(fmt.Sprintf("http://127.0.0.1:%d/confirmations", port))
	}
	argv, ok := DefaultCommand(goos)
	if !ok || len(argv) == 0 {
		return nil
	}
	return CommandNotifier{Bin: argv[0], Args: argv[1:], Timeout: 5 * time.Second}
}

// Native desktop surfaces may be inspected by other local applications. Do
// not let a future caller accidentally put request metadata on that surface.
func validCountOnlyNotification(n Notification) bool {
	const prefix = "有 "
	const suffix = " 项待确认操作，请在本地控制台处理"
	if n.Title != "SIQ AgentShield" || !strings.HasPrefix(n.Body, prefix) || !strings.HasSuffix(n.Body, suffix) {
		return false
	}
	raw := strings.TrimSuffix(strings.TrimPrefix(n.Body, prefix), suffix)
	count, err := strconv.ParseInt(raw, 10, 64)
	return err == nil && count > 0 && strconv.FormatInt(count, 10) == raw
}

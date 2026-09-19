//go:build !windows

package notify

func newNativeNotifier(string) Notifier { return nil }

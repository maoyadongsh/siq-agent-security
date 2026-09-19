package notify

import (
	"testing"
	"time"
)

func TestNativeNotificationRejectsMetadataAndMalformedCounts(t *testing.T) {
	good := Notification{Title: "SIQ AgentShield", Body: "有 2 项待确认操作，请在本地控制台处理"}
	if !validCountOnlyNotification(good) {
		t.Fatal("fixed count-only notification rejected")
	}
	for _, n := range []Notification{
		{Title: "request-secret", Body: good.Body},
		{Title: good.Title, Body: good.Body + " token=secret"},
		{Title: good.Title, Body: "有 0 项待确认操作，请在本地控制台处理"},
		{Title: good.Title, Body: "有 -1 项待确认操作，请在本地控制台处理"},
		{Title: good.Title, Body: "有 +2 项待确认操作，请在本地控制台处理"},
		{Title: good.Title, Body: "有 02 项待确认操作，请在本地控制台处理"},
		{Title: good.Title, Body: "有 2\x00 项待确认操作，请在本地控制台处理"},
		{Title: good.Title, Body: "有 9999999999999999999999 项待确认操作，请在本地控制台处理"},
	} {
		if validCountOnlyNotification(n) {
			t.Fatal("non-count content accepted")
		}
	}
}

func TestWindowsDefaultRejectsInvalidListeningPort(t *testing.T) {
	for _, port := range []int{-1, 0, 65536} {
		if DefaultNotifier("windows", port) != nil {
			t.Fatalf("invalid port %d created a notifier", port)
		}
	}
}

func TestDesktopStartupCooldownDoesNotConsumePendingReminder(t *testing.T) {
	st := &stubNotifier{}
	reads := 0
	d := NewDispatcher(func() int { reads++; return 2 }, st, DispatcherOptions{StartupDelay: 15 * time.Second})
	if d.Tick(d.readyAt.Add(-time.Nanosecond)) || reads != 0 || st.count() != 0 {
		t.Fatal("startup cooldown delivered or consumed a reminder")
	}
	if !d.Tick(d.readyAt) || reads != 1 || st.count() != 1 {
		t.Fatal("pending reminder was lost after startup cooldown")
	}
	if d.Tick(d.readyAt.Add(time.Second)) || st.count() != 1 {
		t.Fatal("unchanged pending count was delivered twice")
	}
}

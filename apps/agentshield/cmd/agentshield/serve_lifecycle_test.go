package main

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"
)

func TestDrainRejectsNewRequestsAndWaitsForActiveHandler(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	h := &drainingHandler{done: make(chan struct{}), handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		close(entered)
		<-release
		w.WriteHeader(http.StatusOK)
	})}
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/", nil))
	}()
	<-entered
	done := h.drain()
	late := httptest.NewRecorder()
	h.ServeHTTP(late, httptest.NewRequest("POST", "/", nil))
	if late.Code != 503 || calls.Load() != 1 {
		t.Error("draining dispatched another operation")
	}
	select {
	case <-done:
		t.Error("drain completed before active operation")
	default:
	}
	close(release)
	<-finished
	select {
	case <-done:
	default:
		t.Fatal("completed request did not finish drain")
	}
	<-h.drain() // Repeated drain is safe and cannot double close.
}

func TestHTTPStopCancelsConnectionButWaitsForHandler(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	entered, canceled, release := make(chan struct{}), make(chan struct{}), make(chan struct{})
	hs := &http.Server{ReadHeaderTimeout: time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-r.Context().Done()
		close(canceled)
		<-release // Model durable cleanup that must finish after request cancellation.
	})}
	stop := make(chan os.Signal, 1)
	result := make(chan error, 1)
	go func() { result <- serveLocalHTTP(hs, ln, stop, 20*time.Millisecond) }()
	clientDone := make(chan struct{})
	go func() {
		defer close(clientDone)
		client := localClient()
		defer client.CloseIdleConnections()
		resp, err := client.Get("http://" + ln.Addr().String())
		if err == nil {
			_, _ = io.Copy(io.Discard, resp.Body)
			_ = resp.Body.Close()
		}
	}()
	defer func() {
		close(release)
		_ = hs.Close()
		select {
		case <-clientDone:
		case <-time.After(5 * time.Second):
			t.Error("client did not exit")
		}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("handler not entered")
	}
	stop <- os.Interrupt
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("request not canceled after grace")
	}
	select {
	case err := <-result:
		t.Fatalf("serve returned while handler still owns state: %v", err)
	default:
	}
	// Cleanup runs after the deferred handler release and connection cleanup.
	t.Cleanup(func() {
		select {
		case err := <-result:
			if !errors.Is(err, context.DeadlineExceeded) {
				t.Errorf("missing forced-close diagnostic: %v", err)
			}
		case <-time.After(5 * time.Second):
			t.Error("serve did not finish after handler completion")
		}
	})
}

func TestHTTPStopWithoutRequests(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	stop := make(chan os.Signal, 1)
	stop <- os.Interrupt
	hs := &http.Server{Handler: http.NotFoundHandler(), ReadHeaderTimeout: time.Second}
	if err := serveLocalHTTP(hs, ln, stop, time.Second); err != nil {
		t.Fatal(err)
	}
}

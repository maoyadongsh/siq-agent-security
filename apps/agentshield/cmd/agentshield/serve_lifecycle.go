package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os"
	"sync"
	"time"
)

// Request completion, not listener closure, is the boundary after which the
// caller may release its state writer. Closing a connection alone does not
// guarantee that its handler has stopped touching durable state.
type drainingHandler struct {
	handler  http.Handler
	mu       sync.Mutex
	active   int
	draining bool
	done     chan struct{}
}

func (h *drainingHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	if h.draining {
		h.mu.Unlock()
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	h.active++
	h.mu.Unlock()
	defer func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		h.active--
		if h.draining && h.active == 0 {
			close(h.done)
		}
	}()
	h.handler.ServeHTTP(w, r)
}

func (h *drainingHandler) drain() <-chan struct{} {
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.draining {
		h.draining = true
		if h.active == 0 {
			close(h.done)
		}
	}
	return h.done
}

func serveLocalHTTP(hs *http.Server, ln net.Listener, stop <-chan os.Signal, grace time.Duration) error {
	h := &drainingHandler{handler: hs.Handler, done: make(chan struct{})}
	hs.Handler = h
	served := make(chan error, 1)
	go func() { served <- hs.Serve(ln) }()
	var serveErr error
	select {
	case <-stop:
	case serveErr = <-served:
		// An unexpected listener failure also must not unlock live writers.
	}
	done := h.drain()
	ctx, cancel := context.WithTimeout(context.Background(), grace)
	defer cancel()
	shutdownErr := hs.Shutdown(ctx)
	if shutdownErr != nil {
		_ = hs.Close()
	}
	<-done
	if serveErr == nil {
		serveErr = <-served
	}
	if errors.Is(serveErr, http.ErrServerClosed) {
		serveErr = nil
	}
	// Timeout means connections were force-closed, but handler completion was
	// still awaited. Surface it for diagnosis instead of claiming clean drain.
	return errors.Join(serveErr, shutdownErr)
}

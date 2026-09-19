package server

import (
	"context"
	"errors"
	"net/http"
	"time"
)

const adapterPreviewWorkBudget = 165 * time.Second
const adapterManagementWriteBudget = 175 * time.Second

// Only management operations extend the response deadline. Admission to this
// synchronous slot never queues behind another operation or starts background work.
func (s *Server) adapterManagementSlot(w http.ResponseWriter, r *http.Request) bool {
	if !s.adapterPlanMu.TryLock() {
		w.Header().Set("Retry-After", "1")
		writeJSON(w, http.StatusTooManyRequests, map[string]string{"error": "adapter_busy"})
		return false
	}
	if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(adapterManagementWriteBudget)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		s.adapterPlanMu.Unlock()
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "adapter_response_unavailable"})
		return false
	}
	if adapterRequestCanceled(w, r.Context()) {
		s.adapterPlanMu.Unlock()
		return false
	}
	return true
}

func adapterRequestCanceled(w http.ResponseWriter, ctx context.Context) bool {
	if ctx.Err() == nil {
		return false
	}
	writeJSON(w, http.StatusRequestTimeout, map[string]string{"error": "adapter_interrupted"})
	return true
}

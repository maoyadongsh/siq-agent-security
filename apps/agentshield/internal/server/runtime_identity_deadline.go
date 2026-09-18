package server

import (
	"errors"
	"net/http"
	"time"
)

const runtimeIdentityWriteBudget = 65 * time.Second

// Identity management can finish durable writes after the global socket deadline.
// Extend only its response window; never retry an uncertain issuance or revocation.
func runtimeIdentityResponseReady(w http.ResponseWriter, r *http.Request) bool {
	if r.Context().Err() != nil {
		writeJSON(w, http.StatusRequestTimeout, map[string]string{"error": "runtime_identity_interrupted"})
		return false
	}
	if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(runtimeIdentityWriteBudget)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "runtime_identity_unavailable"})
		return false
	}
	return true
}

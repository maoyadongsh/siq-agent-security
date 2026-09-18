package server

import (
	"errors"
	"net/http"
	"runtime"
	"time"
)

const runtimeIdentityWriteBudget = 65 * time.Second

// Identity management can finish durable writes after the global socket deadline.
// Extend only its response window; never retry an uncertain issuance or revocation.
func runtimeIdentityResponseReady(w http.ResponseWriter, r *http.Request) bool {
	return authorityManagementResponseReady(w, r, "runtime_identity")
}

func skillContextResponseReady(w http.ResponseWriter, r *http.Request) bool {
	return authorityManagementResponseReady(w, r, "skill_context")
}

func authorityManagementResponseReady(w http.ResponseWriter, r *http.Request, category string) bool {
	if r.Context().Err() != nil {
		writeJSON(w, http.StatusRequestTimeout, map[string]string{"error": category + "_interrupted"})
		return false
	}
	if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(runtimeIdentityWriteBudget)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": category + "_unavailable"})
		return false
	}
	return true
}

// Windows enrollment and WorkBuddy payload validation can outlive the global
// socket write deadline. Keep authorization and uncertainty handling unchanged.
func workBuddyRuntimeResponseReady(w http.ResponseWriter, r *http.Request) bool {
	if runtime.GOOS != "windows" {
		return true
	}
	return authorityManagementResponseReady(w, r, "runtime_response")
}

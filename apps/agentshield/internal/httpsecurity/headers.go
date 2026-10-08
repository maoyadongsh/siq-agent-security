// Package httpsecurity defines browser defenses shared by the local HTTP entry
// and its standalone embedded UI. It does not authorize any request.
package httpsecurity

import "net/http"

// CSP retains the enterprise entry's policy, including inline styles required
// by the current UI. Keep apps/web/security-headers.inc in sync.
const CSP = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'"

// Apply must run before any response is written, including authentication and
// Host/Origin errors. Only known immutable assets may override the cache policy.
func Apply(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Content-Security-Policy", CSP)
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("X-Frame-Options", "DENY")
	h.Set("Referrer-Policy", "strict-origin-when-cross-origin")
	h.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
	h.Set("Cache-Control", "no-store")
}

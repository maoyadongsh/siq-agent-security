// Package ui serves the AgentShield local console (dev-spec §3.10).
// The Vite build from apps/web (VITE_APP=agentshield) is copied into
// embedded/; when that has not been run, a placeholder index.html is served.
package ui

import (
	"embed"
	"io/fs"
	"net/http"
	"path"
	"strings"

	"siq-agent-security/apps/agentshield/internal/httpsecurity"
)

//go:embed all:embedded
var embeddedFS embed.FS

// Handler serves static files and falls back to index.html for SPA routes.
// Callers must still enforce loopback; this handler does not check RemoteAddr.
func Handler() http.Handler {
	sub, err := fs.Sub(embeddedFS, "embedded")
	if err != nil {
		return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			httpsecurity.Apply(w)
			http.Error(w, "ui embed missing", http.StatusInternalServerError)
		})
	}
	files := http.FileServer(http.FS(sub))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		httpsecurity.Apply(w)
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		p := path.Clean("/" + r.URL.Path)
		if p != "/" {
			rel := strings.TrimPrefix(p, "/")
			if info, err := fs.Stat(sub, rel); err == nil && !info.IsDir() {
				if strings.HasPrefix(p, "/assets/") {
					w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
				}
				files.ServeHTTP(w, r)
				return
			}
			if ext := path.Ext(p); p == "/assets" || strings.HasPrefix(p, "/assets/") || ext != "" && ext != ".html" {
				http.NotFound(w, r)
				return
			}
		}
		r2 := r.Clone(r.Context())
		r2.URL.Path = "/"
		w.Header().Set("Cache-Control", "no-store")
		files.ServeHTTP(w, r2)
	})
}

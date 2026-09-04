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
)

//go:embed all:embedded
var embeddedFS embed.FS

// Handler serves static files and falls back to index.html for SPA routes.
// Callers must still enforce loopback; this handler does not check RemoteAddr.
func Handler() http.Handler {
	sub, err := fs.Sub(embeddedFS, "embedded")
	if err != nil {
		return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			http.Error(w, "ui embed missing", http.StatusInternalServerError)
		})
	}
	files := http.FileServer(http.FS(sub))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		p := path.Clean("/" + r.URL.Path)
		if p != "/" {
			rel := strings.TrimPrefix(p, "/")
			if _, err := fs.Stat(sub, rel); err == nil {
				files.ServeHTTP(w, r)
				return
			}
			if ext := path.Ext(p); ext != "" && ext != ".html" {
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

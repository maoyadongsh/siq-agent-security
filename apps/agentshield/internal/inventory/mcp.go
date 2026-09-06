package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const mcpMaxBytes = 1 << 20

type mcpWellKnown struct {
	rel    string
	client string
}

// Well-known MCP client configs, relative to $HOME. Aligned with
// connectors/mcp (must not import that package main).
var mcpConfigs = []mcpWellKnown{
	{".cursor/mcp.json", "cursor"},
	{".claude.json", "claude"},
	{".claude/mcp.json", "claude"},
	{".windsurf/mcp_config.json", "windsurf"},
	{".codeium/windsurf/mcp_config.json", "windsurf"},
}

type mcpFile struct {
	Servers map[string]mcpServer `json:"mcpServers"`
}

type mcpServer struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
	URL     string            `json:"url"`
}

func (r *run) mcpConfigs() {
	home := r.opts.Home
	if home == "" {
		return
	}
	found := false
	for _, wk := range mcpConfigs {
		full := filepath.Join(home, filepath.FromSlash(wk.rel))
		if r.mcpFile(full, wk.rel, wk.client) {
			found = true
		}
	}
	if found && !containsStr(r.report.Platforms, "mcp") {
		r.report.Platforms = append(r.report.Platforms, "mcp")
	}
}

func (r *run) mcpFile(full, rel, client string) bool {
	st, err := os.Lstat(full)
	if err != nil {
		return false
	}
	if st.Mode()&os.ModeSymlink != 0 {
		r.report.Skipped = append(r.report.Skipped, "symlink:mcp:"+rel)
		return false
	}
	if !st.Mode().IsRegular() {
		return false
	}
	if st.Size() > mcpMaxBytes {
		r.report.Skipped = append(r.report.Skipped, "oversize:mcp:"+rel)
		return false
	}
	raw, err := os.ReadFile(full)
	if err != nil {
		r.report.Skipped = append(r.report.Skipped, "unreadable:mcp:"+rel)
		return false
	}
	var cfg mcpFile
	if json.Unmarshal(raw, &cfg) != nil {
		r.report.Skipped = append(r.report.Skipped, "unreadable:mcp:"+rel)
		return false
	}
	if len(cfg.Servers) == 0 {
		return false
	}
	names := make([]string, 0, len(cfg.Servers))
	for name := range cfg.Servers {
		names = append(names, name)
	}
	sort.Strings(names)
	ok := false
	for _, name := range names {
		if r.mcpServer(rel, client, name, cfg.Servers[name]) {
			ok = true
		}
	}
	return ok
}

func (r *run) mcpServer(rel, client, name string, srv mcpServer) bool {
	name = strings.TrimSpace(name)
	if name == "" || looksLikeSecret(name) {
		return false
	}
	secrets := envValueSet(srv.Env)
	envKeys := make([]string, 0, len(srv.Env))
	for k := range srv.Env {
		k = strings.TrimSpace(k)
		if k == "" {
			continue
		}
		envKeys = append(envKeys, truncate(k, 128))
	}
	sort.Strings(envKeys)
	cmdBase := ""
	if srv.Command != "" {
		cmdBase = filepath.Base(scrubSecretValues(srv.Command, secrets))
		if looksLikeSecret(cmdBase) {
			cmdBase = ""
		}
	}
	redactedArgs := make([]string, 0, len(srv.Args))
	for _, a := range srv.Args {
		redactedArgs = append(redactedArgs, truncate(scrubSecretValues(a, secrets), 128))
	}
	host := sanitizeMCPURL(srv.URL)
	transport := mcpTransport(srv)
	pathHash := sha256.Sum256([]byte(rel + "\x00" + name))
	id := "mcp:" + client + ":" + name + "@" + hex.EncodeToString(pathHash[:])[:8]
	redactedRel := redactHome(filepath.Join(r.opts.Home, filepath.FromSlash(rel)), r.opts.Home)
	locator := "mcp://" + redactedRel + "#" + name
	facts, _ := json.Marshal(map[string]any{
		"server": name, "config": redactedRel, "client": client, "transport": transport,
		"command": cmdBase, "args": redactedArgs, "env_keys": envKeys, "url": host,
	})
	sum := sha256.Sum256(facts)
	evID := r.evidence("platform_config", locator, hex.EncodeToString(sum[:]))
	attrs := map[string]string{
		"client": client, "transport": transport, "config": redactedRel,
		"discovery_basis": "client_config",
	}
	if len(envKeys) > 0 {
		attrs["env_keys"] = strings.Join(envKeys, ",")
	}
	if cmdBase != "" {
		attrs["command"] = truncate(cmdBase, 128)
	}
	if host != "" {
		attrs["url"] = host
	}
	r.report.Candidates = append(r.report.Candidates, Candidate{
		CandidateID: id, SourceType: "mcp_server", SourceLocator: locator,
		DiscoveredAt: r.now, Name: truncate(name, 256), Framework: "unknown",
		Attributes: attrs, EvidenceIDs: []string{evID}, Confidence: 0.9, Status: "candidate",
	})
	return true
}

func mcpTransport(srv mcpServer) string {
	if srv.URL != "" {
		if strings.Contains(strings.ToLower(srv.URL), "/sse") {
			return "sse"
		}
		return "http"
	}
	if srv.Command != "" {
		return "stdio"
	}
	return "unknown"
}

func sanitizeMCPURL(raw string) string {
	if raw == "" {
		return ""
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return ""
	}
	return u.Scheme + "://" + u.Host
}

func envValueSet(env map[string]string) map[string]bool {
	set := map[string]bool{}
	for _, v := range env {
		if len(v) >= 4 {
			set[v] = true
		}
	}
	return set
}

func scrubSecretValues(s string, secretVals map[string]bool) string {
	for v := range secretVals {
		if v != "" && strings.Contains(s, v) {
			s = strings.ReplaceAll(s, v, "[REDACTED]")
		}
	}
	return s
}

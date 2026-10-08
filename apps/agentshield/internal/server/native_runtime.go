package server

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

var nativeCredentialPattern = regexp.MustCompile(`^nhp-[a-f0-9]{64}$`)

func nativeUnavailable() error { return errors.New("native_host_unavailable") }

type nativeConnection struct {
	SchemaVersion      string `json:"schema_version"`
	Credential         string `json:"credential"`
	VerificationSocket string `json:"verification_socket"`
}
type nativeMount struct {
	InstanceID     string `json:"instance_id"`
	InstallID      string `json:"install_id"`
	ClaimSignature string `json:"claim_signature"`
	HostRoot       string `json:"host_root"`
	RuntimeRoot    string `json:"runtime_root"`
}

func (m nativeMount) install() skillcontext.NativeInstallMount {
	return skillcontext.NativeInstallMount{InstanceID: m.InstanceID, InstallID: m.InstallID, ClaimSignature: m.ClaimSignature, HostRoot: m.HostRoot, RuntimeRoot: m.RuntimeRoot}
}

type nativeVerified struct {
	SchemaVersion string               `json:"schema_version"`
	Nonce         string               `json:"nonce"`
	Subject       skillcontext.Subject `json:"subject"`
	Artifact      string               `json:"artifact_sha256"`
	ExpiresAt     string               `json:"expires_at"`
	Mounts        []nativeMount        `json:"install_mounts"`
}

// NativeRuntime is fixed at Engine construction and bound exactly once before
// the server starts. It contains no rules and never accepts a caller's verifier URL.
type NativeRuntime struct {
	failed         atomic.Bool
	mu             sync.RWMutex
	connection     nativeConnection
	configPath     string
	configIdentity os.FileInfo
	socketIdentity os.FileInfo
	client         *http.Client
	host           *skillcontext.NativeHostBridge
	identities     *runtimeidentity.Store
	lookup         receipt.NativeCallLookup
}

func nativePrivatePath(path string, directory bool) (os.FileInfo, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, nativeUnavailable()
	}
	expected := os.FileMode(0600)
	if directory {
		expected = 0700
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode().Perm() != expected || (directory && !info.IsDir()) || (!directory && !info.Mode().IsRegular() && info.Mode()&os.ModeSocket == 0) {
		return nil, nativeUnavailable()
	}
	// Read-only standard-library reflection avoids a cross-platform syscall type.
	// This profile is Linux-only; missing UID/link facts fail closed.
	facts := reflect.Indirect(reflect.ValueOf(info.Sys()))
	if !facts.IsValid() || facts.Kind() != reflect.Struct {
		return nil, nativeUnavailable()
	}
	uid := facts.FieldByName("Uid")
	links := facts.FieldByName("Nlink")
	if !uid.IsValid() || !uid.CanUint() || uid.Uint() != uint64(os.Getuid()) || !links.IsValid() || !links.CanUint() || (!directory && links.Uint() != 1) {
		return nil, nativeUnavailable()
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return nil, nativeUnavailable()
	}
	return info, nil
}

// OpenNativeRuntime reads only the opt-in private state configuration. The
// caller must already own the state Writer; no file is created or repaired here.
func OpenNativeRuntime(dir string) (*NativeRuntime, error) {
	if runtime.GOOS != "linux" || os.Getuid() <= 0 {
		return nil, nativeUnavailable()
	}
	parent := filepath.Join(dir, "native-host")
	if _, err := nativePrivatePath(dir, true); err != nil {
		return nil, err
	}
	if _, err := nativePrivatePath(parent, true); err != nil {
		return nil, err
	}
	path := filepath.Join(parent, "connection.json")
	info, err := nativePrivatePath(path, false)
	if err != nil || !info.Mode().IsRegular() {
		return nil, nativeUnavailable()
	}
	raw, err := statefs.ReadPrivateFile(path, 16384)
	if err != nil || !exactJSONObject(raw, "schema_version", "credential", "verification_socket") {
		return nil, nativeUnavailable()
	}
	var cfg nativeConnection
	if json.Unmarshal(raw, &cfg) != nil || cfg.SchemaVersion != "native-host-connection/v1" || !nativeCredentialPattern.MatchString(cfg.Credential) {
		return nil, nativeUnavailable()
	}
	if _, err := nativePrivatePath(filepath.Dir(cfg.VerificationSocket), true); err != nil {
		return nil, err
	}
	// The verifier must exist before opt-in serve starts; it cannot be silently
	// replaced or rebound later under the same pathname.
	socketInfo, err := nativePrivatePath(cfg.VerificationSocket, false)
	if err != nil || socketInfo.Mode()&os.ModeSocket == 0 {
		return nil, nativeUnavailable()
	}
	n := &NativeRuntime{connection: cfg, configPath: path, configIdentity: info, socketIdentity: socketInfo}
	transport := &http.Transport{Proxy: nil, DisableKeepAlives: true, ResponseHeaderTimeout: 5 * time.Second, MaxResponseHeaderBytes: 8192,
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			if err := n.checkConnection(); err != nil {
				return nil, err
			}
			return (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "unix", cfg.VerificationSocket)
		}}
	n.client = &http.Client{Transport: transport, Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return nativeUnavailable() }}
	if err := n.checkConnection(); err != nil {
		return nil, err
	}
	return n, nil
}
func (n *NativeRuntime) checkConnection() (err error) {
	defer func() {
		if err != nil && n != nil {
			n.failed.Store(true)
		}
	}()
	if n == nil || n.failed.Load() {
		return nativeUnavailable()
	}
	for _, dir := range []string{filepath.Dir(n.configPath), filepath.Dir(n.connection.VerificationSocket)} {
		if _, err := nativePrivatePath(dir, true); err != nil {
			return err
		}
	}
	for _, entry := range []struct {
		path   string
		before os.FileInfo
	}{{n.configPath, n.configIdentity}, {n.connection.VerificationSocket, n.socketIdentity}} {
		now, err := nativePrivatePath(entry.path, false)
		if err != nil || !os.SameFile(now, entry.before) {
			return nativeUnavailable()
		}
	}
	raw, err := statefs.ReadPrivateFile(n.configPath, 16384)
	var cfg nativeConnection
	if err != nil || !exactJSONObject(raw, "schema_version", "credential", "verification_socket") || json.Unmarshal(raw, &cfg) != nil || cfg != n.connection {
		return nativeUnavailable()
	}
	return nil
}
func nativeSubjectShape(raw []byte) bool {
	// Task-less subjects are only internal managed-session rechecks.
	return exactJSONObject(raw, "platform", "instance_id", "agent_id", "session_id", "task_id") || exactJSONObject(raw, "platform", "instance_id", "agent_id", "session_id")
}
func (n *NativeRuntime) verify(ctx context.Context, subject skillcontext.Subject, artifact string) (nativeVerified, error) {
	var result nativeVerified
	if err := n.checkConnection(); err != nil {
		return result, err
	}
	nonceBytes := make([]byte, 16)
	if _, err := rand.Read(nonceBytes); err != nil {
		return result, nativeUnavailable()
	}
	nonce := hex.EncodeToString(nonceBytes)
	body, err := json.Marshal(map[string]any{"schema_version": "native-host-verification/v1", "nonce": nonce, "subject": subject, "artifact_sha256": artifact})
	if err != nil {
		return result, nativeUnavailable()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://native-host/verify", bytes.NewReader(body))
	if err != nil {
		return result, nativeUnavailable()
	}
	req.Header.Set("Authorization", "Bearer "+n.connection.Credential)
	req.Header.Set("Content-Type", "application/json")
	resp, err := n.client.Do(req)
	if err != nil {
		return result, nativeUnavailable()
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
	if err != nil || resp.StatusCode != 200 || len(raw) > 65536 || !exactJSONObject(raw, "schema_version", "nonce", "subject", "artifact_sha256", "expires_at", "install_mounts") {
		return result, nativeUnavailable()
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || !nativeSubjectShape(fields["subject"]) {
		return result, nativeUnavailable()
	}
	var mounts []json.RawMessage
	if json.Unmarshal(fields["install_mounts"], &mounts) != nil || len(mounts) > 64 {
		return result, nativeUnavailable()
	}
	for _, m := range mounts {
		if !exactJSONObject(m, "instance_id", "install_id", "claim_signature", "host_root", "runtime_root") {
			return result, nativeUnavailable()
		}
	}
	if json.Unmarshal(raw, &result) != nil || result.SchemaVersion != "native-host-verified/v1" || result.Nonce != nonce || result.Subject != subject || result.Artifact != artifact {
		return nativeVerified{}, nativeUnavailable()
	}
	until, err := time.Parse(time.RFC3339Nano, result.ExpiresAt)
	now := time.Now()
	if err != nil || !now.Before(until) || until.After(now.Add(time.Hour)) || n.checkConnection() != nil {
		return nativeVerified{}, nativeUnavailable()
	}
	for _, mount := range result.Mounts {
		if mount.InstanceID != subject.InstanceID {
			return nativeVerified{}, nativeUnavailable()
		}
	}
	return result, nil
}
func (n *NativeRuntime) Lookup(req receipt.Request) (bool, *receipt.NativeInvocationVerification, error) {
	n.mu.RLock()
	lookup := n.lookup
	n.mu.RUnlock()
	if lookup == nil {
		return true, nil, nativeUnavailable()
	}
	return lookup(req)
}

// Creation fixes a mandatory policy; it does not attest a not-yet-started
// process. Tool execution still requires fresh kernel-backed verification.
func (s *Server) nativeIdentityCreationReady() bool {
	n := s.d.NativeRuntime
	if n == nil || !s.d.Engine.NativeCallsConfigured() {
		return false
	}
	n.mu.RLock()
	bound := n.host != nil && n.lookup != nil && n.identities == s.runtimeIdentities
	n.mu.RUnlock()
	return bound && n.checkConnection() == nil
}

func (s *Server) initNativeRuntime() error {
	n := s.d.NativeRuntime
	if n == nil {
		return nil
	}
	if !s.d.Engine.NativeCallsConfigured() {
		return nativeUnavailable()
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.host != nil || n.lookup != nil || n.identities != nil {
		return nativeUnavailable()
	}
	verify := func(subject skillcontext.Subject, artifact string) (time.Time, error) {
		policy, err := s.runtimeIdentities.NativePolicy(subject.Platform, subject.AgentID)
		if err != nil || policy == nil || policy.RuntimeArtifactSHA256 != artifact {
			return time.Time{}, nativeUnavailable()
		}
		got, err := n.verify(context.Background(), subject, artifact)
		if err != nil {
			return time.Time{}, err
		}
		return time.Parse(time.RFC3339Nano, got.ExpiresAt)
	}
	resolve := func(subject skillcontext.Subject, source skillcontext.NativeSource) (skillcontext.InstallRef, error) {
		policy, err := s.runtimeIdentities.NativePolicy(subject.Platform, subject.AgentID)
		if err != nil || policy == nil {
			return skillcontext.InstallRef{}, nativeUnavailable()
		}
		got, err := n.verify(context.Background(), subject, policy.RuntimeArtifactSHA256)
		if err != nil {
			return skillcontext.InstallRef{}, err
		}
		mounts := make([]skillcontext.NativeInstallMount, 0, len(got.Mounts))
		for _, mount := range got.Mounts {
			mounts = append(mounts, mount.install())
		}
		resolver, err := skillcontext.NewNativeInstallResolver(s.skillInstallations, mounts, func(ctx context.Context, sub skillcontext.Subject, m skillcontext.NativeInstallMount) error {
			fresh, err := n.verify(ctx, sub, policy.RuntimeArtifactSHA256)
			if err != nil {
				return err
			}
			for _, actual := range fresh.Mounts {
				if actual.install() == m {
					return nil
				}
			}
			return nativeUnavailable()
		})
		if err != nil {
			return skillcontext.InstallRef{}, err
		}
		return resolver.Resolve(subject, source)
	}
	host, err := skillcontext.OpenNativeHost(s.d.Store.Dir, skillcontext.NativeHostDeps{
		InvocationDeps: skillcontext.InvocationDeps{Deps: skillcontext.Deps{Key: s.d.Key,
			ReadGrant: func(id string) (*grant.Grant, error) {
				g := s.d.Store.GrantByID(id)
				if g == nil {
					return nil, nativeUnavailable()
				}
				return g, nil
			},
			ReadInstall: func(id string) (*skillinstall.Record, error) {
				return s.skillInstallations.RecordByID(context.Background(), id)
			},
			ReadInstance: s.runtimeIdentities.InspectByInstance,
			SessionBound: func(platform, agent, session, grantID string) (time.Time, error) {
				_, b, err := s.intents.ResolveBinding(platform, session, agent)
				if err != nil || b == nil || b.GrantRef == nil || b.GrantRef.GrantID != grantID {
					return time.Time{}, nativeUnavailable()
				}
				return time.Parse(time.RFC3339, b.ExpiresAt)
			}},
			ValidateInstalled: func(g *grant.Grant, _ skillcontext.InstallRef) error {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				return s.skillInstallations.ValidateRuntimeGrant(ctx, g)
			},
			Audit: func(event, id string) error {
				return s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: event, ActorID: "native-host", Target: id})
			}},
		VerifyRuntime: verify, ResolveSource: resolve,
	})
	if err != nil {
		return err
	}
	lookup, err := host.Calls().RequiredLookup(s.runtimeIdentities)
	if err != nil {
		return err
	}
	n.host, n.identities, n.lookup = host, s.runtimeIdentities, lookup
	return nil
}
func nativeRequestSubject(req receipt.Request) skillcontext.Subject {
	task := req.RuntimeTaskID
	if task == "" {
		task = req.TaskID
	}
	return skillcontext.Subject{Platform: req.Platform, AgentID: req.AgentID, InstanceID: "hi-" + strings.TrimPrefix(req.AgentID, "hri-"), SessionID: req.SessionID, TaskID: task}
}

// Bind runs only after the existing scoped runtime HTTP authentication. The
// returned closer is used only when no handler will be authorized to enter.
func (n *NativeRuntime) bindDecision(req receipt.Request) (func() error, error) {
	n.mu.RLock()
	host, identities := n.host, n.identities
	n.mu.RUnlock()
	if host == nil || identities == nil {
		return nil, nativeUnavailable()
	}
	policy, err := identities.NativePolicy(req.Platform, req.AgentID)
	if err != nil {
		return nil, nativeUnavailable()
	}
	if policy == nil {
		return nil, nil
	}
	subject := nativeRequestSubject(req)
	call, err := host.Bind(subject, req.Tool, req.ToolCallID, req.Params)
	if err != nil {
		return nil, nativeUnavailable()
	}
	return func() error { return host.Finish(subject, req.ToolCallID, call.RequestBinding) }, nil
}
func (s *Server) nativeHostEvent(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	fail := func(status int) { writeJSON(w, status, map[string]string{"error": "native_host_unavailable"}) }
	n := s.d.NativeRuntime
	if n == nil || r.Header.Get("Origin") != "" || len(r.Header.Values("Authorization")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+n.connection.Credential)) != 1 {
		fail(401)
		return
	}
	if r.Method != http.MethodPost {
		fail(405)
		return
	}
	if n.checkConnection() != nil {
		fail(503)
		return
	}
	n.mu.RLock()
	host := n.host
	n.mu.RUnlock()
	if host == nil {
		fail(503)
		return
	}
	var body struct {
		SchemaVersion string          `json:"schema_version"`
		Subject       json.RawMessage `json:"subject"`
		Event         json.RawMessage `json:"event"`
	}
	if !readStrictRequestLimit(w, r, &body, "native_host_invalid", 65536, "schema_version", "subject", "event") {
		return
	}
	if body.SchemaVersion != "native-host-publish/v1" || !exactJSONObject(body.Subject, "platform", "instance_id", "agent_id", "session_id", "task_id") {
		fail(400)
		return
	}
	var subject skillcontext.Subject
	var fields map[string]json.RawMessage
	var kind string
	if json.Unmarshal(body.Subject, &subject) != nil || json.Unmarshal(body.Event, &fields) != nil || json.Unmarshal(fields["kind"], &kind) != nil {
		fail(400)
		return
	}
	schemas := map[string][]string{"task_begin": {"kind", "artifact_sha256"}, "skill_source": {"kind", "load_id", "parent_load_id", "source"}, "call_prepare": {"kind", "tool", "tool_call_id", "request_binding", "load_id"}, "call_finish": {"kind", "tool_call_id", "request_binding"}, "task_end": {"kind"}}
	keys, ok := schemas[kind]
	if !ok || !exactJSONObject(body.Event, keys...) {
		fail(400)
		return
	}
	text := func(key string) string {
		var v string
		if json.Unmarshal(fields[key], &v) != nil {
			return ""
		}
		return v
	}
	// Empty string is meaningful for load ancestry only; reject other JSON types
	// before projecting them into those empty strings.
	for key, raw := range fields {
		if key != "source" {
			var value string
			if json.Unmarshal(raw, &value) != nil {
				fail(400)
				return
			}
		}
	}
	var err error
	switch kind {
	case "task_begin":
		err = host.Begin(subject, text("artifact_sha256"))
	case "skill_source":
		var source skillcontext.NativeSource
		var sourceFields map[string]json.RawMessage
		raw := fields["source"]
		if !exactJSONObject(raw, "schema_version", "skill_file", "content_file", "text_sha256", "decoding", "cache_hit") || json.Unmarshal(raw, &sourceFields) != nil || !exactJSONObject(sourceFields["skill_file"], "path_sha256", "sha256", "bytes") || !exactJSONObject(sourceFields["content_file"], "path_sha256", "sha256", "bytes") || json.Unmarshal(raw, &source) != nil {
			fail(400)
			return
		}
		_, err = host.Load(subject, text("load_id"), text("parent_load_id"), source)
	case "call_prepare":
		err = host.Prepare(subject, text("tool"), text("tool_call_id"), text("request_binding"), text("load_id"))
	case "call_finish":
		err = host.Finish(subject, text("tool_call_id"), text("request_binding"))
	case "task_end":
		err = host.End(subject)
	}
	if err != nil {
		fail(409)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "native-host-published/v1", "accepted": true})
}

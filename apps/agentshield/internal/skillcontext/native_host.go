package skillcontext

import (
	"sync"
	"time"
)

// NativeSource is metadata produced by the actual native reader. ResolveSource
// must independently validate its protected installation mapping and bytes.
type NativeSourceFile struct {
	PathSHA256 string `json:"path_sha256"`
	SHA256     string `json:"sha256"`
	Bytes      int64  `json:"bytes"`
}
type NativeSource struct {
	SchemaVersion string           `json:"schema_version"`
	SkillFile     NativeSourceFile `json:"skill_file"`
	ContentFile   NativeSourceFile `json:"content_file"`
	TextSHA256    string           `json:"text_sha256"`
	Decoding      string           `json:"decoding"`
	CacheHit      bool             `json:"cache_hit"`
}

func (s NativeSource) valid() bool {
	for _, f := range []NativeSourceFile{s.SkillFile, s.ContentFile} {
		if !hex64Pattern.MatchString(f.PathSHA256) || !hex64Pattern.MatchString(f.SHA256) || f.Bytes < 0 || f.Bytes > 1<<20 {
			return false
		}
	}
	return s.SchemaVersion == "native-skill-source/v1" && s.Decoding == "utf-8-sig-replace-universal-newlines/v1" && hex64Pattern.MatchString(s.TextSHA256)
}

type NativeHostDeps struct {
	InvocationDeps
	// Both callbacks are mandatory trusted-host checks, not caller claims.
	VerifyRuntime func(Subject, string) (time.Time, error)
	ResolveSource func(Subject, NativeSource) (InstallRef, error)
}

type hostLoad struct {
	install InstallRef
	loader  NativeLoadRef
	parent  *ParentRef
	context *ParentRef
	main    NativeSourceFile
}
type hostCall struct {
	tool, id, binding, load  string
	context                  *ParentRef
	bindingStarted, finished bool
}
type hostTask struct {
	artifact         string
	until            time.Time
	failed, ended    bool
	load, activeCall string
	loads            map[string]hostLoad
	calls            map[string]hostCall
	sources          map[string]NativeSource
}

// NativeHostBridge joins authenticated host facts to the signed stores. It
// contains no permission rules and cannot authenticate transport by itself.
// All mutation methods are exclusively for the trusted publisher. Ordinary
// runtime requests may only supply parameters to Bind after separate auth.
type NativeHostBridge struct {
	op       sync.Mutex
	mu       sync.RWMutex
	deps     NativeHostDeps
	tasks    map[Subject]*hostTask
	sessions map[Subject]string
	contexts *InvocationStore
	calls    *NativeCallStore
}

func OpenNativeHost(dir string, deps NativeHostDeps) (*NativeHostBridge, error) {
	if deps.VerifyRuntime == nil || deps.ResolveSource == nil {
		return nil, invalid("native_host_unavailable")
	}
	if deps.Now == nil {
		deps.Now = func() time.Time { return time.Now().UTC() }
	}
	h := &NativeHostBridge{deps: deps, tasks: map[Subject]*hostTask{}, sessions: map[Subject]string{}}
	deps.InvocationDeps.ValidateLoad = h.validateLoad
	var err error
	h.contexts, err = OpenInvocations(dir, deps.InvocationDeps)
	if err != nil {
		return nil, err
	}
	h.calls, err = OpenNativeCalls(h.contexts, CallDeps{ValidateSession: h.validateSession, ValidateCall: h.validateCall})
	if err != nil {
		return nil, err
	}
	return h, nil
}
func (h *NativeHostBridge) Calls() *NativeCallStore    { return h.calls }
func (h *NativeHostBridge) Contexts() *InvocationStore { return h.contexts }
func copyParent(p *ParentRef) *ParentRef {
	if p == nil {
		return nil
	}
	v := *p
	return &v
}
func equalParent(a, b *ParentRef) bool {
	return a == nil && b == nil || a != nil && b != nil && *a == *b
}
func hostError() error { return invalid("native_host_unavailable") }
func (h *NativeHostBridge) poison(subject Subject) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if t := h.tasks[subject]; t != nil {
		t.failed = true
	}
}
func (h *NativeHostBridge) live(subject Subject) (string, time.Time, error) {
	h.mu.RLock()
	t := h.tasks[subject]
	if t == nil || t.failed || t.ended || !h.deps.Now().Before(t.until) {
		h.mu.RUnlock()
		return "", time.Time{}, hostError()
	}
	artifact, until := t.artifact, t.until
	h.mu.RUnlock()
	lease, err := h.deps.VerifyRuntime(subject, artifact)
	if err != nil || !h.deps.Now().Before(lease) {
		h.poison(subject)
		return "", time.Time{}, hostError()
	}
	h.mu.RLock()
	stopped := t.failed || t.ended || !h.deps.Now().Before(t.until)
	h.mu.RUnlock()
	if stopped {
		return "", time.Time{}, hostError()
	}
	if lease.Before(until) {
		until = lease
	}
	return artifact, until, nil
}
func (h *NativeHostBridge) Begin(subject Subject, artifact string) (err error) {
	h.op.Lock()
	defer h.op.Unlock()
	defer func() {
		if err != nil {
			h.poison(subject)
		}
	}()
	if !validNativeSubject(subject, true) || subject.Platform != "hermes" || !hex64Pattern.MatchString(artifact) {
		return hostError()
	}
	until, err := h.deps.VerifyRuntime(subject, artifact)
	if err != nil || !h.deps.Now().Before(until) {
		return hostError()
	}
	if cap := h.deps.Now().Add(InvocationMaxTTL); cap.Before(until) {
		until = cap
	}
	h.mu.Lock()
	previous, exists := h.sessions[sessionSubject(subject)]
	if h.tasks[subject] != nil || len(h.tasks) >= 4096 || (exists && previous != artifact) || (!exists && len(h.sessions) >= maxNativeSessions) {
		h.mu.Unlock()
		return hostError()
	}
	h.tasks[subject] = &hostTask{artifact: artifact, until: until, loads: map[string]hostLoad{}, calls: map[string]hostCall{}, sources: map[string]NativeSource{}}
	h.sessions[sessionSubject(subject)] = artifact
	h.mu.Unlock()
	if h.deps.Audit("native_host_task_begin", nativeID("ntask-", nativeSubject(subject))) != nil {
		return hostError()
	}
	_, err = h.calls.RegisterSession(NativeSessionRequest{InstanceID: subject.InstanceID, SessionID: subject.SessionID, RuntimeArtifactSHA256: artifact, TTL: InvocationMaxTTL})
	return err
}
func (h *NativeHostBridge) validateSession(s NativeSession) (time.Time, error) {
	h.mu.RLock()
	artifact, ok := h.sessions[s.Subject]
	h.mu.RUnlock()
	if !ok || artifact != s.RuntimeArtifactSHA256 {
		return time.Time{}, hostError()
	}
	return h.deps.VerifyRuntime(s.Subject, artifact)
}
func (h *NativeHostBridge) validateLoad(subject Subject, install InstallRef, loader NativeLoadRef, parent *ParentRef) (time.Time, error) {
	artifact, until, err := h.live(subject)
	if err != nil {
		return time.Time{}, err
	}
	h.mu.RLock()
	t := h.tasks[subject]
	load, ok := t.loads[loader.LoadID]
	stopped := t.failed || t.ended || !h.deps.Now().Before(t.until)
	h.mu.RUnlock()
	if stopped || !ok || artifact != loader.RuntimeArtifactSHA256 || load.install != install || load.loader != loader || !equalParent(load.parent, parent) {
		return time.Time{}, hostError()
	}
	return until, nil
}
func (h *NativeHostBridge) Load(subject Subject, id, parentID string, source NativeSource) (ref *ParentRef, err error) {
	h.op.Lock()
	defer h.op.Unlock()
	defer func() {
		if err != nil {
			h.poison(subject)
		}
	}()
	artifact, _, err := h.live(subject)
	if err != nil || !source.valid() || !loadIDPattern.MatchString(id) {
		return nil, hostError()
	}
	install, err := h.deps.ResolveSource(subject, source)
	if err != nil {
		return nil, hostError()
	}
	if _, _, err = h.live(subject); err != nil {
		return nil, err
	}
	observed := source
	observed.CacheHit = false
	h.mu.Lock()
	task := h.tasks[subject]
	prior, seen := task.sources[source.ContentFile.PathSHA256]
	if (seen && prior != observed) || (source.CacheHit && !seen) || (!seen && len(task.sources) >= 256) {
		h.mu.Unlock()
		return nil, hostError()
	}
	task.sources[source.ContentFile.PathSHA256] = observed
	h.mu.Unlock()
	h.mu.RLock()
	t := h.tasks[subject]
	current := t.load
	old, exists := t.loads[id]
	parent := copyParent(t.loads[current].context)
	count := len(t.loads)
	h.mu.RUnlock()
	if exists {
		if id != current || parentID != "" || old.install != install || old.main != source.SkillFile || old.context == nil {
			return nil, hostError()
		}
		if _, err = h.contexts.Verify(old.context.ContextID, subject); err != nil {
			return nil, err
		}
		return copyParent(old.context), nil
	}
	if parentID != current || count >= 256 {
		return nil, hostError()
	}
	load := hostLoad{install: install, loader: NativeLoadRef{LoadID: id, SkillFileSHA256: source.SkillFile.SHA256, RuntimeArtifactSHA256: artifact}, parent: parent, main: source.SkillFile}
	h.mu.Lock()
	h.tasks[subject].loads[id] = load
	h.mu.Unlock()
	c, err := h.contexts.Issue(InvocationRequest{InstanceID: subject.InstanceID, SessionID: subject.SessionID, TaskID: subject.TaskID, InstallID: install.InstallID, Loader: load.loader, Parent: copyParent(parent), TTL: InvocationMaxTTL})
	if err != nil || c.Install != install {
		return nil, hostError()
	}
	load.context = &ParentRef{ContextID: c.ContextID, Signature: c.Signature}
	h.mu.Lock()
	t = h.tasks[subject]
	t.loads[id] = load
	t.load = id
	h.mu.Unlock()
	return copyParent(load.context), nil
}

// Prepare has no raw parameters or caller-selected Context/NoSkill flag.
func (h *NativeHostBridge) Prepare(subject Subject, tool, id, binding, loadID string) (err error) {
	h.op.Lock()
	defer h.op.Unlock()
	defer func() {
		if err != nil {
			h.poison(subject)
		}
	}()
	if _, _, err = h.live(subject); err != nil {
		return err
	}
	if !textValid(tool, 128) || !textValid(id, 256) || !hex64Pattern.MatchString(binding) {
		return hostError()
	}
	h.mu.Lock()
	t := h.tasks[subject]
	_, duplicate := t.calls[id]
	if duplicate || t.activeCall != "" || len(t.calls) >= maxNativeCalls || loadID != t.load {
		h.mu.Unlock()
		return hostError()
	}
	c := hostCall{tool: tool, id: id, binding: binding, load: loadID, context: copyParent(t.loads[loadID].context)}
	if loadID != "" && c.context == nil {
		h.mu.Unlock()
		return hostError()
	}
	t.calls[id] = c
	t.activeCall = id
	h.mu.Unlock()
	if h.deps.Audit("native_host_call_prepare", nativeCallID(subject, id)) != nil {
		return hostError()
	}
	return nil
}
func (h *NativeHostBridge) validateCall(c NativeCall) (time.Time, error) {
	_, until, err := h.live(c.Subject)
	if err != nil {
		return time.Time{}, err
	}
	h.mu.RLock()
	t := h.tasks[c.Subject]
	call, ok := t.calls[c.ToolCallID]
	valid := !t.failed && !t.ended && h.deps.Now().Before(t.until) && ok && !call.finished && call.bindingStarted && t.activeCall == call.id && call.tool == c.Tool && call.binding == c.RequestBinding && call.load == t.load && equalParent(call.context, c.Context) && c.NoSkill == (call.load == "")
	h.mu.RUnlock()
	if !valid {
		return time.Time{}, hostError()
	}
	return until, nil
}
func (h *NativeHostBridge) Bind(subject Subject, tool, id string, params map[string]any) (call *NativeCall, err error) {
	h.op.Lock()
	defer h.op.Unlock()
	defer func() {
		if err != nil {
			h.poison(subject)
		}
	}()
	if _, _, err = h.live(subject); err != nil {
		return nil, err
	}
	req := NativeCallRequest{Subject: subject, Tool: tool, ToolCallID: id, Params: params, TTL: NativeCallMaxTTL}
	binding, err := nativeRequestBinding(req)
	if err != nil {
		return nil, err
	}
	h.mu.Lock()
	t := h.tasks[subject]
	c, ok := t.calls[id]
	if !ok || c.finished || c.bindingStarted || t.activeCall != id || c.tool != tool || c.binding != binding || c.load != t.load {
		h.mu.Unlock()
		return nil, hostError()
	}
	c.bindingStarted = true
	t.calls[id] = c
	req.Context = copyParent(c.context)
	req.NoSkill = c.load == ""
	h.mu.Unlock()
	return h.calls.BindFreshCall(req)
}
func (h *NativeHostBridge) Finish(subject Subject, id, binding string) (err error) {
	h.op.Lock()
	defer h.op.Unlock()
	defer func() {
		if err != nil {
			h.poison(subject)
		}
	}()
	// A single late observation is retained even after End; it never validates
	// an old call or permits another execution.
	h.mu.Lock()
	t := h.tasks[subject]
	if t == nil {
		h.mu.Unlock()
		return hostError()
	}
	c, ok := t.calls[id]
	if !ok || c.finished || !c.bindingStarted || c.binding != binding || t.activeCall != id {
		h.mu.Unlock()
		return hostError()
	}
	c.finished = true
	t.calls[id] = c
	t.activeCall = ""
	h.mu.Unlock()
	if h.deps.Audit("native_host_call_finish", nativeCallID(subject, id)) != nil {
		return hostError()
	}
	return nil
}
func (h *NativeHostBridge) End(subject Subject) error {
	// Invalidate without waiting for an outstanding publisher operation.
	h.mu.Lock()
	t := h.tasks[subject]
	if t == nil || t.ended {
		h.mu.Unlock()
		return hostError()
	}
	t.ended = true
	h.mu.Unlock()
	if h.deps.Audit("native_host_task_end", nativeID("ntask-", nativeSubject(subject))) != nil {
		return hostError()
	}
	return nil
}

package runtimecheck

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

var (
	errModelScope       = errors.New("runtime_check_model_scope_changed")
	errModelUnsupported = errors.New("runtime_check_model_scope_unsupported")
	errManagedConflict  = errors.New("runtime_check_managed_policy_conflict")
)

var syntheticAuxTasks = []string{
	"vision", "compression", "skills_hub", "approval", "review", "mcp", "title_generation",
	"memory_query_rewrite", "tts_audio_tags", "triage_specifier", "kanban_decomposer",
	"profile_describer", "goal_judge", "curator", "monitor", "background_review", "moa_reference", "moa_aggregator",
}

// A source pin contains no configuration values. Absent paths are pins too.
type modelSource struct {
	path string
	info os.FileInfo
	hash [32]byte
}

func modelSourceRead(path string, optional bool) (modelSource, []byte, error) {
	s := modelSource{path: path}
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) && optional {
		return s, nil, nil
	}
	if err != nil || info.Mode()&os.ModeSymlink != 0 {
		return s, nil, errModelScope
	}
	s.info = info
	if info.IsDir() {
		return s, nil, nil
	}
	if !info.Mode().IsRegular() || info.Size() > 1<<20 {
		return s, nil, errModelScope
	}
	f, err := os.Open(path)
	if err != nil {
		return s, nil, errModelScope
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return s, nil, errModelScope
	}
	raw, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	after, statErr := os.Lstat(path)
	if err != nil || statErr != nil || len(raw) > 1<<20 || !os.SameFile(opened, after) || after.Size() != int64(len(raw)) {
		return s, nil, errModelScope
	}
	s.hash = sha256.Sum256(raw)
	return s, raw, nil
}

func (s modelSource) verify() error {
	if s.info == nil {
		// An absent environment file is never a configuration document to read.
		// Appearance or an indeterminate result rejects without opening it.
		if _, err := os.Lstat(s.path); errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return errModelScope
	}
	now, _, err := modelSourceRead(s.path, s.info == nil)
	if err != nil || (s.info == nil) != (now.info == nil) {
		return errModelScope
	}
	if s.info != nil && (!os.SameFile(s.info, now.info) || s.hash != now.hash) {
		return errModelScope
	}
	return nil
}

type syntheticModelScope struct {
	dir, provider, model string
	raw                  []byte
	sources              []modelSource
}

// The managed configuration is a final native overlay, not a replacement
// instance. Its source profile, CLI, SIQ plugin and Authority remain unchanged.
func prepareSyntheticModelScope(target adapterinstall.RuntimeTarget, materials, endpoint, id string) (*syntheticModelScope, error) {
	installation, err := inspectSyntheticInstallation(target.NativeCLI)
	if err != nil {
		return nil, err
	}
	s, err := prepareSyntheticModelScopeWithParser(target, materials, endpoint, id, adapterinstall.ParseHermesConfigForRuntimeCheck)
	if err != nil {
		return nil, err
	}
	s.sources = append(s.sources, installation...)
	return s, s.verify()
}

func prepareSyntheticModelScopeWithParser(target adapterinstall.RuntimeTarget, materials, endpoint, id string, parse func(string, []byte) (map[string]any, error)) (*syntheticModelScope, error) {
	s := &syntheticModelScope{dir: filepath.Join(materials, "managed"), provider: "custom:siq-check-" + id, model: "siq-check-" + id}
	profile, raw, err := modelSourceRead(filepath.Join(target.ProfilePath, "config.yaml"), false)
	if err != nil || profile.info.IsDir() {
		return nil, errModelScope
	}
	s.sources = append(s.sources, profile)
	// Hermes sanitizes dotenv before python-dotenv checks its disable flag and
	// hydrates external secrets separately. Do not read or rewrite these files.
	for _, name := range []string{".env", ".op.env"} {
		path := filepath.Join(target.ProfilePath, name)
		if _, e := os.Lstat(path); !errors.Is(e, os.ErrNotExist) {
			return nil, errModelUnsupported
		}
		s.sources = append(s.sources, modelSource{path: path})
	}
	profileDoc, err := parse(target.NativeCLI, raw)
	if err != nil {
		return nil, errModelUnsupported
	}
	// Secret-source bootstrap reads raw profile facts before managed overlay.
	if err := supportedModelSecrets(profileDoc); err != nil {
		return nil, err
	}
	managedDoc := map[string]any{}
	managedPath := strings.TrimSpace(os.Getenv("HERMES_MANAGED_DIR"))
	if managedPath == "" {
		managedPath = filepath.FromSlash("/etc/hermes")
		if runtime.GOOS == "windows" {
			managedPath = filepath.VolumeName(materials) + managedPath
		}
	}
	if !filepath.IsAbs(managedPath) {
		return nil, errModelUnsupported
	}
	managed, _, err := modelSourceRead(managedPath, true)
	if err != nil || (managed.info != nil && !managed.info.IsDir()) {
		return nil, errModelUnsupported
	}
	s.sources = append(s.sources, managed)
	if managed.info != nil {
		resolved, e := filepath.EvalSymlinks(managedPath)
		if e != nil || !sameModelScopePath(resolved, managedPath) {
			return nil, errModelUnsupported
		}
		envPath := filepath.Join(managedPath, ".env")
		if _, e := os.Lstat(envPath); !errors.Is(e, os.ErrNotExist) {
			return nil, errModelUnsupported
		}
		s.sources = append(s.sources, modelSource{path: envPath})
		pin, raw, e := modelSourceRead(filepath.Join(managedPath, "config.yaml"), true)
		if e != nil || (pin.info != nil && pin.info.IsDir()) || bytes.Contains(raw, []byte("${")) {
			return nil, errModelUnsupported
		}
		s.sources = append(s.sources, pin)
		if pin.info != nil {
			managedDoc, e = parse(target.NativeCLI, raw)
			if e != nil {
				return nil, errModelUnsupported
			}
		}
	}
	effective := mergeModelConfig(profileDoc, managedDoc)
	if err := supportedModelConfig(effective); err != nil {
		return nil, err
	}
	routing, err := syntheticRouting(endpoint, id)
	if err != nil {
		return nil, err
	}
	// Existing administrator pins have priority: conflicting routes are an
	// explicit unsupported case, never silently discarded policy.
	if err := compatibleManagedPins(managedDoc, routing); err != nil {
		return nil, err
	}
	s.raw, err = json.Marshal(mergeModelConfig(managedDoc, routing))
	if err != nil || len(s.raw) > 1<<20 {
		return nil, errModelUnsupported
	}
	if err := s.verifySources(); err != nil {
		return nil, err
	}
	if _, e := os.Lstat(s.dir); !errors.Is(e, os.ErrNotExist) {
		return nil, errModelScope
	}
	if err := statefs.MkdirAllPrivate(s.dir); err != nil {
		return nil, errModelScope
	}
	f, err := statefs.CreatePrivate(filepath.Join(s.dir, "config.yaml"))
	if err != nil {
		return nil, errModelScope
	}
	_, writeErr := f.Write(s.raw)
	syncErr := f.Sync()
	closeErr := f.Close()
	if writeErr != nil || syncErr != nil || closeErr != nil {
		return nil, errModelScope
	}
	for _, path := range []string{s.dir, filepath.Join(s.dir, "config.yaml")} {
		pin, _, e := modelSourceRead(path, false)
		if e != nil {
			return nil, errModelScope
		}
		s.sources = append(s.sources, pin)
	}
	return s, s.verify()
}

func sameModelScopePath(a, b string) bool {
	if runtime.GOOS == "windows" {
		return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

func (s *syntheticModelScope) verifySources() error {
	for _, pin := range s.sources {
		if err := pin.verify(); err != nil {
			return err
		}
	}
	return nil
}

func (s *syntheticModelScope) verify() error {
	if err := s.verifySources(); err != nil {
		return err
	}
	if statefs.CheckPrivateDir(s.dir) != nil {
		return errModelScope
	}
	raw, err := statefs.ReadPrivateFile(filepath.Join(s.dir, "config.yaml"), 1<<20)
	if err != nil || !bytes.Equal(raw, s.raw) {
		return errModelScope
	}
	return nil
}

// Keep the owned overlay and ancestors stable for this single synchronous
// native invocation. No authorization result is reused across HTTP requests.
func (s *syntheticModelScope) pin() (*privatefs.ReadSnapshot, error) {
	if err := s.verify(); err != nil {
		return nil, err
	}
	pin, err := privatefs.OpenReadSnapshot(s.dir)
	if err != nil {
		return nil, errModelScope
	}
	raw, err := pin.ReadFile("config.yaml", 1<<20)
	if err != nil || !bytes.Equal(raw, s.raw) || pin.Verify() != nil || s.verify() != nil {
		_ = pin.Close()
		return nil, errModelScope
	}
	return pin, nil
}

func syntheticRouting(endpoint, id string) (map[string]any, error) {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "/"+id+"/v1" {
		return nil, errModelScope
	}
	if _, _, err := net.SplitHostPort(u.Host); err != nil || len(id) != 48 || strings.Trim(id, "0123456789abcdef") != "" {
		return nil, errModelScope
	}
	name, model := "siq-check-"+id, "siq-check-"+id
	provider := "custom:" + name
	aux := map[string]any{}
	for _, task := range syntheticAuxTasks {
		cfg := map[string]any{"provider": provider, "model": model, "base_url": endpoint, "api_key": "siq-runtime-check-placeholder", "api_mode": "chat_completions", "fallback_chain": []any{}}
		if task == "title_generation" || task == "background_review" {
			cfg["enabled"] = false
		}
		aux[task] = cfg
	}
	return map[string]any{
		"model":              map[string]any{"provider": provider, "default": model, "base_url": endpoint, "api_mode": "chat_completions"},
		"providers":          map[string]any{name: map[string]any{"base_url": endpoint, "api_key": "siq-runtime-check-placeholder", "default_model": model, "api_mode": "chat_completions", "transport": "chat_completions", "enabled": true}},
		"fallback_providers": []any{}, "fallback_model": []any{}, "auxiliary": aux,
		"compression": map[string]any{"enabled": false}, "nous": map[string]any{"guest": false},
	}, nil
}

func supportedModelConfig(doc map[string]any) error {
	plugins, ok := doc["plugins"].(map[string]any)
	if !ok {
		return errModelUnsupported
	}
	enabled, ok := plugins["enabled"].([]any)
	if !ok || len(enabled) != 1 || enabled[0] != product.PluginDir() {
		return errModelUnsupported
	}
	if disabled, exists := plugins["disabled"]; exists {
		list, ok := disabled.([]any)
		if !ok {
			return errModelUnsupported
		}
		for _, item := range list {
			if item == product.PluginDir() {
				return errModelUnsupported
			}
		}
	}
	if entries, exists := plugins["entries"]; exists {
		list, ok := entries.(map[string]any)
		if !ok {
			return errModelUnsupported
		}
		if entry, exists := list[product.PluginDir()]; exists {
			cfg, ok := entry.(map[string]any)
			if !ok {
				return errModelUnsupported
			}
			if flag, exists := cfg["allow_tool_override"]; exists && flag != false {
				return errModelUnsupported
			}
		}
	}
	// Some native versions try the profile's auto+base_url before rejecting an
	// unknown explicit provider. That would defeat a missing-overlay diagnostic.
	provider, base := doc["provider"], doc["base_url"]
	if cfg, ok := doc["model"].(map[string]any); ok {
		if v, ok := cfg["provider"]; ok {
			provider = v
		}
		if v, ok := cfg["base_url"]; ok {
			base = v
		}
	}
	if base != nil && base != "" && (provider == nil || provider == "" || provider == "auto") {
		return errModelUnsupported
	}
	// Additional native plugin/provider code and arbitrary secret hydrators are
	// outside the standard route proof. Do not disable them silently.
	if err := supportedModelSecrets(doc); err != nil {
		return err
	}
	for section, key := range map[string]string{"memory": "provider", "context": "engine"} {
		if cfg, ok := doc[section].(map[string]any); ok {
			if value, exists := cfg[key]; exists && value != "" && !(section == "context" && value == "compressor") {
				return errModelUnsupported
			}
		} else if doc[section] != nil {
			return errModelUnsupported
		}
	}
	if aux, ok := doc["auxiliary"].(map[string]any); ok {
		allowed := map[string]bool{"transient_retries": true, "free_only": true, "openrouter_model": true, "stream_only_base_urls": true}
		for _, task := range syntheticAuxTasks {
			allowed[task] = true
		}
		for key := range aux {
			if !allowed[key] {
				return errModelUnsupported
			}
		}
	} else if doc["auxiliary"] != nil {
		return errModelUnsupported
	}
	return nil
}

func supportedModelSecrets(doc map[string]any) error {
	if sources, ok := doc["secrets"].(map[string]any); ok {
		for _, value := range sources {
			if cfg, ok := value.(map[string]any); !ok || cfg["enabled"] != false {
				return errModelUnsupported
			}
		}
	} else if doc["secrets"] != nil {
		return errModelUnsupported
	}
	return nil
}

func mergeModelConfig(base, overlay map[string]any) map[string]any {
	out := make(map[string]any, len(base)+len(overlay))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range overlay {
		b, bok := out[k].(map[string]any)
		o, ook := v.(map[string]any)
		if bok && ook {
			out[k] = mergeModelConfig(b, o)
		} else {
			out[k] = v
		}
	}
	return out
}

func compatibleManagedPins(pins, overlay map[string]any) error {
	for key, wanted := range overlay {
		prior, exists := pins[key]
		if !exists {
			continue
		}
		p, pok := prior.(map[string]any)
		w, wok := wanted.(map[string]any)
		if pok && wok {
			if err := compatibleManagedPins(p, w); err != nil {
				return err
			}
			continue
		}
		if !reflect.DeepEqual(prior, wanted) {
			return errManagedConflict
		}
	}
	return nil
}

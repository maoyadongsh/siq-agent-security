// Package modelconfig reads explicit model declarations, never effective runtime routes.
package modelconfig

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"

	"siq-agent-security/apps/agentshield/internal/privatefs"
)

var invalid = errors.New("model_configuration_unavailable")
var processKey = func() []byte {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic("model configuration key unavailable")
	}
	return b
}()
var safeLabel = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_./:+ -]{0,255}$`)
var envName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,127}$`)

type Source struct {
	ID, Platform, Name, Root string
	secretProviders          map[string]any
}
type Item struct {
	ID          string `json:"id"`
	InstanceID  string `json:"instance_id"`
	Platform    string `json:"platform"`
	Name        string `json:"instance_name"`
	Role        string `json:"role"`
	Model       string `json:"model"`
	Provider    string `json:"provider"`
	Endpoint    string `json:"endpoint_display"`
	Credential  string `json:"credential"`
	State       string `json:"state"`
	CanCheck    bool   `json:"can_check"`
	Fingerprint string `json:"fingerprint"`
}

// Target is private: never marshal or log this value, its source or its key.
type Target struct {
	Item     Item
	URL, Key string
}

func readFile(root, name string) ([]byte, error) {
	return readBoundedFile(root, name, false)
}
func readBoundedFile(root, name string, private bool) ([]byte, error) {
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil || filepath.Clean(resolved) != filepath.Clean(root) {
		return nil, invalid
	}
	dir, err := os.Lstat(root)
	if err != nil || !dir.IsDir() {
		return nil, invalid
	}
	path := filepath.Join(root, name)
	before, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !before.Mode().IsRegular() || before.Size() > 1<<20 {
		return nil, invalid
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, invalid
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(before, opened) {
		return nil, invalid
	}
	if private && (privatefs.CheckFile(f) != nil || runtime.GOOS != "windows" && opened.Mode().Perm()&0077 != 0) {
		return nil, invalid
	}
	raw, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 {
		return nil, invalid
	}
	after, err := os.Lstat(path)
	if err != nil || !os.SameFile(opened, after) || opened.Size() != after.Size() || !opened.ModTime().Equal(after.ModTime()) {
		return nil, invalid
	}
	dirAfter, err := os.Lstat(root)
	if err != nil || !os.SameFile(dir, dirAfter) {
		return nil, invalid
	}
	return raw, nil
}

// scalar accepts only unambiguous literal strings, never expansion or YAML objects.
func scalar(s string) (string, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return "", nil
	}
	if strings.HasPrefix(s, `"`) {
		var v string
		if json.Unmarshal([]byte(s), &v) != nil {
			return "", invalid
		}
		return v, nil
	}
	if strings.HasPrefix(s, "'") {
		if len(s) < 2 || !strings.HasSuffix(s, "'") {
			return "", invalid
		}
		return strings.ReplaceAll(s[1:len(s)-1], "''", "'"), nil
	}
	if i := strings.Index(s, " #"); i >= 0 {
		s = strings.TrimSpace(s[:i])
	}
	if strings.ContainsAny(s, "{}[]&*!|>\t\r\n") || strings.Contains(s, "${") || strings.Contains(s, "$(") || strings.Contains(s, ": ") {
		return "", invalid
	}
	switch strings.ToLower(s) {
	case "null", "~", "true", "false", "yes", "no", "on", "off":
		return "", invalid
	}
	return s, nil
}

// Only the direct model map is projected. Duplicate root keys, merges, aliases
// and nested lookalike fields cannot override the projection silently.
func hermesModel(raw []byte) (map[string]any, error) {
	if bytes.IndexByte(raw, 0) >= 0 {
		return nil, invalid
	}
	out := map[string]any{}
	roots := map[string]bool{}
	seen := map[string]bool{}
	in := false
	childIndent := -1
	wanted := map[string]bool{"default": true, "provider": true, "base_url": true, "api_key": true, "key_env": true, "api_mode": true}
	for _, line := range strings.Split(string(raw), "\n") {
		t := strings.TrimSpace(line)
		if t == "" || strings.HasPrefix(t, "#") {
			continue
		}
		if strings.Contains(line, "\t") || t == "---" || t == "..." || strings.HasPrefix(t, "<<:") {
			return nil, invalid
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		// PyYAML commonly emits root-level sequence entries without extra
		// indentation. They belong to the preceding non-model field.
		if indent == 0 && strings.HasPrefix(t, "- ") {
			if in || len(roots) == 0 {
				return nil, invalid
			}
			continue
		}
		key, rest, ok := strings.Cut(t, ":")
		if indent == 0 {
			if !ok || roots[key] || strings.ContainsAny(key, "\"'{}[]&*!") {
				return nil, invalid
			}
			roots[key] = true
			in = key == "model"
			childIndent = -1
			if in && strings.TrimSpace(rest) != "" {
				return nil, invalid
			}
			continue
		}
		if !in {
			continue
		}
		if !ok {
			return nil, invalid
		}
		if childIndent < 0 {
			childIndent = indent
		}
		if indent != childIndent {
			return nil, invalid
		}
		if seen[key] || strings.ContainsAny(key, "\"'{}[]&*!") {
			return nil, invalid
		}
		seen[key] = true
		if wanted[key] {
			v, e := scalar(rest)
			if e != nil {
				return nil, e
			}
			out[key] = v
		}
	}
	return out, nil
}

func mapAt(m map[string]any, k string) map[string]any { v, _ := m[k].(map[string]any); return v }
func str(m map[string]any, k string) string           { v, _ := m[k].(string); return v }
func digest(parts ...string) string {
	h := hmac.New(sha256.New, processKey)
	for _, p := range parts {
		io.WriteString(h, strconv.Itoa(len(p))+":"+p)
	}
	return hex.EncodeToString(h.Sum(nil))
}

func credential(root string, cfg map[string]any, hermes bool, providers ...map[string]any) (string, string) {
	field := "apiKey"
	if hermes {
		field = "api_key"
	}
	if value, exists := cfg[field]; exists {
		if !hermes {
			if ref, ok := value.(map[string]any); ok {
				if str(ref, "source") == "file" && len(providers) == 1 {
					return fileCredential(ref, providers[0])
				}
				name := str(ref, "id")
				if len(ref) != 3 || str(ref, "source") != "env" || str(ref, "provider") != "default" || !envName.MatchString(name) {
					return "", "unsupported"
				}
				key := os.Getenv(name)
				if key == "" {
					return "", "missing"
				}
				if strings.ContainsAny(key, "\r\n") {
					return "", "unsupported"
				}
				return key, "present"
			}
		}
		key, ok := value.(string)
		if !ok || strings.Contains(key, "${") || strings.ContainsAny(key, "\r\n") {
			return "", "unsupported"
		}
		if key != "" {
			if hermes && str(cfg, "key_env") != "" {
				return "", "unsupported"
			}
			return key, "present"
		}
	}
	name := str(cfg, "key_env")
	if name == "" {
		return "", "none"
	}
	if !hermes || !envName.MatchString(name) {
		return "", "unsupported"
	}
	if key := os.Getenv(name); key != "" && !strings.ContainsAny(key, "\r\n") {
		return key, "present"
	}
	raw, err := readBoundedFile(root, ".env", true)
	if os.IsNotExist(err) {
		return "", "missing"
	}
	if err != nil {
		return "", "unsupported"
	}
	key := ""
	found := false
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		line = strings.TrimPrefix(line, "export ")
		k, v, ok := strings.Cut(line, "=")
		if !ok || strings.TrimSpace(k) != name {
			continue
		}
		if found {
			return "", "unsupported"
		}
		found = true
		key, err = scalar(v)
		if err != nil || strings.ContainsAny(key, "\r\n") || strings.Contains(key, "$") {
			return "", "unsupported"
		}
	}
	if key == "" {
		return "", "missing"
	}
	return key, "present"
}

func build(source Source, raw []byte, role, model, provider string, cfg map[string]any) Target {
	t := Target{Item: Item{InstanceID: source.ID, Platform: source.Platform, Name: source.Name, Role: role, Model: model, Provider: provider, State: "configured"}}
	t.Item.ID = "mc-" + digest(source.ID, role, model, provider)[:32]
	if len(t.Item.Name) > 128 {
		t.Item.Name = "instance"
	}
	if !safeLabel.MatchString(model) {
		t.Item.Model = ""
		t.Item.State = "missing_model"
	}
	if provider != "" && (!safeLabel.MatchString(provider) || len(provider) > 128) {
		t.Item.Provider = ""
		t.Item.State = "unsupported_config"
	}
	base, mode := str(cfg, "baseUrl"), str(cfg, "api")
	if source.Platform == "hermes" {
		base, mode = str(cfg, "base_url"), str(cfg, "api_mode")
	}
	t.Key, t.Item.Credential = credential(source.Root, cfg, source.Platform == "hermes", source.secretProviders)
	u, err := endpoint(base)
	if err != nil && t.Item.State == "configured" {
		t.Item.State = "missing_endpoint"
	} else if err == nil {
		t.URL = u.String()
		t.Item.Endpoint = u.Scheme + "://" + u.Host
	}
	if t.Item.State == "configured" && (source.Platform == "openclaw" && mode != "openai-completions" || source.Platform == "hermes" && mode != "openai_chat" && !(mode == "" && (provider == "custom" || strings.HasPrefix(provider, "custom:")))) {
		t.Item.State = "unsupported_protocol"
	}
	if _, ok := cfg["headers"]; ok {
		t.Item.Credential = "unsupported"
	}
	if value, ok := cfg["authHeader"]; ok && value != true {
		t.Item.Credential = "unsupported"
	}
	if value, ok := cfg["auth"]; ok && value != "api-key" {
		t.Item.Credential = "unsupported"
	}
	if t.Item.State == "configured" && (t.Item.Credential == "missing" || t.Item.Credential == "unsupported") {
		t.Item.State = "credential_unavailable"
	}
	t.Item.CanCheck = t.Item.State == "configured"
	t.Item.Fingerprint = digest(source.ID, string(raw), t.URL, t.Key, t.Item.Credential, role, model, provider)
	return t
}

func Discover(source Source) []Target {
	name := "config.yaml"
	if source.Platform == "openclaw" {
		name = "openclaw.json"
	}
	raw, err := readFile(source.Root, name)
	bad := func(state string) []Target {
		t := build(source, raw, "configured", "", "", nil)
		t.Item.State = state
		t.Item.CanCheck = false
		return []Target{t}
	}
	if err != nil {
		return bad("unreadable_config")
	}
	if source.Platform == "hermes" {
		cfg, e := hermesModel(raw)
		if e != nil {
			return bad("unsupported_config")
		}
		return []Target{build(source, raw, "configured", str(cfg, "default"), str(cfg, "provider"), cfg)}
	}
	var doc map[string]any
	if !uniqueJSON(raw) || json.Unmarshal(raw, &doc) != nil || doc == nil {
		return bad("unsupported_config")
	}
	if _, included := doc["$include"]; included {
		return bad("unsupported_config")
	}
	source.secretProviders = mapAt(mapAt(doc, "secrets"), "providers")
	defaults := mapAt(mapAt(doc, "agents"), "defaults")
	model := mapAt(defaults, "model")
	primary := str(model, "primary")
	if value, ok := defaults["model"].(string); ok {
		primary = value
	}
	choices := []string{primary}
	roles := []string{"primary"}
	if values, ok := model["fallbacks"].([]any); ok {
		if len(values) > 16 {
			return bad("unsupported_config")
		}
		for _, v := range values {
			text, ok := v.(string)
			if !ok {
				return bad("unsupported_config")
			}
			choices = append(choices, text)
			roles = append(roles, "fallback")
		}
	}
	providers := mapAt(mapAt(doc, "models"), "providers")
	result := []Target{}
	seen := map[string]bool{}
	for i, choice := range choices {
		if seen[choice] {
			continue
		}
		seen[choice] = true
		provider, model, _ := strings.Cut(choice, "/")
		cfg := mapAt(providers, provider)
		result = append(result, build(source, raw, roles[i], model, provider, cfg))
	}
	return result
}

// JSON configuration must not contain duplicate keys or trailing documents.
func uniqueJSON(raw []byte) bool {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var walk func(int) bool
	walk = func(depth int) bool {
		if depth > 64 {
			return false
		}
		token, err := d.Token()
		if err != nil {
			return false
		}
		delim, ok := token.(json.Delim)
		if !ok {
			return true
		}
		if delim == '{' {
			seen := map[string]bool{}
			for d.More() {
				k, e := d.Token()
				key, ok := k.(string)
				if e != nil || !ok || seen[key] {
					return false
				}
				seen[key] = true
				if !walk(depth + 1) {
					return false
				}
			}
			end, e := d.Token()
			return e == nil && end == json.Delim('}')
		}
		if delim == '[' {
			for d.More() {
				if !walk(depth + 1) {
					return false
				}
			}
			end, e := d.Token()
			return e == nil && end == json.Delim(']')
		}
		return false
	}
	if !walk(0) {
		return false
	}
	_, err := d.Token()
	return err == io.EOF
}

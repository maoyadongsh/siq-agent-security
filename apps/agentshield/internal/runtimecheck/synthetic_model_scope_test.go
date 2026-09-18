package runtimecheck

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const scopeTestID = "0123456789abcdef0123456789abcdef0123456789abcdef"
const scopeTestURL = "http://127.0.0.1:43210/" + scopeTestID + "/v1"

func scopeTestJSON(_ string, raw []byte) (map[string]any, error) {
	var doc map[string]any
	err := json.Unmarshal(raw, &doc)
	return doc, err
}

func scopeTestFixture(t *testing.T) (adapterinstall.RuntimeTarget, string, string) {
	t.Helper()
	root := t.TempDir()
	profile, materials, managed := filepath.Join(root, "profile"), filepath.Join(root, "materials"), filepath.Join(root, "existing-managed")
	for _, path := range []string{profile, materials} {
		if err := statefs.MkdirAllPrivate(path); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("HERMES_MANAGED_DIR", managed)
	config := `{"plugins":{"enabled":["siq-agent-security"]},"model":{"provider":"paid-fixture","api_mode":"anthropic_messages"},"fallback_providers":[{"provider":"paid-fallback"}],"fallback_model":{"provider":"legacy-paid"},"auxiliary":{"vision":{"provider":"paid-vision","fallback_chain":[{"provider":"paid-aux-fallback"}]}}}`
	if err := os.WriteFile(filepath.Join(profile, "config.yaml"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	return adapterinstall.RuntimeTarget{ProfilePath: profile, NativeCLI: "not-executed"}, materials, managed
}

func TestSyntheticModelScopeOverridesAllStandardRoutes(t *testing.T) {
	target, materials, _ := scopeTestFixture(t)
	original, _ := os.ReadFile(filepath.Join(target.ProfilePath, "config.yaml"))
	s, err := prepareSyntheticModelScopeWithParser(target, materials, scopeTestURL, scopeTestID, scopeTestJSON)
	if err != nil {
		t.Fatal(err)
	}
	var overlay map[string]any
	if err := json.Unmarshal(s.raw, &overlay); err != nil {
		t.Fatal(err)
	}
	profile, _ := scopeTestJSON("", original)
	effective := mergeModelConfig(profile, overlay)
	for _, key := range []string{"fallback_providers", "fallback_model"} {
		if list, ok := effective[key].([]any); !ok || len(list) != 0 {
			t.Fatalf("%s was not cleared", key)
		}
	}
	model := effective["model"].(map[string]any)
	if model["provider"] != s.provider || model["api_mode"] != "chat_completions" || model["base_url"] != scopeTestURL {
		t.Fatal("main route escaped")
	}
	for _, task := range syntheticAuxTasks {
		cfg := effective["auxiliary"].(map[string]any)[task].(map[string]any)
		if cfg["provider"] != s.provider || cfg["base_url"] != scopeTestURL || cfg["api_mode"] != "chat_completions" || len(cfg["fallback_chain"].([]any)) != 0 {
			t.Fatalf("aux route escaped: %s", task)
		}
	}
	if err := s.verify(); err != nil {
		t.Fatal(err)
	}
	after, _ := os.ReadFile(filepath.Join(target.ProfilePath, "config.yaml"))
	if !bytes.Equal(original, after) {
		t.Fatal("actual profile changed")
	}
	if _, err := os.Stat(filepath.Join(materials, "unexpected")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("unexpected material")
	}
}

func TestSyntheticModelScopePreservesManagedPolicyAndRejectsConflict(t *testing.T) {
	for _, conflict := range []bool{false, true} {
		t.Run(map[bool]string{false: "preserve", true: "conflict"}[conflict], func(t *testing.T) {
			target, materials, managed := scopeTestFixture(t)
			if err := statefs.MkdirAllPrivate(managed); err != nil {
				t.Fatal(err)
			}
			pins := map[string]any{"security": map[string]any{"redact_secrets": true}, "network": map[string]any{"allowed_hosts": []any{"127.0.0.1"}}}
			if conflict {
				pins["model"] = map[string]any{"provider": "required-admin-provider"}
			}
			raw, _ := json.Marshal(pins)
			if err := os.WriteFile(filepath.Join(managed, "config.yaml"), raw, 0600); err != nil {
				t.Fatal(err)
			}
			s, err := prepareSyntheticModelScopeWithParser(target, materials, scopeTestURL, scopeTestID, scopeTestJSON)
			if conflict {
				if !errors.Is(err, errManagedConflict) {
					t.Fatal("admin pin silently replaced", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			var got map[string]any
			_ = json.Unmarshal(s.raw, &got)
			for key, want := range pins {
				if !reflect.DeepEqual(got[key], want) {
					t.Fatal("admin policy lost", key)
				}
			}
			if err := os.WriteFile(filepath.Join(managed, "config.yaml"), []byte(`{}`), 0600); err != nil {
				t.Fatal(err)
			}
			if s.verify() == nil {
				t.Fatal("changed source policy accepted")
			}
		})
	}
}

func TestSyntheticModelScopeRejectsUnsupportedInputsBeforeLaunch(t *testing.T) {
	for _, which := range []string{"dotenv", "op-env", "managed-env", "managed-expansion", "unknown-aux", "extra-plugin", "disabled-siq", "override-siq", "auto-endpoint", "secret-source", "memory-plugin", "context-plugin", "parse-error"} {
		t.Run(which, func(t *testing.T) {
			target, materials, managed := scopeTestFixture(t)
			path := filepath.Join(target.ProfilePath, "config.yaml")
			raw, _ := os.ReadFile(path)
			doc, _ := scopeTestJSON("", raw)
			parse := scopeTestJSON
			switch which {
			case "dotenv", "op-env":
				name := ".env"
				if which == "op-env" {
					name = ".op.env"
				}
				if err := os.WriteFile(filepath.Join(target.ProfilePath, name), []byte("SYNTHETIC_ONLY=1"), 0600); err != nil {
					t.Fatal(err)
				}
			case "managed-env", "managed-expansion":
				if err := statefs.MkdirAllPrivate(managed); err != nil {
					t.Fatal(err)
				}
				name, data := ".env", "SYNTHETIC_ONLY=1"
				if which == "managed-expansion" {
					name, data = "config.yaml", `{"security":{"pin":"${UNRESOLVED}"}}`
				}
				if err := os.WriteFile(filepath.Join(managed, name), []byte(data), 0600); err != nil {
					t.Fatal(err)
				}
			case "unknown-aux":
				doc["auxiliary"] = map[string]any{"third_party": map[string]any{}}
			case "extra-plugin":
				doc["plugins"] = map[string]any{"enabled": []any{"siq-agent-security", "other"}}
			case "disabled-siq":
				doc["plugins"] = map[string]any{"enabled": []any{"siq-agent-security"}, "disabled": []any{"siq-agent-security"}}
			case "override-siq":
				doc["plugins"] = map[string]any{"enabled": []any{"siq-agent-security"}, "entries": map[string]any{"siq-agent-security": map[string]any{"allow_tool_override": true}}}
			case "auto-endpoint":
				doc["model"] = map[string]any{"provider": "auto", "base_url": "https://unverified.invalid/v1"}
			case "secret-source":
				doc["secrets"] = map[string]any{"provider": map[string]any{"enabled": true}}
			case "memory-plugin":
				doc["memory"] = map[string]any{"provider": "unknown"}
			case "context-plugin":
				doc["context"] = map[string]any{"engine": "unknown"}
			case "parse-error":
				parse = func(string, []byte) (map[string]any, error) { return nil, errors.New("private input must not escape") }
			}
			updated, _ := json.Marshal(doc)
			if err := os.WriteFile(path, updated, 0600); err != nil {
				t.Fatal(err)
			}
			_, err := prepareSyntheticModelScopeWithParser(target, materials, scopeTestURL, scopeTestID, parse)
			if err == nil || strings.Contains(err.Error(), "private input") {
				t.Fatal("unsafe input accepted or leaked", err)
			}
			if _, err := os.Lstat(filepath.Join(materials, "managed")); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("unsupported input published overlay")
			}
		})
	}
}

func TestSyntheticModelScopeMissingCorruptReplacedAndLateInput(t *testing.T) {
	for _, which := range []string{"missing", "corrupt", "replaced", "directory-replaced", "late-dotenv", "late-managed"} {
		t.Run(which, func(t *testing.T) {
			target, materials, managed := scopeTestFixture(t)
			s, err := prepareSyntheticModelScopeWithParser(target, materials, scopeTestURL, scopeTestID, scopeTestJSON)
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(s.dir, "config.yaml")
			switch which {
			case "missing":
				err = os.Remove(path)
			case "corrupt":
				err = os.WriteFile(path, []byte("broken"), 0600)
			case "replaced":
				if err = os.Rename(path, path+".old"); err == nil {
					err = os.WriteFile(path, s.raw, 0600)
				}
			case "directory-replaced":
				if err = os.Rename(s.dir, s.dir+".old"); err == nil {
					err = statefs.MkdirAllPrivate(s.dir)
				}
				if err == nil {
					err = os.WriteFile(path, s.raw, 0600)
				}
			case "late-dotenv":
				err = os.WriteFile(filepath.Join(target.ProfilePath, ".env"), []byte("SYNTHETIC_ONLY=1"), 0600)
			case "late-managed":
				err = statefs.MkdirAllPrivate(managed)
			}
			if err != nil {
				t.Fatal(err)
			}
			if s.verify() == nil {
				t.Fatal("changed scope accepted")
			}
		})
	}
}

func TestSyntheticModelScopeOnlyExactLoopbackAndModel(t *testing.T) {
	for _, endpoint := range []string{"https://127.0.0.1:42/" + scopeTestID + "/v1", "http://example.invalid:42/" + scopeTestID + "/v1", scopeTestURL + "?next=remote", scopeTestURL + "#x", "http://user@127.0.0.1:42/" + scopeTestID + "/v1"} {
		if _, err := syntheticRouting(endpoint, scopeTestID); err == nil {
			t.Fatal("nonexact endpoint accepted")
		}
	}
	model := &probeModel{prefix: "/" + scopeTestID + "/v1", model: "siq-check-" + scopeTestID}
	for _, request := range []struct {
		path, body string
		want       int
	}{
		{model.prefix + "/responses", `{}`, 404},
		{model.prefix + "/chat/completions", `{"model":"paid-fixture"}`, 400},
		{model.prefix + "/chat/completions", `{"model":"` + model.model + `"}`, 200},
	} {
		w := httptest.NewRecorder()
		model.ServeHTTP(w, httptest.NewRequest(http.MethodPost, request.path, strings.NewReader(request.body)))
		if w.Code != request.want {
			t.Fatal("unexpected synthetic route", w.Code)
		}
	}
}

func TestSyntheticAbsentEnvironmentPinRejectsNewObject(t *testing.T) {
	for _, directory := range []bool{false, true} {
		t.Run(map[bool]string{false: "file", true: "directory"}[directory], func(t *testing.T) {
			path := filepath.Join(t.TempDir(), ".env")
			pin := modelSource{path: path}
			if err := pin.verify(); err != nil {
				t.Fatal(err)
			}
			var err error
			if directory {
				err = os.Mkdir(path, 0700)
			} else {
				err = os.WriteFile(path, []byte("must-not-be-read"), 0000)
			}
			if err != nil {
				t.Fatal(err)
			}
			if !errors.Is(pin.verify(), errModelScope) {
				t.Fatal("new unknown environment object accepted")
			}
		})
	}
}

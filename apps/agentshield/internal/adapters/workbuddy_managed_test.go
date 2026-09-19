package adapters

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

const workBuddyInput = `{"hook_event_name":"PreToolUse","session_id":"host-session","tool_use_id":"host-call","call_id":"host-call","tool_name":"Read","tool_input":{"file_path":"C:\\fixture\\input.txt"}}`

type workBuddyDecider struct {
	requests                             []receipt.Request
	events                               []string
	session                              string
	action                               string
	enrollErr, errorDecide, errorObserve bool
}

func (d *workBuddyDecider) Enroll(session string) error {
	d.events = append(d.events, "enroll")
	d.session = session
	if d.enrollErr {
		return errors.New("enroll unavailable")
	}
	return nil
}
func (d *workBuddyDecider) Decide(req receipt.Request) (*receipt.Decision, error) {
	d.events = append(d.events, "decide")
	d.requests = append(d.requests, req)
	if d.errorDecide {
		return nil, errors.New("down")
	}
	return &receipt.Decision{Action: d.action, Reason: "fixture", Receipt: receipt.Receipt{ReceiptID: "rcp-fixture", ActionID: "act-fixture"}}, nil
}
func (d *workBuddyDecider) Observe(req receipt.Request, _ string) error {
	d.events = append(d.events, "observe")
	d.requests = append(d.requests, req)
	if d.errorObserve {
		return errors.New("down")
	}
	return nil
}

func TestWorkBuddyManagedStrictInputBeforeAuthority(t *testing.T) {
	cases := map[string]string{
		"missing session":     strings.Replace(workBuddyInput, `"session_id":"host-session",`, "", 1),
		"missing call":        strings.Replace(workBuddyInput, `"call_id":"host-call",`, "", 1),
		"empty call":          strings.Replace(workBuddyInput, `"call_id":"host-call"`, `"call_id":""`, 1),
		"call conflict":       strings.Replace(workBuddyInput, `"call_id":"host-call"`, `"call_id":"different"`, 1),
		"duplicate":           strings.Replace(workBuddyInput, `"session_id":`, `"session_id":"same","session_id":`, 1),
		"escaped duplicate":   strings.Replace(workBuddyInput, `"session_id":`, `"session_\u0069d":"same","session_id":`, 1),
		"nested duplicate":    strings.Replace(workBuddyInput, `"file_path":`, `"file_path":"other","file_path":`, 1),
		"alias":               strings.Replace(workBuddyInput, `"session_id"`, `"Session_ID"`, 1),
		"unknown authority":   strings.Replace(workBuddyInput, `"tool_name":`, `"intent_id":"forged","tool_name":`, 1),
		"unknown event":       strings.Replace(workBuddyInput, "PreToolUse", "PermissionRequest", 1),
		"trailing":            workBuddyInput + ` {}`,
		"params null":         strings.Replace(workBuddyInput, `{"file_path":"C:\\fixture\\input.txt"}`, "null", 1),
		"metadata null":       strings.Replace(workBuddyInput, `"tool_name":`, `"cwd":null,"tool_name":`, 1),
		"space ID":            strings.Replace(workBuddyInput, "host-session", " host-session", 1),
		"control ID":          strings.Replace(workBuddyInput, "host-session", `host\nsession`, 1),
		"long ID":             strings.Replace(workBuddyInput, "host-session", strings.Repeat("x", 257), 1),
		"post missing result": strings.Replace(workBuddyInput, "PreToolUse", "PostToolUse", 1),
		"invalid utf8":        strings.Replace(workBuddyInput, "host-session", string([]byte{0xff}), 1),
		"oversized":           strings.Repeat(" ", WorkBuddyHookLimit) + workBuddyInput,
		"deep":                strings.Replace(workBuddyInput, `"file_path":"C:\\fixture\\input.txt"`, `"x":`+strings.Repeat("[", 65)+"0"+strings.Repeat("]", 65), 1),
	}
	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			for _, mode := range []string{"block", "warn", "audit_only"} {
				d := &workBuddyDecider{action: "allow"}
				out := WorkBuddyManagedHook(strings.NewReader(input), d, "hri-fixture", mode, "")
				if out.HookSpecificOutput.PermissionDecision != "deny" || len(d.events) != 0 {
					t.Fatalf("ambiguous input reached authority in %s: %+v %v", mode, out, d.events)
				}
			}
		})
	}
}

func TestWorkBuddyManagedNativeBindingAndHostPermission(t *testing.T) {
	d := &workBuddyDecider{action: "allow"}
	input := strings.Replace(workBuddyInput, `"tool_name":`, `"agent_id":"host-store-not-authority","tool_name":`, 1)
	input = strings.Replace(input, `"tool_input":{`, `"tool_input":{"session_id":"model-forged-session","call_id":"model-forged-call",`, 1)
	out := WorkBuddyManagedHook(strings.NewReader(input), d, "hri-configured", "block", "")
	session, _ := runtimeidentity.WorkBuddySessionID("host-session")
	call, _ := runtimeidentity.WorkBuddyCallID("host-session", "host-call")
	if len(d.requests) != 1 || strings.Join(d.events, ",") != "enroll,decide" || d.session != session {
		t.Fatalf("chain missing: %+v", d)
	}
	req := d.requests[0]
	if req.SessionID != session || req.ToolCallID != call || req.AgentID != "hri-configured" || req.Platform != "workbuddy" {
		t.Fatalf("host envelope lost: %+v", req)
	}
	raw, _ := json.Marshal(out)
	if strings.Contains(string(raw), "permissionDecision") {
		t.Fatalf("SIQ allow bypassed host permission: %s", raw)
	}
	post := strings.Replace(workBuddyInput, "PreToolUse", "PostToolUse", 1)
	post = strings.TrimSuffix(post, "}") + `,"tool_response":"fixture-result"}`
	out = WorkBuddyManagedHook(strings.NewReader(post), d, "hri-configured", "block", "")
	if strings.Join(d.events, ",") != "enroll,decide,observe" || d.requests[1].SessionID != session || d.requests[1].ToolCallID != call || out.HookSpecificOutput.PermissionDecision != "" {
		t.Fatal("post lost original pre identity or enrolled new authority")
	}
}

func TestWorkBuddyManagedFailuresAndHoldNeverAsk(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, kind := range []string{"nil", "enroll", "decide", "deny", "hold", "redact", "malformed"} {
			t.Run(mode+"/"+kind, func(t *testing.T) {
				d := &workBuddyDecider{action: kind, enrollErr: kind == "enroll", errorDecide: kind == "decide"}
				var client WorkBuddyManagedDecider = d
				if kind == "nil" {
					client = nil
				}
				out := WorkBuddyManagedHook(strings.NewReader(workBuddyInput), client, "hri-fixture", mode, "")
				if out.HookSpecificOutput.PermissionDecision != "deny" {
					t.Fatalf("unsafe permission: %+v", out)
				}
				if kind == "enroll" && strings.Join(d.events, ",") != "enroll" {
					t.Fatal("decide ran after failed enroll")
				}
			})
		}
	}
}

func TestWorkBuddyManagedConfigRejectsFallbackReferences(t *testing.T) {
	root := t.TempDir()
	state := filepath.Join(root, "state")
	path := filepath.Join(root, "profile", "siq-agent-security.json")
	instance := hermeshome.Identifier(filepath.Dir(path))
	cfg := WorkBuddyManagedConfig{SchemaVersion: "workbuddy-managed-hook/v1", RuntimeIdentityID: "ri-" + strings.Repeat("a", 32), InstanceID: instance, AgentID: "hri-" + strings.TrimPrefix(instance, "hi-"), Endpoint: "http://127.0.0.1:47611", EnforcementMode: "block", StateDir: state}
	cfg.CredentialPath = filepath.Join(state, "runtime-identity-secrets", cfg.RuntimeIdentityID+".token")
	raw, _ := json.Marshal(cfg)
	if _, err := DecodeWorkBuddyManagedConfig(raw, path, state); err != nil {
		t.Fatal(err)
	}
	for name, edit := range map[string]func(*WorkBuddyManagedConfig){
		"shared token":     func(c *WorkBuddyManagedConfig) { c.CredentialPath = filepath.Join(state, "token") },
		"default agent":    func(c *WorkBuddyManagedConfig) { c.AgentID = "default" },
		"foreign instance": func(c *WorkBuddyManagedConfig) { c.InstanceID = "hi-" + strings.Repeat("b", 32) },
		"foreign state":    func(c *WorkBuddyManagedConfig) { c.StateDir = filepath.Dir(state) },
		"remote":           func(c *WorkBuddyManagedConfig) { c.Endpoint = "http://example.invalid:47611" },
		"userinfo":         func(c *WorkBuddyManagedConfig) { c.Endpoint = "http://user@127.0.0.1:47611" },
		"missing port":     func(c *WorkBuddyManagedConfig) { c.Endpoint = "http://127.0.0.1" },
		"query":            func(c *WorkBuddyManagedConfig) { c.Endpoint += "?" },
		"unknown mode":     func(c *WorkBuddyManagedConfig) { c.EnforcementMode = "allow" },
	} {
		t.Run(name, func(t *testing.T) {
			c := cfg
			edit(&c)
			raw, _ := json.Marshal(c)
			if _, err := DecodeWorkBuddyManagedConfig(raw, path, state); err == nil {
				t.Fatal("invalid config accepted")
			}
		})
	}
	for _, bad := range []string{string(raw) + `{}`, strings.Replace(string(raw), `"agent_id":`, `"agent_id":"default","agent_id":`, 1), strings.Replace(string(raw), `"agent_id"`, `"Agent_ID"`, 1)} {
		if _, err := DecodeWorkBuddyManagedConfig([]byte(bad), path, state); err == nil {
			t.Fatal("ambiguous config accepted")
		}
	}
}

type workBuddyEnrollmentStageDecider struct {
	workBuddyDecider
	failure error
}

func (d *workBuddyEnrollmentStageDecider) Enroll(string) error { return d.failure }
func TestWorkBuddyEnrollmentDeadlineAlwaysDenies(t *testing.T) {
	for _, failure := range []error{&WorkBuddyEnrollmentDeadline{BeforeRequest: true}, &WorkBuddyEnrollmentDeadline{}, errors.New("private token and URL")} {
		d := &workBuddyEnrollmentStageDecider{failure: failure}
		out := WorkBuddyManagedHook(strings.NewReader(workBuddyInput), d, "hri-fixture", "block", "")
		if out.HookSpecificOutput.PermissionDecision != "deny" || len(d.requests) != 0 || strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "private") {
			t.Fatalf("unsafe enrollment failure: %+v", out)
		}
	}
}

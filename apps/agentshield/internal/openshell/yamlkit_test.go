package openshell

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func testdata(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestParseRealPolicyGetFull(t *testing.T) {
	doc, err := parsePolicyYAML(testdata(t, "policy_get_full.txt"))
	if err != nil {
		t.Fatal(err)
	}
	fs := asMap(doc["filesystem_policy"])
	ro, _ := fs["read_only"].([]any)
	if len(ro) == 0 || ro[0] != "/usr" {
		t.Fatalf("read_only: %v", fs["read_only"])
	}
	if fs["include_workdir"] != true {
		t.Fatalf("include_workdir: %v", fs["include_workdir"])
	}
	proc := asMap(doc["process"])
	if proc["run_as_user"] != "sandbox" {
		t.Fatalf("process: %v", proc)
	}
	if _, ok := doc["network_policies"]; ok {
		t.Fatalf("fixture has no network section: %v", doc["network_policies"])
	}
}

func TestParseRealPolicyGetFullV2Network(t *testing.T) {
	doc, err := parsePolicyYAML(testdata(t, "policy_get_full_v2.txt"))
	if err != nil {
		t.Fatal(err)
	}
	rules, err := networkRules(doc["network_policies"])
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 || rules[0].Endpoint != "api.example.com:443" {
		t.Fatalf("network: %+v", rules)
	}
	if len(rules[0].BinaryPaths) != 1 || rules[0].BinaryPaths[0] != "/usr/bin/curl" {
		t.Fatalf("binaries: %+v", rules[0].BinaryPaths)
	}
}

func TestDumpPreservesStaticFilesystem(t *testing.T) {
	doc, err := parsePolicyYAML(testdata(t, "policy_get_full.txt"))
	if err != nil {
		t.Fatal(err)
	}
	raw := dumpYAML(map[string]any{
		"version":           1,
		"filesystem_policy": doc["filesystem_policy"],
		"landlock":          map[string]any{"compatibility": "best_effort"},
		"process":           doc["process"],
		"network_policies":  map[string]any{},
	})
	again, err := parseYAML(raw)
	if err != nil {
		t.Fatal(err, raw)
	}
	fs := asMap(asMap(again)["filesystem_policy"])
	ro, _ := fs["read_only"].([]any)
	if fs["include_workdir"] != true || len(ro) < 1 || ro[0] != "/usr" {
		t.Fatalf("roundtrip filesystem: %v\n%s", fs, raw)
	}
	if !strings.Contains(raw, "include_workdir: true") {
		t.Fatalf("dump missing include_workdir:\n%s", raw)
	}
}

func TestRejectsTabIndent(t *testing.T) {
	if _, err := parseYAML("a:\n\tb: 1\n"); err == nil {
		t.Fatal("tabs must fail closed")
	}
}

func TestGatewayEndpointValidation(t *testing.T) {
	c := New(Options{})
	t.Setenv(envCLIBin, "/usr/bin/openshell")
	t.Setenv(envEndpoint, "http://gateway.example.com:17671")
	t.Setenv(envInsecure, "0")
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "HTTPS") {
		t.Fatalf("non-loopback http: %v", err)
	}
	t.Setenv(envEndpoint, "https://gateway.example.com:17671")
	t.Setenv(envInsecure, "1")
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "回环") {
		t.Fatalf("insecure non-loopback: %v", err)
	}
	t.Setenv(envInsecure, "0")
	for _, ep := range []string{
		"https://user:secret@gateway.example.com:17671",
		"https://gateway.example.com:17671/admin",
		"https://gateway.example.com:17671?tenant=other",
		"https://gateway.example.com:17671#fragment",
		"https://gateway.example.com:invalid",
	} {
		t.Setenv(envEndpoint, ep)
		_, err := c.BuildCommand([]string{"gateway", "info"})
		if err == nil || !strings.Contains(err.Error(), "无效") {
			t.Fatalf("%s: %v", ep, err)
		}
	}
}

func missingPATH() func(string) (string, error) {
	return func(string) (string, error) { return "", os.ErrNotExist }
}

func TestBuildCommandRequiresPairOrEnvSH(t *testing.T) {
	c := New(Options{LookPath: missingPATH()})
	t.Setenv(envCLIBin, "")
	t.Setenv(envEndpoint, "")
	t.Setenv(envEnvSH, "")
	os.Unsetenv(envCLIBin)
	os.Unsetenv(envEndpoint)
	os.Unsetenv(envEnvSH)
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "未配置") {
		t.Fatalf("unconfigured: %v", err)
	}
	t.Setenv(envCLIBin, "/opt/os104/openshell")
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "必须同时") {
		t.Fatalf("xor: %v", err)
	}
	t.Setenv(envEndpoint, "http://127.0.0.1:17673")
	t.Setenv(envInsecure, "1")
	cmd, err := c.BuildCommand([]string{"sandbox", "list"})
	if err != nil {
		t.Fatal(err)
	}
	if cmd[0] != "/opt/os104/openshell" || !contains(cmd, "--gateway-insecure") {
		t.Fatalf("%v", cmd)
	}
	t.Setenv(envCLIBin, "")
	t.Setenv(envEndpoint, "")
	os.Unsetenv(envCLIBin)
	os.Unsetenv(envEndpoint)
	explicit := New(Options{EnvScript: "/opt/siq/openshell-env.sh"})
	cmd, err = explicit.BuildCommand([]string{"sandbox", "list"})
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS == "windows" {
		// still produces a bash wrapper; execution would fail closed later
	}
	want := []string{"bash", "-c", `source "$1" && shift && exec "${SIQ_OPENSHELL_BIN:-openshell}" "$@"`, "openshell-env", "/opt/siq/openshell-env.sh"}
	if len(cmd) < 5 {
		t.Fatalf("%v", cmd)
	}
	for i := 0; i < 5; i++ {
		if cmd[i] != want[i] {
			t.Fatalf("argv %d: %q != %q (%v)", i, cmd[i], want[i], cmd)
		}
	}
}

func contains(ss []string, v string) bool {
	for _, s := range ss {
		if s == v {
			return true
		}
	}
	return false
}

func TestEnvScriptMustBeAbsolute(t *testing.T) {
	c := New(Options{EnvScript: "relative/env.sh"})
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "绝对路径") {
		t.Fatalf("%v", err)
	}
}

func TestBuildCommandDiscoversPATH(t *testing.T) {
	c := New(Options{
		LookPath: func(name string) (string, error) {
			if name != "openshell" {
				t.Fatalf("looked up %q", name)
			}
			return "/usr/bin/openshell", nil
		},
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	cmd, err := c.BuildCommand([]string{"gateway", "info"})
	if err != nil {
		t.Fatal(err)
	}
	if len(cmd) != 3 || cmd[0] != "/usr/bin/openshell" || cmd[1] != "gateway" || cmd[2] != "info" {
		t.Fatalf("path discovery argv: %v", cmd)
	}
	if contains(cmd, "--gateway-endpoint") {
		t.Fatal("PATH discovery must not inject --gateway-endpoint")
	}
}

func TestBuildCommandIgnoresRelativePATHHit(t *testing.T) {
	c := New(Options{
		LookPath:  func(string) (string, error) { return "openshell", nil },
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	if _, err := c.BuildCommand([]string{"gateway", "info"}); err == nil || !strings.Contains(err.Error(), "未配置") {
		t.Fatalf("relative LookPath must fail closed: %v", err)
	}
}

func TestExplicitPairWinsOverPATH(t *testing.T) {
	c := New(Options{LookPath: func(string) (string, error) { return "/usr/bin/openshell", nil }})
	t.Setenv(envCLIBin, "/opt/os104/openshell")
	t.Setenv(envEndpoint, "http://127.0.0.1:17673")
	t.Setenv(envInsecure, "1")
	cmd, err := c.BuildCommand([]string{"gateway", "info"})
	if err != nil {
		t.Fatal(err)
	}
	if cmd[0] != "/opt/os104/openshell" || !contains(cmd, "--gateway-endpoint") {
		t.Fatalf("explicit pair must win: %v", cmd)
	}
}

// 回归：YAML 指示符只在节点起始位置有语义。真实网关策略含值中部的 glob
// 通配符（如 path: /research/**），不得因值内出现 * 而被误判为不受支持语法。
func TestYAMLAcceptsIndicatorsInsidePlainScalars(t *testing.T) {
	cases := []struct {
		src  string
		key  string
		want any
	}{
		{"path: /research/**\n", "path", "/research/**"},
		{"cmd: /usr/bin/curl -x http://a*b\n", "cmd", "/usr/bin/curl -x http://a*b"},
		{"note: a|b&c!d>e\n", "note", "a|b&c!d>e"},
		{"glob: /logs/**/*.log\n", "glob", "/logs/**/*.log"},
		{"glob: \"**/*.log\"\n", "glob", "**/*.log"},
		{"q: \"*alias not real\"\n", "q", "*alias not real"},
		{"empty: {}\n", "empty", map[string]any{}},
		{"empty: []\n", "empty", []any{}},
	}
	for _, tc := range cases {
		v, err := parseYAML(tc.src)
		if err != nil {
			t.Fatalf("parseYAML(%q) = %v, want ok", tc.src, err)
		}
		got := v.(map[string]any)[tc.key]
		if !reflect.DeepEqual(got, tc.want) {
			t.Fatalf("parseYAML(%q)[%s] = %#v, want %#v", tc.src, tc.key, got, tc.want)
		}
	}
}

// 负向回归：真正的 YAML 锚点/别名/标签/块标量/流集合仍必须 fail-closed。
func TestYAMLRejectsNodeStartIndicators(t *testing.T) {
	bad := []string{
		"key: *alias\n",
		"key: &anchor value\n",
		"key: !!str value\n",
		"key: !tag value\n",
		"key: |\n  block\n",
		"key: >\n  folded\n",
		"key: |2\n  block\n",
		"- *alias\n",
		"- &anchor key: v\n",
		"key: {a: b}\n",
		"key: [1, 2]\n",
		"key: ,leading\n",
		"key: ]leading\n",
		"key: `reserved\n",
		"*alias\n",
		"&anchor key: v\n",
	}
	for _, src := range bad {
		if _, err := parseYAML(src); err == nil {
			t.Fatalf("parseYAML(%q) must fail closed, got nil error", src)
		}
	}
}

// 回归：网关 0.0.83 的网络策略形状（rest allow 限制 + allowed_ips）必须可保真读回。
func TestNetworkRulesReadbackGatewayV0083Shapes(t *testing.T) {
	src := `network_policies:
  rest_provider:
    name: rest-provider
    endpoints:
    - host: api.example.com
      port: 443
      protocol: rest
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /v1/models
      - allow:
          method: POST
          path: /v1/messages/**
    binaries:
    - path: /usr/bin/curl
  ip_allowlist:
    name: ip-allowlist
    endpoints:
    - host: host.openshell.internal
      port: 8000
      allowed_ips:
      - '172.23.0.1/32'
    binaries:
    - path: /usr/bin/curl
`
	doc, err := parseYAML(src)
	if err != nil {
		t.Fatal(err)
	}
	rules, err := networkRules(doc.(map[string]any)["network_policies"])
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 3 {
		t.Fatalf("rules: %+v", rules)
	}
	// provider keys are summarized in sorted order: ip_allowlist < rest_provider
	ip := rules[0]
	if ip.Endpoint != "host.openshell.internal:8000" || len(ip.AllowedIPs) != 1 || ip.AllowedIPs[0] != "172.23.0.1/32" {
		t.Fatalf("ip: %+v", ip)
	}
	rest := rules[1]
	if rest.Endpoint != "api.example.com:443" || rest.Method != "GET" || rest.Path != "/v1/models" {
		t.Fatalf("rest[0]: %+v", rest)
	}
	if rules[2].Method != "POST" || rules[2].Path != "/v1/messages/**" {
		t.Fatalf("rest[1]: %+v", rules[2])
	}
}

// 负向回归：0.0.83 形状之外的限制仍必须 fail-closed，不得静默丢弃后夸大有效权限。
func TestNetworkRulesReadbackFailClosedBeyondV0083(t *testing.T) {
	base := func(endpointExtra, rule string) string {
		return "network_policies:\n  p:\n    name: p\n    endpoints:\n    - host: a.example.com\n      port: 443\n" +
			endpointExtra + "    binaries:\n    - path: /usr/bin/curl\n" + rule
	}
	cases := map[string]string{
		"enforcement-monitor":  base("      enforcement: monitor\n", ""),
		"protocol-tcp":         base("      protocol: tcp\n", ""),
		"rewrite-string":       base("      request_body_credential_rewrite: \"true\"\n", ""),
		"unknown-endpoint-key": base("      future_restriction: x\n", ""),
		"malformed-cidr":       base("      allowed_ips:\n      - '172.23.0.1/33'\n", ""),
		"empty-allowed-ips":    base("      allowed_ips: []\n", ""),
		"deny-rule":            base("      rules:\n      - deny:\n          method: GET\n          path: /x\n", ""),
		"rules-empty-list":     base("      rules: []\n", ""),
		"allow-missing-path":   base("      rules:\n      - allow:\n          method: GET\n", ""),
		"allow-extra-key":      base("      rules:\n      - allow:\n          method: GET\n          path: /x\n          future: z\n", ""),
	}
	for name, src := range cases {
		doc, err := parseYAML(src)
		if err != nil {
			t.Fatalf("%s: fixture itself must parse: %v", name, err)
		}
		if _, err := networkRules(doc.(map[string]any)["network_policies"]); err == nil {
			t.Fatalf("%s: networkRules must fail closed, got nil error", name)
		}
	}
}

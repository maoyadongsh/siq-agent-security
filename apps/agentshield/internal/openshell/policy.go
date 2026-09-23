package openshell

import (
	"crypto/sha256"
	"encoding/hex"
	"net"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

// ReadEffective parses `policy get <target> --full`.
func (c *Client) ReadEffective(target string) (Snapshot, error) {
	out, err := c.cli("policy", "get", target, "--full")
	if err != nil {
		return Snapshot{}, err
	}
	doc, err := parsePolicyYAML(out)
	if err != nil {
		return Snapshot{}, err
	}
	rev, err := parseActiveRevision(out)
	if err != nil {
		return Snapshot{}, err
	}
	digest, err := policyDigest(doc)
	if err != nil {
		return Snapshot{}, err
	}
	staticDigest, err := staticPolicyDigest(doc)
	if err != nil {
		return Snapshot{}, err
	}
	network, err := networkRules(doc["network_policies"])
	if err != nil {
		return Snapshot{}, err
	}
	return Snapshot{
		Target:          target,
		Revision:        rev,
		LoadEpoch:       parsePolicyLoadEpoch(out),
		PolicyStatus:    parsePolicyStatus(out),
		Policy:          clonePolicy(doc),
		PolicyDigest:    digest,
		StaticDigest:    staticDigest,
		Filesystem:      asMap(doc["filesystem_policy"]),
		Network:         network,
		Process:         asMap(doc["process"]),
		EnforcementMode: "unknown", // policy get --full has no mode field
	}, nil
}

func parsePolicyStatus(out string) string {
	for _, line := range strings.Split(out, "\n") {
		if strings.TrimSpace(line) == "---" {
			break
		}
		key, value, ok := strings.Cut(line, ":")
		if ok && strings.TrimSpace(key) == "Status" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

// parsePolicyLoadEpoch extracts the target revision's Loaded timestamp from
// policy get --full only while the reported revision is loaded/active. A stale
// Loaded field alongside Pending/Failed must not preserve execution proof.
// Missing or malformed metadata yields no execution proof; ordinary policy
// readback remains available for diagnostics and rollback.
func parsePolicyLoadEpoch(out string) string {
	var status, loaded string
	for _, line := range strings.Split(out, "\n") {
		if strings.TrimSpace(line) == "---" {
			break
		}
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		switch strings.TrimSpace(key) {
		case "Status":
			status = strings.TrimSpace(value)
		case "Loaded":
			parts := strings.Fields(value)
			if len(parts) != 2 || parts[1] != "ms" {
				return ""
			}
			millis, err := strconv.ParseUint(parts[0], 10, 64)
			if err != nil || millis == 0 {
				return ""
			}
			loaded = parts[0]
		}
	}
	if status != "Loaded" && status != "Active" {
		return ""
	}
	return loaded
}

func parsePolicyYAML(out string) (map[string]any, error) {
	lines := strings.Split(out, "\n")
	marker := -1
	for i, line := range lines {
		if strings.TrimSpace(line) == "---" {
			if marker >= 0 {
				return nil, fail("策略 YAML 文档边界歧义（fail-closed）")
			}
			marker = i
		}
	}
	if marker < 0 {
		return nil, fail("策略输出缺少 YAML 文档边界（fail-closed）")
	}
	body := strings.Join(lines[marker+1:], "\n")
	v, err := parseYAML(body)
	if err != nil {
		return nil, err
	}
	doc, ok := v.(map[string]any)
	if !ok || doc == nil {
		return nil, fail("策略 YAML 解析失败（fail-closed）: expected mapping")
	}
	return doc, nil
}

func parseActiveRevision(out string) (string, error) {
	revisions := map[string]string{}
	metadataKeys := map[string]bool{}
	for _, line := range strings.Split(out, "\n") {
		if strings.TrimSpace(line) == "---" {
			break
		}
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "-") || !strings.Contains(line, ":") {
			continue
		}
		key, value, _ := strings.Cut(line, ":")
		key = strings.TrimSpace(key)
		if metadataKeys[key] {
			return "", fail("策略元信息包含重复 key（fail-closed）")
		}
		metadataKeys[key] = true
		if key != "Active" && key != "Version" {
			continue
		}
		revisions[key] = strings.TrimSpace(value)
	}
	if len(revisions) == 0 {
		return "", fail("策略元信息缺少 revision（fail-closed）")
	}
	for _, revision := range revisions {
		if err := validateRevision(revision); err != nil {
			return "", err
		}
	}
	if active, ok := revisions["Active"]; ok {
		if version, hasVersion := revisions["Version"]; hasVersion && version != active {
			return "", fail("策略元信息 revision 歧义（fail-closed）")
		}
		return active, nil
	}
	return revisions["Version"], nil
}

func validateRevision(revision string) error {
	if revision == "" || revision[0] == '0' {
		return fail("策略 revision 非规范正十进制（fail-closed）")
	}
	for _, r := range revision {
		if r < '0' || r > '9' {
			return fail("策略 revision 非规范正十进制（fail-closed）")
		}
	}
	return nil
}

func networkRules(raw any) ([]NetworkRule, error) {
	var rules []NetworkRule
	if raw == nil {
		return rules, nil
	}
	gateway, ok := raw.(map[string]any)
	if !ok {
		return nil, fail("后端网络策略形状不受支持（fail-closed）")
	}
	for _, key := range sortedMapKeys(gateway) {
		raw := gateway[key]
		rule, ok := raw.(map[string]any)
		if !ok {
			return nil, fail("后端网络策略形状不受支持（fail-closed）")
		}
		if !onlyKeys(rule, "name", "endpoints", "binaries") {
			return nil, fail("后端网络策略包含不可保真的限制（fail-closed）")
		}
		name, _ := rule["name"].(string)
		if name == "" {
			name = key
		}
		bl, ok := rule["binaries"].([]any)
		if !ok || len(bl) == 0 {
			return nil, fail("后端网络策略缺少显式 binary path（fail-closed）")
		}
		var bins []string
		for _, b := range bl {
			m, ok := b.(map[string]any)
			if !ok || !onlyKeys(m, "path") {
				return nil, fail("后端网络 binary 限制不可保真（fail-closed）")
			}
			path, ok := m["path"].(string)
			if !ok || !isAbsPath(path) {
				return nil, fail("网络规则必须包含显式绝对 binary path（fail-closed）")
			}
			bins = append(bins, path)
		}
		eps, ok := rule["endpoints"].([]any)
		if !ok || len(eps) == 0 {
			return nil, fail("后端网络策略缺少 endpoint（fail-closed）")
		}
		for _, e := range eps {
			m, ok := e.(map[string]any)
			if !ok || !onlyKeys(m, "host", "port", "protocol", "enforcement", "rules", "allowed_ips", "request_body_credential_rewrite") {
				return nil, fail("后端网络 endpoint 限制不可保真（fail-closed）")
			}
			host, hostOK := m["host"].(string)
			port, portOK := m["port"].(int)
			if !hostOK || !portOK || !validHost(host) || port < 1 || port > 65535 {
				return nil, fail("后端网络 endpoint 无效（fail-closed）")
			}
			// The gateway 0.0.83 schema carries protocol/enforcement as fixed
			// values; anything else cannot be summarized without overstating
			// what the backend actually enforces, so it fails closed.
			if v, ok := m["protocol"]; ok && v != "rest" {
				return nil, fail("后端网络 endpoint protocol 不可保真（fail-closed）")
			}
			if v, ok := m["enforcement"]; ok && v != "enforce" {
				return nil, fail("后端网络 endpoint enforcement 不可保真（fail-closed）")
			}
			var rewrite *bool
			if v, ok := m["request_body_credential_rewrite"]; ok {
				value, isBool := v.(bool)
				if !isBool {
					return nil, fail("后端网络 request_body_credential_rewrite 无效（fail-closed）")
				}
				rewrite = &value
			}
			protocol, _ := m["protocol"].(string)
			enforcement, _ := m["enforcement"].(string)
			var ips []string
			if raw, ok := m["allowed_ips"]; ok {
				list, isList := raw.([]any)
				if !isList || len(list) == 0 {
					return nil, fail("后端网络 allowed_ips 无效（fail-closed）")
				}
				for _, item := range list {
					s, isStr := item.(string)
					if !isStr {
						return nil, fail("后端网络 allowed_ips 非有效 CIDR（fail-closed）")
					}
					if _, _, err := net.ParseCIDR(strings.TrimSpace(s)); err != nil {
						return nil, fail("后端网络 allowed_ips 非有效 CIDR（fail-closed）")
					}
					ips = append(ips, s)
				}
			}
			type allowRule struct{ method, path string }
			var allows []allowRule
			if raw, ok := m["rules"]; ok {
				list, isList := raw.([]any)
				if !isList || len(list) == 0 {
					return nil, fail("后端网络 rules 无效（fail-closed）")
				}
				for _, item := range list {
					rm, isMap := item.(map[string]any)
					if !isMap || !onlyKeys(rm, "allow") {
						return nil, fail("后端网络 rule 含不可保真的 effect（fail-closed）")
					}
					am, isMap := rm["allow"].(map[string]any)
					if !isMap || !onlyKeys(am, "method", "path") {
						return nil, fail("后端网络 allow rule 形状不可保真（fail-closed）")
					}
					method, _ := am["method"].(string)
					path, _ := am["path"].(string)
					if method == "" || path == "" {
						return nil, fail("后端网络 allow rule 缺少 method/path（fail-closed）")
					}
					allows = append(allows, allowRule{method: method, path: path})
				}
			}
			endpoint := net.JoinHostPort(host, strconv.Itoa(port))
			if len(allows) == 0 {
				rules = append(rules, NetworkRule{
					Endpoint:    endpoint,
					Effect:      "allow",
					BinaryPaths: bins,
					RuleName:    name,
					AllowedIPs:  ips, Protocol: protocol, Enforcement: enforcement, RequestBodyCredentialRewrite: rewrite,
				})
				continue
			}
			// One readback entry per explicit allow restriction so the
			// method/path limits stay attached to the endpoint instead of
			// being silently dropped.
			for _, a := range allows {
				rules = append(rules, NetworkRule{
					Endpoint:    endpoint,
					Effect:      "allow",
					BinaryPaths: bins,
					RuleName:    name,
					Method:      a.method,
					Path:        a.path,
					AllowedIPs:  ips, Protocol: protocol, Enforcement: enforcement, RequestBodyCredentialRewrite: rewrite,
				})
			}
		}
	}
	return rules, nil
}

// Restricted projections are read-only until the writer can preserve all semantics.
func (r NetworkRule) hasReadbackRestrictions() bool {
	return r.Method != "" || r.Path != "" || r.AllowedIPs != nil ||
		r.Protocol != "" || r.Enforcement != "" || r.RequestBodyCredentialRewrite != nil
}

func networkRulesToGateway(rules []NetworkRule) (map[string]any, error) {
	gateway := map[string]any{}
	for idx, rule := range rules {
		if rule.hasReadbackRestrictions() {
			return nil, fail("网络读回限制不支持写入，拒绝降格为 host:port（fail-closed）")
		}
		if rule.Effect != "allow" {
			return nil, fail("OpenShell 仅支持显式 allow 网络规则（fail-closed）")
		}
		host, port, err := splitEndpoint(rule.Endpoint)
		if err != nil {
			return nil, err
		}
		bins := rule.BinaryPaths
		if len(bins) == 0 {
			return nil, fail("网络规则必须包含显式绝对 binary path（fail-closed）")
		}
		binaries := make([]any, 0, len(bins))
		for _, p := range bins {
			if !isAbsPath(p) {
				return nil, fail("网络规则必须包含显式绝对 binary path（fail-closed）")
			}
			binaries = append(binaries, map[string]any{"path": p})
		}
		name := rule.RuleName
		if name == "" {
			name = "siq-as-rule-" + strconv.Itoa(idx)
		}
		gateway["siq_as_rule_"+strconv.Itoa(idx)] = map[string]any{
			"name":      name,
			"endpoints": []any{map[string]any{"host": host, "port": port}},
			"binaries":  binaries,
		}
	}
	return gateway, nil
}

func splitEndpoint(endpoint string) (host string, port int, err error) {
	if strings.ContainsAny(endpoint, "/?#@ \t\r\n") {
		return "", 0, fail("OpenShell 网络规则仅支持 host:port（fail-closed）")
	}
	colon := strings.LastIndexByte(endpoint, ':')
	if colon <= 0 || colon == len(endpoint)-1 {
		return "", 0, fail("OpenShell 网络规则必须显式指定 host:port（fail-closed）")
	}
	host, portText := endpoint[:colon], endpoint[colon+1:]
	if strings.HasPrefix(host, "[") && strings.HasSuffix(host, "]") {
		host = host[1 : len(host)-1]
	} else if strings.Contains(host, ":") {
		return "", 0, fail("IPv6 网络 endpoint 必须使用方括号（fail-closed）")
	}
	port, err = strconv.Atoi(portText)
	if err != nil || strconv.Itoa(port) != portText || port < 1 || port > 65535 || !validHost(host) {
		return "", 0, fail("OpenShell 网络 endpoint 无效（fail-closed）")
	}
	return host, port, nil
}

func validHost(host string) bool {
	return host != "" && !strings.ContainsAny(host, "/?#@[] \t\r\n")
}

// sortedMapKeys keeps readback summaries deterministic across runs; Go map
// iteration order would otherwise leak into Snapshot.Network.
func sortedMapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func onlyKeys(m map[string]any, allowed ...string) bool {
	want := make(map[string]bool, len(allowed))
	for _, key := range allowed {
		want[key] = true
	}
	for key := range m {
		if !want[key] {
			return false
		}
	}
	return true
}

func withPolicyFile(doc map[string]any, fn func(path string) error) (err error) {
	f, err := statefs.CreateTemp("", "siq-as-policy-*.yaml")
	if err != nil {
		return failf("无法创建策略临时文件（fail-closed）: %s", err.Error())
	}
	path := f.Name()
	defer func() {
		_ = statefs.Remove(path)
	}()
	if err := f.Chmod(0o600); err != nil {
		_ = f.Close()
		return failf("无法设置策略临时文件权限（fail-closed）: %s", err.Error())
	}
	if _, err := f.WriteString(dumpYAML(doc)); err != nil {
		_ = f.Close()
		return failf("无法写入策略临时文件（fail-closed）: %s", err.Error())
	}
	if err := f.Close(); err != nil {
		return err
	}
	return fn(path)
}

func parseSetReceipt(out string) (revision, hash string, err error) {
	m := versionSubmittedRe.FindStringSubmatch(out)
	if m == nil {
		m = versionUnchangedRe.FindStringSubmatch(out)
	}
	if m == nil {
		return "", "", fail("无法解析 policy set 回执（fail-closed）")
	}
	return m[1], m[2], nil
}

// setPolicyAndWait requires the sandbox load acknowledgement, not merely
// gateway submission. Outer Runner timeout remains authoritative. Never retry
// a timeout without --wait: the first write may already have happened.
func (c *Client) setPolicyAndWait(target, path string) (string, error) {
	seconds := int64(c.Timeout/time.Second) - 2
	if seconds < 1 {
		seconds = 1
	}
	return c.cli("policy", "set", target, "--policy", path, "--wait", "--timeout", strconv.FormatInt(seconds, 10))
}

// ApplyNetwork merges the live static sections with the new network rules and
// submits `policy set`. It never writes filesystem/process from the caller and
// never calls create_generation.
func (c *Client) ApplyNetwork(target string, rules []NetworkRule, expectedRevision string) (DeploymentReceipt, error) {
	lock := c.targetPolicyLock(target)
	lock.Lock()
	defer lock.Unlock()
	return c.applyNetworkLocked(target, rules, expectedRevision, nil)
}

// ApplyNetworkAuthorized rechecks the caller's current authority after backend
// prewrite drift checks. It makes no cross-process atomicity guarantee.
func (c *Client) ApplyNetworkAuthorized(target string, rules []NetworkRule, expectedRevision string, authorize func() error) (DeploymentReceipt, error) {
	if authorize == nil {
		return DeploymentReceipt{}, fail("current authorization required")
	}
	lock := c.targetPolicyLock(target)
	lock.Lock()
	defer lock.Unlock()
	return c.applyNetworkLocked(target, rules, expectedRevision, func(Snapshot) error { return authorize() })
}

// ApplyNetworkAuthorizedBase checks the exact captured restore baseline while
// holding the target lock; callers can refuse replacing a policy they cannot
// restore under current authority. The callback also rechecks current authority.
func (c *Client) ApplyNetworkAuthorizedBase(target string, rules []NetworkRule, expectedRevision string, authorize func(Snapshot) error) (DeploymentReceipt, error) {
	if authorize == nil {
		return DeploymentReceipt{}, fail("current authorization required")
	}
	lock := c.targetPolicyLock(target)
	lock.Lock()
	defer lock.Unlock()
	return c.applyNetworkLocked(target, rules, expectedRevision, authorize)
}

func (c *Client) applyNetworkLocked(target string, rules []NetworkRule, expectedRevision string, authorize func(Snapshot) error) (DeploymentReceipt, error) {
	if err := validateRevision(expectedRevision); err != nil {
		return DeploymentReceipt{}, err
	}
	current, err := c.ReadEffective(target)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	if current.Revision != expectedRevision {
		return DeploymentReceipt{}, &RevisionConflict{Expected: expectedRevision, Actual: current.Revision}
	}
	gw, err := networkRulesToGateway(rules)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	merged := clonePolicy(current.Policy)
	if len(gw) == 0 {
		// Full gateway readback omits the empty map. Match its write form
		// on revocation; preserve an already-empty map as a no-op.
		if existing, ok := merged["network_policies"].(map[string]any); !ok || len(existing) != 0 {
			delete(merged, "network_policies")
		}
	} else {
		merged["network_policies"] = gw
	}
	expectedDigest, err := policyDigest(merged)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	opID, err := newOperationID()
	if err != nil {
		return DeploymentReceipt{}, err
	}
	if expectedDigest == current.PolicyDigest {
		if authorize != nil {
			if err := authorize(current); err != nil {
				return DeploymentReceipt{}, err
			}
		}
		receipt := DeploymentReceipt{
			OperationID: opID, Target: target,
			BaseRevision: current.Revision, BasePolicyDigest: current.PolicyDigest,
			BackendRevision: current.Revision, AppliedPolicyDigest: current.PolicyDigest,
			Result: "no_op", Evidence: map[string]string{"full_policy_digest": current.PolicyDigest},
		}
		c.rememberOperation(policyOperation{
			ID: opID, Target: target, Base: current,
			AppliedRevision: current.Revision, AppliedDigest: current.PolicyDigest, NoOp: true,
		})
		return receipt, nil
	}
	prewrite, err := c.ReadEffective(target)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	if prewrite.Revision != current.Revision || prewrite.PolicyDigest != current.PolicyDigest {
		return DeploymentReceipt{}, fail("OpenShell 策略写前检测到外部漂移（fail-closed）")
	}
	if authorize != nil {
		if err := authorize(current); err != nil {
			return DeploymentReceipt{}, err
		}
	}
	// The write may reach the gateway even if --wait or readback fails. Drop
	// the old loaded fact before that side effect, not after observing success.
	c.forgetLoadedPolicy(target)
	var out string
	err = withPolicyFile(merged, func(path string) error {
		var e error
		out, e = c.setPolicyAndWait(target, path)
		return e
	})
	if err != nil {
		return DeploymentReceipt{}, err
	}
	rev, hash, err := parseSetReceipt(out)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	if err := validateRevision(rev); err != nil {
		return DeploymentReceipt{}, err
	}
	readback, err := c.readAfterWrite(prewrite, rev, expectedDigest)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	c.rememberLoadedPolicy(target, readback.Revision, readback.PolicyDigest, readback.LoadEpoch)
	receipt := DeploymentReceipt{
		OperationID: opID, Target: target,
		BaseRevision: current.Revision, BasePolicyDigest: current.PolicyDigest,
		BackendRevision: rev, AppliedPolicyDigest: expectedDigest, Result: "applied",
		Evidence: map[string]string{
			"gateway_policy_hash": hash,
			"full_policy_digest":  readback.PolicyDigest,
		},
	}
	c.rememberOperation(policyOperation{
		ID: opID, Target: target, Base: current,
		AppliedRevision: rev, AppliedDigest: expectedDigest,
	})
	return receipt, nil
}

func (c *Client) readAfterWrite(base Snapshot, expectedRevision, expectedDigest string) (Snapshot, error) {
	var last Snapshot
	for attempt := 0; attempt < c.PollAttempts; attempt++ {
		snapshot, err := c.ReadEffective(base.Target)
		if err != nil {
			return Snapshot{}, err
		}
		last = snapshot
		if snapshot.Revision == expectedRevision && snapshot.PolicyDigest == expectedDigest {
			return snapshot, nil
		}
		if snapshot.Revision != base.Revision && snapshot.Revision != expectedRevision {
			return Snapshot{}, fail("OpenShell 策略写后检测到外部 revision 漂移（fail-closed）")
		}
		if snapshot.Revision == expectedRevision && snapshot.PolicyDigest != expectedDigest {
			return Snapshot{}, fail("OpenShell 策略写后完整摘要不一致（fail-closed）")
		}
		if c.PollInterval > 0 {
			time.Sleep(c.PollInterval)
		}
	}
	if last.Revision == expectedRevision {
		return Snapshot{}, fail("OpenShell 策略写后完整摘要不一致（fail-closed）")
	}
	return Snapshot{}, fail("OpenShell 策略写后 revision 未生效（fail-closed）")
}

// Verify compares a config read-back to expect_allow / expect_deny.
// A pass is always readback_verified — never enforcement_verified.
func (c *Client) Verify(target string, receipt DeploymentReceipt, expectAllow, expectDeny []string) VerificationReport {
	snap, err := c.ReadEffective(target)
	if err != nil {
		return VerificationReport{Passed: false, Level: VerifyFailed, Failures: []string{err.Error()}}
	}
	for i := 0; i < c.PollAttempts; i++ {
		if snap.Revision == receipt.BackendRevision {
			break
		}
		if c.PollInterval > 0 {
			time.Sleep(c.PollInterval)
		}
		var e error
		snap, e = c.ReadEffective(target)
		if e != nil {
			return VerificationReport{Passed: false, Level: VerifyFailed, Failures: []string{e.Error()}}
		}
	}
	allowed := map[string]struct{}{}
	restricted := map[string]struct{}{}
	for _, r := range snap.Network {
		if r.hasReadbackRestrictions() {
			restricted[r.Endpoint] = struct{}{}
		} else if r.Effect != "deny" {
			allowed[r.Endpoint] = struct{}{}
		}
	}
	var failures []string
	if snap.Revision != receipt.BackendRevision {
		failures = append(failures, "revision mismatch: "+snap.Revision+" != "+receipt.BackendRevision)
	}
	if receipt.AppliedPolicyDigest == "" || snap.PolicyDigest != receipt.AppliedPolicyDigest {
		failures = append(failures, "full policy digest mismatch")
	}
	var allowChecks, denyChecks []Check
	for _, e := range expectAllow {
		actual := "not_in_allow_set"
		if _, ok := allowed[e]; ok {
			actual = "allow"
		}
		if _, ok := restricted[e]; ok {
			actual = "restricted"
		}
		allowChecks = append(allowChecks, Check{
			Endpoint: e, Request: "config_readback", Expected: "allow", Actual: actual,
			Result: "allow", Revision: snap.Revision,
		})
		if actual != "allow" {
			failures = append(failures, "allow check failed: "+e)
		}
	}
	for _, e := range expectDeny {
		actual := "deny"
		if _, ok := allowed[e]; ok {
			actual = "in_allow_set"
		}
		if _, ok := restricted[e]; ok {
			actual = "restricted"
		}
		denyChecks = append(denyChecks, Check{
			Endpoint: e, Request: "config_readback", Expected: "deny", Actual: actual,
			Result: "deny", Revision: snap.Revision,
		})
		if actual != "deny" {
			failures = append(failures, "deny check failed: "+e)
		}
	}
	passed := len(failures) == 0
	level := VerifyFailed
	if passed {
		level = VerifyReadback
	}
	return VerificationReport{
		Passed: passed, Level: level,
		AllowChecks: allowChecks, DenyChecks: denyChecks, Failures: failures,
	}
}

// ApplyAndVerify is the CLI/HTTP convenience: network-only apply plus readback.
func (c *Client) ApplyAndVerify(target string, rules []NetworkRule, expectedRevision string, expectAllow, expectDeny []string) (ApplyResult, error) {
	if len(expectAllow) == 0 {
		for _, r := range rules {
			if r.Effect != "deny" && r.Endpoint != "" {
				expectAllow = append(expectAllow, r.Endpoint)
			}
		}
	}
	rec, err := c.ApplyNetwork(target, rules, expectedRevision)
	if err != nil {
		return ApplyResult{}, err
	}
	report := c.Verify(target, rec, expectAllow, expectDeny)
	sum := sha256.Sum256([]byte(rec.BackendRevision + "|" + rec.AppliedPolicyDigest))
	evID := "ev-" + hex.EncodeToString(sum[:8])
	result := ApplyResult{
		Receipt: rec,
		Report:  report,
		Readback: EffectiveReadback{
			Backend:    BackendName,
			Revision:   rec.BackendRevision,
			VerifiedAt: time.Now().UTC().Format(time.RFC3339),
			EvidenceID: evID,
		},
	}
	if !report.Passed {
		return result, failf("openshell 读回未通过（%s）: %s", report.Level, strings.Join(report.Failures, "; "))
	}
	return result, nil
}

// Rollback only completes a no-op restore. Changed rollback requires the
// trusted authorizer accepted by RollbackAuthorized.
func (c *Client) Rollback(target string, receipt DeploymentReceipt) (RollbackReceipt, error) {
	return c.RollbackAuthorized(target, receipt, nil)
}

// RollbackAuthorized restores the exact private base snapshot after current
// authorization and before/after full-digest drift checks.
func (c *Client) RollbackAuthorized(target string, receipt DeploymentReceipt, authorize RollbackAuthorizer) (RollbackReceipt, error) {
	lock := c.targetPolicyLock(target)
	lock.Lock()
	defer lock.Unlock()
	op, ok := c.lookupOperation(receipt.OperationID)
	if !ok {
		return RollbackReceipt{}, fail("未知或已消费的策略操作，拒绝回滚（fail-closed）")
	}
	if err := validateReceiptBinding(receipt, op, target); err != nil {
		return RollbackReceipt{}, err
	}
	current, err := c.ReadEffective(target)
	if err != nil {
		return RollbackReceipt{}, err
	}
	if current.Revision != op.AppliedRevision || current.PolicyDigest != op.AppliedDigest {
		return RollbackReceipt{}, fail("策略当前状态已漂移，拒绝回滚（fail-closed）")
	}
	if op.NoOp {
		c.consumeOperation(op.ID)
		return RollbackReceipt{
			RestoredRevision: current.Revision, RestoredDigest: current.PolicyDigest, Result: "no_op",
			Evidence: map[string]string{"operation_id": op.ID},
		}, nil
	}
	if authorize == nil {
		return RollbackReceipt{}, fail("策略回滚缺少当前授权器（fail-closed）")
	}
	if err := authorize(RollbackAuthorization{OperationID: op.ID, Target: target, Current: current, Restore: op.Base}); err != nil {
		return RollbackReceipt{}, fail("策略回滚当前授权无效（fail-closed）")
	}
	prewrite, err := c.ReadEffective(target)
	if err != nil {
		return RollbackReceipt{}, err
	}
	if prewrite.Revision != op.AppliedRevision || prewrite.PolicyDigest != op.AppliedDigest {
		return RollbackReceipt{}, fail("策略回滚写前检测到外部漂移（fail-closed）")
	}
	c.forgetLoadedPolicy(target)
	var applied string
	err = withPolicyFile(op.Base.Policy, func(path string) error {
		var e error
		applied, e = c.setPolicyAndWait(target, path)
		return e
	})
	if err != nil {
		return RollbackReceipt{}, err
	}
	rev, gatewayHash, err := parseSetReceipt(applied)
	if err != nil {
		return RollbackReceipt{}, err
	}
	if err := validateRevision(rev); err != nil {
		return RollbackReceipt{}, err
	}
	readback, err := c.readAfterWrite(prewrite, rev, op.Base.PolicyDigest)
	if err != nil {
		return RollbackReceipt{}, err
	}
	c.rememberLoadedPolicy(target, readback.Revision, readback.PolicyDigest, readback.LoadEpoch)
	c.consumeOperation(op.ID)
	return RollbackReceipt{
		RestoredRevision: rev, RestoredDigest: readback.PolicyDigest, Result: "restored",
		Evidence: map[string]string{"operation_id": op.ID, "gateway_policy_hash": gatewayHash},
	}, nil
}

// StreamEvents returns policy-list text. It is not a behavioural event stream.
func (c *Client) StreamEvents(cursor string) EventBatch {
	out, err := c.cli("policy", "list")
	if err != nil {
		detail := err.Error()
		if len(detail) > 200 {
			detail = detail[:200]
		}
		return EventBatch{
			Events: []map[string]string{{"type": "backend_unavailable", "detail": detail}},
			Cursor: cursor,
			Source: "cli_policy_list_readback",
		}
	}
	raw := strings.TrimSpace(out)
	if len(raw) > 500 {
		raw = raw[:500]
	}
	return EventBatch{
		Events: []map[string]string{{"type": "policy_history", "raw": raw}},
		Cursor: cursor,
		Source: "cli_policy_list_readback",
	}
}

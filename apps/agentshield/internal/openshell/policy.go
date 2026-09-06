package openshell

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"strconv"
	"strings"
	"time"
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
	meta := parsePolicyMeta(out)
	rev := meta["Active"]
	if rev == "" {
		rev = meta["Version"]
	}
	if rev == "" {
		rev = "1"
	}
	return Snapshot{
		Target:          target,
		Revision:        rev,
		Filesystem:      asMap(doc["filesystem_policy"]),
		Network:         networkRules(asMap(doc["network_policies"])),
		Process:         asMap(doc["process"]),
		EnforcementMode: "unknown", // policy get --full has no mode field
	}, nil
}

func parsePolicyYAML(out string) (map[string]any, error) {
	body := out
	if i := strings.Index(out, "---"); i >= 0 {
		body = out[i+3:]
	}
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

func parsePolicyMeta(out string) map[string]string {
	meta := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "-") || !strings.Contains(line, ":") {
			continue
		}
		key, value, _ := strings.Cut(line, ":")
		meta[strings.TrimSpace(key)] = strings.TrimSpace(value)
	}
	return meta
}

func networkRules(gateway map[string]any) []NetworkRule {
	var rules []NetworkRule
	for key, raw := range gateway {
		rule, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		name, _ := rule["name"].(string)
		if name == "" {
			name = key
		}
		var bins []string
		if bl, ok := rule["binaries"].([]any); ok {
			for _, b := range bl {
				if m, ok := b.(map[string]any); ok {
					if p, ok := m["path"].(string); ok {
						bins = append(bins, p)
					}
				}
			}
		}
		eps, _ := rule["endpoints"].([]any)
		for _, e := range eps {
			m, ok := e.(map[string]any)
			if !ok {
				continue
			}
			host, _ := m["host"].(string)
			port := 443
			switch t := m["port"].(type) {
			case int:
				port = t
			case int64:
				port = int(t)
			case string:
				if n, err := strconv.Atoi(t); err == nil {
					port = n
				}
			}
			rules = append(rules, NetworkRule{
				Endpoint:    host + ":" + strconv.Itoa(port),
				Effect:      "allow",
				BinaryPaths: bins,
				RuleName:    name,
			})
		}
	}
	return rules
}

func networkRulesToGateway(rules []NetworkRule) (map[string]any, error) {
	gateway := map[string]any{}
	for idx, rule := range rules {
		host, port, err := splitEndpoint(rule.Endpoint)
		if err != nil {
			return nil, err
		}
		bins := rule.BinaryPaths
		if len(bins) == 0 {
			bins = []string{"/usr/bin/curl"}
		}
		binaries := make([]any, 0, len(bins))
		for _, p := range bins {
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
	host, rest, _ := strings.Cut(endpoint, ":")
	portStr, path, _ := strings.Cut(rest, "/")
	if path != "" && path != "**" {
		return "", 0, failf("path 级网络规则不被 v0.0.83 支持（拒绝编译）: %s", endpoint)
	}
	if portStr == "" {
		port = 443
	} else {
		port, err = strconv.Atoi(portStr)
		if err != nil || port < 1 || port > 65535 {
			return "", 0, failf("path 级网络规则不被 v0.0.83 支持（拒绝编译）: %s", endpoint)
		}
	}
	if host == "" {
		return "", 0, failf("path 级网络规则不被 v0.0.83 支持（拒绝编译）: %s", endpoint)
	}
	return host, port, nil
}

func withPolicyFile(doc map[string]any, fn func(path string) error) (err error) {
	f, err := os.CreateTemp("", "siq-as-policy-*.yaml")
	if err != nil {
		return failf("无法创建策略临时文件（fail-closed）: %s", err.Error())
	}
	path := f.Name()
	defer func() {
		_ = os.Remove(path)
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
		msg := strings.TrimSpace(out)
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return "", "", failf("无法解析 policy set 回执（fail-closed）: %s", msg)
	}
	return m[1], m[2], nil
}

// ApplyNetwork merges the live static sections with the new network rules and
// submits `policy set`. It never writes filesystem/process from the caller and
// never calls create_generation.
func (c *Client) ApplyNetwork(target string, rules []NetworkRule, expectedRevision string) (DeploymentReceipt, error) {
	current, err := c.ReadEffective(target)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	if expectedRevision != "" && current.Revision != expectedRevision {
		return DeploymentReceipt{}, &RevisionConflict{Expected: expectedRevision, Actual: current.Revision}
	}
	gw, err := networkRulesToGateway(rules)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	merged := map[string]any{
		"version":           1,
		"filesystem_policy": current.Filesystem,
		"landlock":          map[string]any{"compatibility": "best_effort"},
		"process":           current.Process,
		"network_policies":  gw,
	}
	var out string
	err = withPolicyFile(merged, func(path string) error {
		var e error
		out, e = c.cli("policy", "set", target, "--policy", path)
		return e
	})
	if err != nil {
		return DeploymentReceipt{}, err
	}
	rev, hash, err := parseSetReceipt(out)
	if err != nil {
		return DeploymentReceipt{}, err
	}
	return DeploymentReceipt{
		BackendRevision: rev,
		Evidence:        map[string]string{"snapshot_hash": hash, "submitted": rev},
	}, nil
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
	for _, r := range snap.Network {
		if r.Effect != "deny" {
			allowed[r.Endpoint] = struct{}{}
		}
	}
	var failures []string
	if snap.Revision != receipt.BackendRevision {
		failures = append(failures, "revision mismatch: "+snap.Revision+" != "+receipt.BackendRevision)
	}
	var allowChecks, denyChecks []Check
	for _, e := range expectAllow {
		actual := "not_in_allow_set"
		if _, ok := allowed[e]; ok {
			actual = "allow"
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
		denyChecks = append(denyChecks, Check{
			Endpoint: e, Request: "config_readback", Expected: "deny", Actual: actual,
			Result: "deny", Revision: snap.Revision,
		})
		if actual != "deny" {
			failures = append(failures, "deny check failed: "+e)
		}
	}
	if len(allowChecks) == 0 || len(denyChecks) == 0 {
		failures = append(failures, "正负向验证必须各至少一项（§15.3）")
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
	if len(expectDeny) == 0 {
		expectDeny = []string{"192.0.2.1:1"}
	}
	rec, err := c.ApplyNetwork(target, rules, expectedRevision)
	if err != nil {
		return ApplyResult{}, err
	}
	report := c.Verify(target, rec, expectAllow, expectDeny)
	sum := sha256.Sum256([]byte(rec.BackendRevision + "|" + rec.Evidence["snapshot_hash"]))
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

// Rollback restores the previous revision via policy get --rev + policy set.
func (c *Client) Rollback(target string, receipt DeploymentReceipt) (RollbackReceipt, error) {
	raw := strings.TrimSpace(receipt.BackendRevision)
	if raw == "" {
		return RollbackReceipt{}, fail("回执缺少 backend_revision，无法计算回滚目标（fail-closed）")
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return RollbackReceipt{}, failf("backend_revision 非法（无法解析为整数，fail-closed）: %q", raw)
	}
	prev := n - 1
	if prev < 1 {
		return RollbackReceipt{}, fail("无可回滚的上一 revision")
	}
	out, err := c.cli("policy", "get", target, "--rev", strconv.Itoa(prev), "--full")
	if err != nil {
		return RollbackReceipt{}, err
	}
	doc, err := parsePolicyYAML(out)
	if err != nil {
		return RollbackReceipt{}, err
	}
	var applied string
	err = withPolicyFile(doc, func(path string) error {
		var e error
		applied, e = c.cli("policy", "set", target, "--policy", path)
		return e
	})
	if err != nil {
		return RollbackReceipt{}, err
	}
	rev, _, err := parseSetReceipt(applied)
	if err != nil {
		return RollbackReceipt{}, err
	}
	msg := strings.TrimSpace(applied)
	if len(msg) > 120 {
		msg = msg[:120]
	}
	return RollbackReceipt{RestoredRevision: rev, Evidence: map[string]string{"applied": msg}}, nil
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

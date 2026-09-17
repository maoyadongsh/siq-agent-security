package openshell

import (
	"regexp"
	"strings"
)

const errNotOpenShell = "该 endpoint 不是 OpenShell（常见：端口被 OpenClaw/Hermes 占用）"

// errIdentityUnconfirmed: the endpoint answered but its output does not match
// the expected OpenShell server-status shape, so the identity stays unproven.
const errIdentityUnconfirmed = "endpoint 有响应，但 status 输出无法识别为 OpenShell 服务端（身份/协议未确认）"

func looksLikeOpenShellGateway(text string) bool {
	if strings.Contains(text, "Gateway Info") {
		return true
	}
	if strings.Contains(text, "Gateway endpoint:") && strings.Contains(text, "Gateway:") {
		return true
	}
	return strings.Contains(text, "Gateway version:")
}

// looksLikeOpenShellStatus structurally validates live `status` output: an
// rc=0 result only counts as a handshake when it carries a `Server Status`
// heading AND a `Gateway:` line with a sane name. Empty or unrelated rc=0
// output fails closed.
func looksLikeOpenShellStatus(text string) bool {
	heading, names := false, 0
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if !heading {
			if line != "Server Status" {
				return false
			}
			heading = true
			continue
		}
		if strings.HasPrefix(line, "Gateway:") {
			if sanitizeGatewayName(strings.TrimSpace(strings.TrimPrefix(line, "Gateway:"))) == "" {
				return false
			}
			names++
		}
	}
	return heading && names == 1
}

var gatewayVersionRe = regexp.MustCompile(`(?im)^\s*Gateway version:\s*v?(\d+\.\d+\.\d+)\s*$`)

// parseGatewayVersion reads a gateway version ONLY from live handshake output
// (`status`). `gateway info` is a local config print and never proves the
// gateway's version.
func parseGatewayVersion(text string) string {
	if m := gatewayVersionRe.FindStringSubmatch(text); m != nil {
		return m[1]
	}
	return ""
}

func looksLikeForeignGateway(text string) bool {
	if looksLikeOpenShellGateway(text) {
		return false
	}
	lower := strings.ToLower(text)
	for _, n := range []string{
		"invalidcontenttype",
		"corrupt message",
		"openclaw",
		"hermes-agent",
		"websocket handshake",
	} {
		if strings.Contains(lower, n) {
			return true
		}
	}
	return false
}

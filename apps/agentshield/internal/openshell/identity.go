package openshell

import "strings"

const errNotOpenShell = "该 endpoint 不是 OpenShell（常见：端口被 OpenClaw/Hermes 占用）"

func looksLikeOpenShellGateway(text string) bool {
	if strings.Contains(text, "Gateway Info") {
		return true
	}
	if strings.Contains(text, "Gateway endpoint:") && strings.Contains(text, "Gateway:") {
		return true
	}
	return strings.Contains(text, "Gateway version:")
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

package runtimeaction

import (
	"regexp"
	"strings"
)

const (
	EffectToolInvoke     = "tool.invoke"
	EffectFileRead       = "file.read"
	EffectFileWrite      = "file.write"
	EffectFileDelete     = "file.delete"
	EffectNetworkRequest = "network.request"
	EffectProcessExec    = "process.exec"
	EffectMessageSend    = "message.send"
	EffectDatabaseRead   = "database.read"
	EffectDatabaseWrite  = "database.write"
	EffectSecretRead     = "secret.read"
	EffectUnknown        = "unknown"
)

var networkCommand = regexp.MustCompile(`(?i)\b(curl|wget|nc|ncat|netcat|ssh|scp|rsync|ftp|telnet|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b`)

// Normalize maps adapter vocabulary to stable operation/effect vocabulary.
// Unknown tools remain explicit unknown so an intent can fail closed.
func Normalize(tool string, params map[string]any) (operation string, effects []string) {
	t := strings.ToLower(strings.TrimSpace(tool))
	switch t {
	case "read_file", "read", "cat":
		return "read", []string{EffectFileRead}
	case "write_file", "write", "edit", "patch":
		return "write", []string{EffectFileWrite}
	case "delete_file", "remove":
		return "delete", []string{EffectFileDelete}
	case "send_message", "message":
		return "send", []string{EffectMessageSend}
	case "web_fetch", "web_extract", "web_search", "http", "http_request", "fetch", "browser_navigate", "webfetch", "websearch", "browser":
		return "request", []string{EffectNetworkRequest}
	case "exec", "terminal", "bash", "shell", "process":
		effects := []string{EffectProcessExec}
		for _, value := range params {
			if text, ok := value.(string); ok {
				lower := strings.ToLower(text)
				if networkCommand.MatchString(lower) || strings.Contains(lower, "http://") || strings.Contains(lower, "https://") {
					effects = append(effects, EffectNetworkRequest)
					break
				}
			}
		}
		// A text command can delegate to arbitrary programs or shell expansions.
		// Known hints are not an exhaustive effect inventory.
		return "exec", append(effects, EffectUnknown)
	default:
		return "invoke", []string{EffectUnknown}
	}
}

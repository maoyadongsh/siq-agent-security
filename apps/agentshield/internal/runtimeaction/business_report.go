package runtimeaction

import "regexp"

// These are versioned implementation contracts, not a wildcard trust rule for
// MCP tools. The reviewed publisher takes no caller-controlled paths or code.
const (
	ResearchPublishTool  = "mcp__siq_business__research_publish_report"
	ResearchVerifyTool   = "mcp__siq_business__research_verify_published_report"
	ResearchBusinessRoot = "/sandbox/siq-business"
)

var businessID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var businessDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

func businessReportShape(tool string, params map[string]any) bool {
	valid := func(key string, pattern *regexp.Regexp) bool {
		value, ok := params[key].(string)
		return ok && pattern.MatchString(value)
	}
	switch tool {
	case ResearchPublishTool:
		return len(params) == 3 && valid("task_id", businessID) && valid("request_sha256", businessDigest) && valid("approval_sha256", businessDigest)
	case ResearchVerifyTool:
		return len(params) == 1 && valid("report_key", businessID)
	default:
		return false
	}
}

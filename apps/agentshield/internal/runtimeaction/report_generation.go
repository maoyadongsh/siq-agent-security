package runtimeaction

import (
	"encoding/json"
	"path"
	"regexp"
	"strconv"
	"unicode/utf8"
)

const ResearchGenerateTool = "mcp__siq_business__research_generate_report"
const ResearchGenerateBroker = "host.openshell.internal:18794"

var reportCompanyPath = regexp.MustCompile(`^/(?:[^/\\\x00-\x1f\x7f]+/)+data/wiki/companies/[0-9]{6}-[^/\\\x00-\x1f\x7f]{1,153}$`)
var reportRunID = regexp.MustCompile(`^qwen-request-[a-f0-9]{16}$`)

func reportYear(value any) bool {
	var number float64
	switch v := value.(type) {
	case float64:
		number = v
	case int:
		number = float64(v)
	case int64:
		number = float64(v)
	case json.Number:
		var err error
		number, err = strconv.ParseFloat(string(v), 64)
		if err != nil {
			return false
		}
	default:
		return false
	}
	return number >= 2000 && number <= 2200 && number == float64(int(number))
}

func generationDescriptor(tool string, params map[string]any, normalize func(string, string) (string, error)) (Descriptor, bool) {
	company, companyOK := params["company_path"].(string)
	run, runOK := params["run_id"].(string)
	if tool != ResearchGenerateTool || len(params) != 3 || !companyOK || !runOK || len(company) > 4096 ||
		!utf8.ValidString(company) || !reportCompanyPath.MatchString(company) || path.Clean(company) != company ||
		!reportRunID.MatchString(run) || !reportYear(params["year"]) {
		return Descriptor{}, false
	}
	metadata := path.Dir(path.Dir(company)) + "/_meta"
	output := company + "/analysis/runs/" + run
	d := Descriptor{Tool: tool, Operation: "generate", Effects: []string{EffectFileRead, EffectFileWrite,
		EffectProcessExec, EffectDatabaseRead, EffectNetworkRequest}, Mutating: true, Egress: true,
		FilesystemWriteHint: true, HighImpactParameterPaths: []string{"/company_path", "/run_id", "/year"},
		Hosts: []string{ResearchGenerateBroker}, ReadOnlyPaths: map[string]bool{}}
	for _, p := range []string{company, metadata, output} {
		value, err := normalize("filesystem", p)
		if err != nil {
			d.ResourceError = err
			return d, true
		}
		d.Paths = append(d.Paths, value)
		d.Resources = append(d.Resources, Resource{Domain: "filesystem", Value: value})
		if p != output {
			d.ReadOnlyPaths[value] = true
		}
	}
	host, err := normalize("network", "http://"+ResearchGenerateBroker)
	if err != nil {
		d.ResourceError = err
		return d, true
	}
	d.Resources = append(d.Resources, Resource{Domain: "network", Value: host})
	return d, true
}

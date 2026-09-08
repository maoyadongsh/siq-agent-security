package runtimeaction

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Descriptor is transient: resources and hints contain raw values. Persist only
// ResourceRefs and approved, redacted receipt fields.
type Descriptor struct {
	Tool                     string
	Operation                string
	Effects                  []string
	Resources                []Resource
	ResourceError            error
	Egress                   bool
	Mutating                 bool
	ShellLike                bool
	HighImpactParameterPaths []string
	Hosts                    []string
	Paths                    []string
	FilesystemWriteHint      bool
}

var writeCommand = regexp.MustCompile(`(>>?|\b(cp|mv|tee|rm|chmod|install|mkdir)\b)`)

func Describe(tool string, params map[string]any) Descriptor {
	op, effects := normalizeEffects(tool, params)
	d := Descriptor{Tool: tool, Operation: op, Effects: effects, HighImpactParameterPaths: []string{}}
	fileLike := false
	for _, effect := range effects {
		switch effect {
		case EffectProcessExec:
			d.ShellLike, d.Mutating = true, true
		case EffectFileRead:
			fileLike = true
		case EffectFileWrite, EffectFileDelete:
			fileLike, d.Mutating, d.FilesystemWriteHint = true, true, true
		case EffectMessageSend, EffectNetworkRequest:
			d.Egress = true
			d.Mutating = true
		case EffectDatabaseWrite:
			d.Mutating = true
		}
	}
	text := FlattenStrings(params)
	if d.ShellLike {
		d.FilesystemWriteHint = writeCommand.MatchString(text)
		// Nested command parameters still trigger egress checks. They never erase
		// the unknown effect of an interpreter.
		if networkCommand.MatchString(text) || urlRe.MatchString(text) {
			d.Egress = true
			if !hasEffect(d.Effects, EffectNetworkRequest) {
				d.Effects = append(d.Effects, EffectNetworkRequest)
			}
		}
	}
	d.Resources, d.ResourceError = extractResources(tool, params)
	d.Hosts = extractHosts(d.Egress, fileLike, text)
	d.Paths = extractPaths(fileLike, d.ShellLike, text)
	var walk func(any, string)
	walk = func(value any, pointer string) {
		switch v := value.(type) {
		case map[string]any:
			keys := make([]string, 0, len(v))
			for k := range v {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				p := pointer + "/" + strings.ReplaceAll(strings.ReplaceAll(k, "~", "~0"), "/", "~1")
				if highImpactKey(k, fileLike) {
					d.HighImpactParameterPaths = append(d.HighImpactParameterPaths, p)
				}
				walk(v[k], p)
			}
		case []any:
			for i, x := range v {
				walk(x, pointer+"/"+strconv.Itoa(i))
			}
		}
	}
	walk(params, "")
	sort.Strings(d.HighImpactParameterPaths)
	return d
}

func hasEffect(effects []string, wanted string) bool {
	for _, e := range effects {
		if e == wanted {
			return true
		}
	}
	return false
}

func highImpactKey(key string, fileLike bool) bool {
	switch strings.ToLower(key) {
	case "recipient", "to", "destination_host", "host", "url", "filesystem_target", "database_scope", "credential_ref", "deployment_target", "repo", "branch", "command", "cmd", "account", "identity":
		return true
	case "path", "file_path":
		return fileLike
	default:
		return false
	}
}

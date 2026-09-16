package main

import (
	"errors"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

type launchRuntime struct {
	PID      int64
	LastExit *int64
}

var launchPrintAllowedKeys = map[string]struct{}{
	"active count":                   {},
	"path":                           {},
	"type":                           {},
	"state":                          {},
	"program":                        {},
	"arguments":                      {},
	"stdout path":                    {},
	"stderr path":                    {},
	"inherited environment":          {},
	"default environment":            {},
	"environment":                    {},
	"domain":                         {},
	"umask":                          {},
	"asid":                           {},
	"minimum runtime":                {},
	"exit timeout":                   {},
	"runs":                           {},
	"last exit code":                 {},
	"spawn type":                     {},
	"jetsam priority":                {},
	"jetsam memory limit (active)":   {},
	"jetsam memory limit (inactive)": {},
	"jetsamproperties category":      {},
	"jetsam thread limit":            {},
	"cpumon":                         {},
	"properties":                     {},
	"pid":                            {},
	"immediate reason":               {},
	"forks":                          {},
	"execs":                          {},
	"initialized":                    {},
	"trampolined":                    {},
	"started suspended":              {},
	"proxy started suspended":        {},
	"checked allocations":            {},
	"checked allocations reason":     {},
	"checked allocations flags":      {},
	"resource coalition":             {},
	"jetsam coalition":               {},
}

func launchAgentSource(dir, label string) (string, error) {
	if !launchAgentLabelValid(label) {
		return "", errors.New("launch-agent: invalid expected label")
	}
	source, err := filepath.Abs(filepath.Join(dir, label+".plist"))
	if err != nil {
		return "", err
	}
	source, err = filepath.EvalSymlinks(source)
	if err != nil {
		return "", errors.New("launch-agent: invalid source configuration")
	}
	if !filepath.IsAbs(source) || filepath.Clean(source) != source {
		return "", errors.New("launch-agent: canonical source path required")
	}
	return source, nil
}

func launchPrintTarget(uid int, label string) string {
	return "gui/" + strconv.Itoa(uid) + "/" + label
}

func decodeLaunchPrint(raw string, uid int, label string) (map[string]any, error) {
	invalid := errors.New("launch-agent: invalid or unsupported loaded configuration response")
	if len(raw) == 0 || len(raw) > 65536 || !utf8.ValidString(raw) || !strings.HasSuffix(raw, "\n") {
		return nil, invalid
	}
	lines := strings.Split(strings.TrimSuffix(raw, "\n"), "\n")
	if len(lines) == 0 || lines[0] != launchPrintTarget(uid, label)+" = {" {
		return nil, invalid
	}
	nodes := 0
	i := 1
	var parse func(int) (any, error)
	parse = func(childIndent int) (any, error) {
		var obj map[string]any
		var arr []any
		kind := 0
		ensure := func(next int) error {
			if kind == 0 {
				kind = next
				if next == 1 {
					obj = map[string]any{}
				}
				return nil
			}
			if kind != next {
				return invalid
			}
			return nil
		}
		for i < len(lines) {
			line := lines[i]
			if line == "" {
				i++
				continue
			}
			indent := 0
			for indent < len(line) && line[indent] == '\t' {
				indent++
			}
			if indent < len(line) && line[indent] == ' ' {
				return nil, invalid
			}
			rest := line[indent:]
			if rest == "" || strings.IndexFunc(rest, unicode.IsControl) >= 0 {
				return nil, invalid
			}
			if indent == childIndent-1 && rest == "}" {
				i++
				if kind == 2 {
					return arr, nil
				}
				if kind == 0 {
					return map[string]any{}, nil
				}
				return obj, nil
			}
			if indent != childIndent {
				return nil, invalid
			}
			nodes++
			if nodes > 2048 || childIndent > 8 {
				return nil, invalid
			}
			i++
			if key, ok := strings.CutSuffix(rest, " = {"); ok {
				if err := ensure(1); err != nil {
					return nil, err
				}
				if key == "" || strings.IndexFunc(key, unicode.IsControl) >= 0 {
					return nil, invalid
				}
				if _, exists := obj[key]; exists {
					return nil, invalid
				}
				child, err := parse(childIndent + 1)
				if err != nil {
					return nil, err
				}
				obj[key] = child
				continue
			}
			if key, val, ok := strings.Cut(rest, " = "); ok {
				if err := ensure(1); err != nil {
					return nil, err
				}
				if key == "" || val == "" || strings.IndexFunc(key, unicode.IsControl) >= 0 {
					return nil, invalid
				}
				if _, exists := obj[key]; exists {
					return nil, invalid
				}
				obj[key] = val
				continue
			}
			if key, val, ok := strings.Cut(rest, " => "); ok {
				if err := ensure(1); err != nil {
					return nil, err
				}
				if key == "" || val == "" || strings.IndexFunc(key, unicode.IsControl) >= 0 {
					return nil, invalid
				}
				if _, exists := obj[key]; exists {
					return nil, invalid
				}
				obj[key] = val
				continue
			}
			if err := ensure(2); err != nil {
				return nil, err
			}
			arr = append(arr, rest)
		}
		return nil, invalid
	}
	tree, err := parse(1)
	if err != nil {
		return nil, err
	}
	if i != len(lines) {
		return nil, invalid
	}
	root, ok := tree.(map[string]any)
	if !ok || root == nil {
		return nil, invalid
	}
	return root, nil
}

func stringSlice(v any) ([]string, bool) {
	items, ok := v.([]any)
	if !ok {
		return nil, false
	}
	out := make([]string, len(items))
	for i, item := range items {
		value, ok := item.(string)
		if !ok {
			return nil, false
		}
		out[i] = value
	}
	return out, true
}

func verifyLaunchPrint(wanted, tree map[string]any, uid int, source string) (launchRuntime, error) {
	var zero launchRuntime
	differ := errors.New("launch-agent: loaded configuration differs from signed source")
	unsupported := errors.New("launch-agent: unknown loaded configuration field; compatibility unconfirmed")
	for key := range tree {
		if _, ok := launchPrintAllowedKeys[key]; !ok {
			return zero, unsupported
		}
	}
	for _, key := range []string{"path", "type", "state", "program", "arguments", "stdout path", "stderr path", "environment", "domain", "umask", "exit timeout", "last exit code"} {
		if _, ok := tree[key]; !ok {
			return zero, differ
		}
	}
	if tree["type"] != "LaunchAgent" || tree["path"] != source {
		return zero, differ
	}
	if wanted["RunAtLoad"] != false || wanted["KeepAlive"] != false {
		return zero, unsupported
	}
	argv, ok := stringSlice(wanted["ProgramArguments"])
	if !ok || len(argv) != 2 || argv[1] != "serve" {
		return zero, errors.New("launch-agent: invalid expected label")
	}
	gotArgv, ok := stringSlice(tree["arguments"])
	if !ok || !reflect.DeepEqual(gotArgv, argv) || tree["program"] != argv[0] {
		return zero, differ
	}
	if tree["stdout path"] != wanted["StandardOutPath"] || tree["stderr path"] != wanted["StandardErrorPath"] {
		return zero, differ
	}
	umask, ok := wanted["Umask"].(int64)
	gotUmask, umaskOK := tree["umask"].(string)
	if !ok || !umaskOK || gotUmask != strconv.FormatInt(umask, 8) {
		return zero, differ
	}
	timeout, ok := wanted["ExitTimeOut"].(int64)
	gotTimeout, timeoutOK := tree["exit timeout"].(string)
	if !ok || !timeoutOK || gotTimeout != strconv.FormatInt(timeout, 10) {
		return zero, differ
	}
	domain, _ := tree["domain"].(string)
	prefix := "gui/" + strconv.Itoa(uid)
	if domain != prefix && !strings.HasPrefix(domain, prefix+" ") {
		return zero, errors.New("launch-agent: wrong user domain")
	}
	wantedEnv, ok := wanted["EnvironmentVariables"].(map[string]any)
	stateDir, dirOK := wantedEnv["SIQ_AGENT_SECURITY_STATE_DIR"].(string)
	env, envOK := tree["environment"].(map[string]any)
	gotDir, gotOK := env["SIQ_AGENT_SECURITY_STATE_DIR"].(string)
	if !ok || !dirOK || !envOK || !gotOK || len(wantedEnv) != 1 || gotDir != stateDir {
		return zero, differ
	}
	label, _ := wanted["Label"].(string)
	for key, value := range env {
		text, ok := value.(string)
		if !ok {
			return zero, unsupported
		}
		switch key {
		case "SIQ_AGENT_SECURITY_STATE_DIR":
		case "OSLogRateLimit":
		case "XPC_SERVICE_NAME":
			if text != label {
				return zero, differ
			}
		default:
			return zero, unsupported
		}
	}
	var runtime launchRuntime
	switch tree["state"] {
	case "running":
		pidText, ok := tree["pid"].(string)
		pid, err := strconv.ParseInt(pidText, 10, 64)
		if !ok || err != nil || pid <= 0 || strconv.FormatInt(pid, 10) != pidText {
			return zero, errors.New("launch-agent: invalid running PID")
		}
		runtime.PID = pid
	case "not running":
		if _, present := tree["pid"]; present {
			return zero, errors.New("launch-agent: invalid running PID")
		}
	default:
		return zero, errors.New("launch-agent: invalid or unsupported loaded configuration response")
	}
	code, ok := tree["last exit code"].(string)
	if !ok {
		return zero, errors.New("launch-agent: invalid exit status")
	}
	if code != "(never exited)" {
		status, err := strconv.ParseInt(code, 10, 64)
		if err != nil || strconv.FormatInt(status, 10) != code {
			return zero, errors.New("launch-agent: invalid exit status")
		}
		runtime.LastExit = &status
	}
	return runtime, nil
}

func readLoadedLaunchRuntime(control userSystemctl, uid int, expected []byte, source string) (launchRuntime, error) {
	var zero launchRuntime
	if err := verifyLaunchUserDomain(control, uid); err != nil {
		return zero, err
	}
	wanted, err := decodeLaunchPlist(string(expected))
	if err != nil {
		return zero, err
	}
	label, ok := wanted["Label"].(string)
	if !ok || !launchAgentLabelValid(label) {
		return zero, errors.New("launch-agent: invalid expected label")
	}
	if !filepath.IsAbs(source) || filepath.Clean(source) != source {
		return zero, errors.New("launch-agent: canonical source path required")
	}
	resolved, err := filepath.EvalSymlinks(source)
	if err != nil {
		return zero, errors.New("launch-agent: invalid source configuration")
	}
	raw, err := control("print", launchPrintTarget(uid, label))
	if err != nil {
		return zero, err
	}
	tree, err := decodeLaunchPrint(raw, uid, label)
	if err != nil {
		return zero, errors.New("launch-agent: invalid or unsupported loaded configuration response")
	}
	return verifyLaunchPrint(wanted, tree, uid, resolved)
}

func readLoadedLaunchAgent(control userSystemctl, uid int, expected []byte, source string) (int64, error) {
	runtime, err := readLoadedLaunchRuntime(control, uid, expected, source)
	if err != nil {
		return 0, err
	}
	return runtime.PID, nil
}

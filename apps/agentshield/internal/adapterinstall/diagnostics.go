package adapterinstall

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/product"
)

type DiagnosticCheck struct {
	Code    string `json:"code"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

type Diagnosis struct {
	Platform           string            `json:"platform"`
	ConfigurationState string            `json:"configuration_state"`
	RuntimeState       string            `json:"runtime_state"`
	Checks             []DiagnosticCheck `json:"checks"`
	NextSteps          []string          `json:"next_steps"`
}

func (d *Diagnosis) check(code, status, message string) {
	d.Checks = append(d.Checks, DiagnosticCheck{Code: code, Status: status, Message: message})
}

// Inspect reads installed adapter configuration. It never loads plugin code,
// reads credentials or converts configuration into runtime protection evidence.
func Inspect(opts Options) Diagnosis {
	d := Diagnosis{Platform: opts.Platform, ConfigurationState: "not_installed", RuntimeState: "unverified",
		Checks: []DiagnosticCheck{}, NextSteps: []string{}}
	if opts.Platform == "workbuddy" || opts.Platform == Trae || !known[opts.Platform] {
		d.ConfigurationState = "unsupported"
		d.check("runtime_integration", "not_applicable", "当前尚无经过验证的工具接入路径")
		if opts.Platform == "workbuddy" {
			d.NextSteps = append(d.NextSteps, "WorkBuddy 桌面端需独立实测，CodeBuddy 的结果不能代替。")
		} else {
			d.NextSteps = append(d.NextSteps, "可继续盘点与静态检查；当前不声明工具调用阻断能力。")
		}
		return d
	}
	if opts.Home == "" {
		opts.Home, _ = os.UserHomeDir()
	}
	if opts.Platform == CodeBuddy && validateCodeBuddyConfigDir() != nil {
		d.ConfigurationState = "incomplete"
		d.check("configuration_root", "fail", "平台配置目录覆盖无效或包含符号链接")
		return d
	}
	if err := validateInstance(opts); err != nil {
		d.ConfigurationState = "incomplete"
		d.check("instance_target", "fail", "实例定位已变化，请重新发现")
		return d
	}
	root := opts.configRoot()
	plugin := filepath.Join(root, "plugins", product.PluginDir())
	entry := filepath.Join(plugin, "index.ts")
	if opts.Platform == Hermes {
		entry = filepath.Join(plugin, "plugin.yaml")
	} else if opts.Platform == CodeBuddy {
		entry = filepath.Join(root, "settings.json")
	}
	if _, err := os.Lstat(entry); errors.Is(err, os.ErrNotExist) {
		// Partial installs and legacy roots need repair, not a false fresh state.
		_, pluginErr := os.Lstat(plugin)
		_, legacyErr := os.Lstat(filepath.Join(root, "plugins", product.LegacyName))
		if opts.Platform == CodeBuddy || errors.Is(pluginErr, os.ErrNotExist) && errors.Is(legacyErr, os.ErrNotExist) {
			d.check("adapter_files", "unknown", "尚未发现当前适配器文件")
			d.NextSteps = append(d.NextSteps, "查看接入所需改动并安装适配器，随后验证宿主加载和工具调用。")
			return d
		}
	}
	d.ConfigurationState = "ready"
	switch opts.Platform {
	case Hermes, OpenClaw:
		assets := []string{"plugin.yaml", "__init__.py"}
		if opts.Platform == OpenClaw {
			assets = []string{"package.json", "index.ts", "openclaw.plugin.json"}
		}
		matched := true
		for _, file := range assets {
			current, err := inspectRead(opts.Home, filepath.Join(plugin, file))
			expected, expectedErr := embedded.ReadFile("assets/" + opts.Platform + "/" + file)
			matched = matched && err == nil && expectedErr == nil && bytes.Equal(current, expected)
		}
		if matched {
			d.check("adapter_files", "pass", "适配器文件与当前服务内嵌版本一致")
		} else {
			d.check("adapter_files", "fail", "适配器文件缺失、不可读取，或与当前服务版本不同")
		}
		config := filepath.Join(plugin, "config.json")
		if opts.Platform == OpenClaw {
			config = filepath.Join(root, product.Name+".json")
		}
		inspectConnection(&d, opts, config)
		if opts.Platform == OpenClaw {
			doc, err := inspectJSON(opts.Home, filepath.Join(root, "openclaw.json"))
			if err == nil && openClawRegistered(doc, plugin) {
				d.check("host_registration", "pass", "配置已登记并启用本插件；仍需验证实际加载")
			} else {
				d.check("host_registration", "fail", "宿主配置不可确认，或插件未登记、被禁用、未列入允许范围")
			}
		} else {
			record, recordErr := newestInstanceRecord(opts)
			current, configErr := readImage(opts.Home, filepath.Join(root, "config.yaml"))
			if recordErr == nil && record.NativeOriginal != nil && configErr == nil && record.NativeConfigHash == imageHash(current) {
				digest, cliErr := programDigest(record.NativeCLI)
				if cliErr == nil && digest == record.NativeCLIHash {
					d.check("host_registration", "pass", "原生命令已确认本实例启用配置，摘要仍一致；实际运行仍待验证")
				} else {
					d.check("host_registration", "unknown", "原生程序已变化，请重新检查本实例接入")
				}
			} else {
				d.check("host_registration", "unknown", "Hermes 需要原生验证当前 profile 的插件启用状态")
				d.NextSteps = append(d.NextSteps, "在接入预览中选择目标 profile 并启用插件，再开启新会话验证正常和拒绝调用。")
			}
		}
	case CodeBuddy:
		doc, err := inspectJSON(opts.Home, entry)
		if err == nil && codeBuddyRegistered(doc, opts.Binary) {
			d.check("host_registration", "pass", "配置含本程序的前置和后置工具钩子")
		} else {
			d.check("host_registration", "fail", "未确认前置及后置工具钩子，或命令与当前程序不一致")
		}
		d.check("service_configuration", "unknown", "需在 CodeBuddy 实际进程中验证程序路径、状态目录及服务连接")
	}
	for _, check := range d.Checks {
		if check.Status == "fail" {
			d.ConfigurationState = "incomplete"
			break
		}
		if check.Status == "unknown" {
			d.ConfigurationState = "needs_verification"
		}
	}
	d.check("runtime_verification", "unknown", "此诊断仅检查配置；真实调用证据请查看独立的运行自检记录")
	if d.ConfigurationState == "incomplete" {
		d.NextSteps = append(d.NextSteps, "先检查上方失败项；修复或重新接入后，再验证宿主实际调用。")
	} else {
		d.NextSteps = append(d.NextSteps, "配置检查不等于保护生效；在方便时重启目标会话，完成原生调用自检。")
	}
	return d
}

func inspectRead(home, path string) ([]byte, error) {
	for current := filepath.Clean(path); ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("adapter: diagnostic file unavailable")
		}
		if current == filepath.Clean(home) || filepath.Dir(current) == current {
			break
		}
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 1<<20 {
		return nil, errors.New("adapter: diagnostic file type or size invalid")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, errors.New("adapter: diagnostic read failed")
	}
	defer f.Close()
	info, err = f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > 1<<20 {
		return nil, errors.New("adapter: diagnostic file type or size invalid")
	}
	raw, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 {
		return nil, errors.New("adapter: diagnostic read limit")
	}
	return raw, nil
}

func inspectJSON(home, path string) (map[string]any, error) {
	raw, err := inspectRead(home, path)
	if err != nil {
		return nil, err
	}
	var doc map[string]any
	if json.Unmarshal(raw, &doc) != nil || doc == nil {
		return nil, errors.New("adapter: diagnostic JSON invalid")
	}
	return doc, nil
}

func inspectConnection(d *Diagnosis, opts Options, path string) {
	doc, err := inspectJSON(opts.Home, path)
	tokenField, modeField := "token_path", "enforcement_mode"
	if opts.Platform == OpenClaw {
		tokenField, modeField = "tokenPath", "enforcementMode"
	}
	credentialMatches := doc[tokenField] == filepath.Join(opts.StateDir, "token")
	if _, managed := doc["runtime_identity_id"]; opts.Platform == Hermes && managed {
		credentialMatches = managedConnectionMatches(opts, doc)
	}
	if err == nil && opts.Endpoint != "" && opts.StateDir != "" && opts.Mode != "" &&
		doc["endpoint"] == opts.Endpoint && credentialMatches && doc[modeField] == opts.Mode {
		d.check("service_configuration", "pass", "配置的服务地址、凭据位置及执行模式与当前服务一致；未读取凭据")
	} else {
		d.check("service_configuration", "fail", "无法确认连接配置与当前服务一致，请检查地址、状态目录及模式")
	}
}

func openClawRegistered(doc map[string]any, root string) bool {
	p, ok := doc["plugins"].(map[string]any)
	if !ok {
		return false
	}
	if enabled, exists := p["enabled"]; exists && enabled != true {
		return false
	}
	for _, field := range []string{"allow", "deny"} {
		if value, exists := p[field]; exists {
			list, err := openClawStrings(value, field)
			if err != nil {
				return false
			}
			found := false
			for _, item := range list {
				found = found || item == product.PluginDir()
			}
			if field == "allow" && !found || field == "deny" && found {
				return false
			}
		}
	}
	load, _ := p["load"].(map[string]any)
	paths, err := openClawStrings(load["paths"], "load.paths")
	if err != nil {
		return false
	}
	registered := false
	for _, path := range paths {
		registered = registered || path == root
	}
	entries, _ := p["entries"].(map[string]any)
	entry, _ := entries[product.PluginDir()].(map[string]any)
	return registered && entry["enabled"] == true
}

func codeBuddyRegistered(doc map[string]any, binary string) bool {
	if binary == "" {
		return false
	}
	hooks, _ := doc["hooks"].(map[string]any)
	for _, event := range []string{"PreToolUse", "PostToolUse"} {
		found := false
		entries, _ := hooks[event].([]any)
		for _, value := range entries {
			entry, _ := value.(map[string]any)
			if entry["matcher"] != ".*" {
				continue
			}
			commands, _ := entry["hooks"].([]any)
			for _, command := range commands {
				cmd, _ := command.(map[string]any)
				text, _ := cmd["command"].(string)
				found = found || cmd["type"] == "command" && strings.TrimSpace(text) == binary+" hook codebuddy"
			}
		}
		if !found {
			return false
		}
	}
	return true
}

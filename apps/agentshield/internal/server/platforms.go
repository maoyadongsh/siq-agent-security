package server

import "siq-agent-security/apps/agentshield/internal/adapterinstall"

// PlatformInfo is the console-facing row for one runtime (dev-spec §3.10).
type PlatformInfo struct {
	Name      string                    `json:"name"`
	Detected  bool                      `json:"detected"`
	Adapter   string                    `json:"adapter"`
	Tier      string                    `json:"tier"`
	Note      string                    `json:"note"`
	Diagnosis *adapterinstall.Diagnosis `json:"diagnosis,omitempty"`
}

func (s *Server) platforms() []PlatformInfo {
	home := s.d.Home
	detected := map[string]bool{}
	for _, p := range adapterinstall.Detect(home) {
		detected[p] = true
	}
	names := []string{adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy, "workbuddy", adapterinstall.Trae}
	out := make([]PlatformInfo, 0, len(names))
	for _, name := range names {
		res, err := adapterinstall.Status(adapterinstall.Options{Platform: name, Home: home, StateDir: s.d.Store.Dir})
		adapter := "unknown"
		if err == nil {
			adapter = res.Note
		}
		info := PlatformInfo{Name: name, Detected: detected[name], Adapter: adapter, Tier: "L0"}
		diagnosis := s.diagnoseAdapter(name)
		info.Diagnosis = &diagnosis
		switch name {
		case adapterinstall.Trae:
			info.Note = "审计模式，无法阻断"
			if !detected[name] {
				info.Note = "未发现；即便安装也仅审计、无法阻断"
			}
		case "workbuddy":
			info.Adapter = "unverified"
			info.Note = "WorkBuddy 桌面接入待独立验证；不沿用 CodeBuddy 结果"
		default:
			if diagnosis.ConfigurationState == "incomplete" {
				info.Note = "配置待修复；保护尚未验证"
			} else if diagnosis.ConfigurationState == "ready" {
				info.Note = "配置已就绪；需验证当前实例正常调用与执行前拒绝"
			} else if diagnosis.ConfigurationState == "needs_verification" {
				info.Note = "文件已安装；宿主启用和实际调用待验证"
			} else if detected[name] {
				info.Note = "未装适配器，无法阻断"
			} else {
				info.Note = "未发现平台"
			}
		}
		if name == adapterinstall.Hermes {
			info.Note = "此处显示默认目录；其他 profile 请打开实例管理。" + info.Note
		}
		out = append(out, info)
	}
	osRow := s.openshellPlatform(false)
	out = append(out, osRow)
	return out
}

package server

import "siq-agent-security/apps/agentshield/internal/adapterinstall"

// PlatformInfo is the console-facing row for one runtime (dev-spec §3.10).
type PlatformInfo struct {
	Name     string `json:"name"`
	Detected bool   `json:"detected"`
	Adapter  string `json:"adapter"`
	Tier     string `json:"tier"`
	Note     string `json:"note"`
}

func (s *Server) platforms() []PlatformInfo {
	home := s.d.Home
	detected := map[string]bool{}
	for _, p := range adapterinstall.Detect(home) {
		detected[p] = true
	}
	names := []string{adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy, adapterinstall.Trae}
	out := make([]PlatformInfo, 0, len(names))
	for _, name := range names {
		res, err := adapterinstall.Status(adapterinstall.Options{Platform: name, Home: home, StateDir: s.d.Store.Dir})
		adapter := "unknown"
		if err == nil {
			adapter = res.Note
		}
		info := PlatformInfo{Name: name, Detected: detected[name], Adapter: adapter, Tier: "L0"}
		switch name {
		case adapterinstall.Trae:
			info.Note = "审计模式，无法阻断"
			if !detected[name] {
				info.Note = "未发现；即便安装也仅审计、无法阻断"
			}
		default:
			if adapter == "installed" {
				info.Tier = "L2"
				info.Note = "运行时回执"
			} else if detected[name] {
				info.Note = "未装适配器，无法阻断"
			} else {
				info.Note = "未发现平台"
			}
		}
		out = append(out, info)
	}
	osRow := s.openshellPlatform(false)
	if osRow.Tier != "L3" {
		for i := range out {
			if out[i].Tier == "L2" {
				out[i].Note = "运行时回执 · 仅工具层拦截"
			}
		}
	}
	out = append(out, osRow)
	return out
}

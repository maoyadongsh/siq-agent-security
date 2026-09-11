package server

import (
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func (s *Server) adapterOptions(platform string) adapterinstall.Options {
	bin := s.d.Binary
	if bin == "" {
		bin, _ = os.Executable()
	}
	endpoint := s.d.Endpoint
	if endpoint == "" {
		host, port := s.d.ListenHost, s.d.ListenPort
		if host == "" {
			host = "127.0.0.1"
		}
		if port == 0 {
			port = 47611
		}
		endpoint = "http://" + net.JoinHostPort(host, strconv.Itoa(port))
	}
	return adapterinstall.Options{Platform: platform, Home: s.d.Home,
		StateDir: s.d.Store.Dir, Binary: bin, Endpoint: endpoint, Mode: s.currentMode()}
}

func (s *Server) diagnoseAdapter(platform string) adapterinstall.Diagnosis {
	return s.diagnoseInstance(s.adapterOptions(platform))
}

func (s *Server) adapterDiagnostics(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	rows := []adapterinstall.Diagnosis{}
	for _, platform := range []string{adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy, "workbuddy", adapterinstall.Trae} {
		rows = append(rows, s.diagnoseAdapter(platform))
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"schema_version": "local-adapter-diagnostics/v1", "platform_changes": false, "platforms": rows})
}

func (s *Server) diagnoseInstance(opts adapterinstall.Options) adapterinstall.Diagnosis {
	d := adapterinstall.Inspect(opts)
	id, err := adapterinstall.ConfiguredRuntimeIdentity(opts)
	if id == "" && err == nil {
		return d
	}
	instanceID := hermeshome.Identifier(hermeshome.LegacyRoot(opts.Home))
	if opts.Instance != nil {
		instanceID = opts.Instance.ID
	}
	status, message := "pass", "实例授权当前可用；仍需验证原生调用。"
	if err != nil || s.runtimeIdentities == nil {
		status, message = "fail", "无法读取实例身份，请检查配置并恢复接入。"
	} else if summary, e := s.runtimeIdentities.Summary(id); e != nil || summary.Status != "issued" || summary.InstanceID != instanceID || summary.Platform != opts.Platform || summary.AgentID != "hri-"+strings.TrimPrefix(instanceID, "hi-") {
		status, message = "fail", "实例授权已停用、过期或不可验证；请检查授权后重新接入。"
	}
	d.Checks = append(d.Checks, adapterinstall.DiagnosticCheck{Code: "instance_authority", Status: status, Message: message})
	if status == "fail" {
		d.ConfigurationState = "incomplete"
	}
	return d
}

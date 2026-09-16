package server

import (
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
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
	for _, platform := range []string{adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy, adapterinstall.WorkBuddy, adapterinstall.Trae} {
		rows = append(rows, s.diagnoseAdapter(platform))
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"schema_version": "local-adapter-diagnostics/v1", "platform_changes": false, "platforms": rows})
}

func (s *Server) diagnoseInstance(opts adapterinstall.Options) adapterinstall.Diagnosis {
	d := adapterinstall.Inspect(opts)
	instanceID := adapterinstall.DefaultInstanceID(opts.Home, opts.Platform)
	if opts.Instance != nil {
		instanceID = opts.Instance.ID
	}
	if d.ConfigurationState != "not_installed" && d.ConfigurationState != "unsupported" {
		d.Checks = append(d.Checks, s.backendReachability(opts))
		d.Checks = append(d.Checks, s.hookLoadEvidence(opts.Platform, instanceID))
	}
	id, err := adapterinstall.ConfiguredRuntimeIdentity(opts)
	if id == "" && err == nil {
		return d
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

// backendReachability separates "the configured service is not reachable"
// from configuration drift: the connection document can be intact yet point
// at a service that is no longer this one, or that is not running at all.
func (s *Server) backendReachability(opts adapterinstall.Options) adapterinstall.DiagnosticCheck {
	configured, ok := adapterinstall.ConfiguredEndpoint(opts)
	if !ok {
		if opts.Platform == adapterinstall.CodeBuddy {
			return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "unknown", Message: "CodeBuddy 的服务连接需在其目标进程内验证；此处不读取其运行配置"}
		}
		if opts.Platform == adapterinstall.WorkBuddy {
			return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "unknown", Message: "WorkBuddy 的服务连接需在桌面会话内验证；此处不读取其运行配置，CodeBuddy CLI 不能代替"}
		}
		return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "unknown", Message: "无法读取适配器配置中的服务地址"}
	}
	if sameEndpoint(configured, s.adapterOptions(opts.Platform).Endpoint) {
		return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "pass", Message: "配置的服务地址即当前服务监听地址；本服务运行期间后端可达"}
	}
	switch probeLoopback(configured) {
	case probeReachable:
		return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "unknown", Message: "配置指向另一个正在监听的本机地址，与当前服务不一致；请重新接入"}
	case probeUnreachable:
		return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "fail", Message: "后端服务不可达：配置地址当前无监听服务，请确认服务已启动或重新接入"}
	default:
		return adapterinstall.DiagnosticCheck{Code: "backend_reachability", Status: "unknown", Message: "配置指向非本机地址，此处不探测其可达性；请确认地址后重新接入"}
	}
}

func sameEndpoint(a, b string) bool {
	pa, perr := url.Parse(a)
	pb, qerr := url.Parse(b)
	if perr != nil || qerr != nil {
		return strings.TrimSpace(a) == strings.TrimSpace(b)
	}
	return strings.EqualFold(pa.Scheme, pb.Scheme) && strings.EqualFold(pa.Host, pb.Host)
}

type reachability int

const (
	probeUnreachable reachability = iota
	probeReachable
	probeNotLocal
)

// probeLoopback only probes loopback endpoints; remote addresses are left
// unclassified rather than probed from the management service.
func probeLoopback(endpoint string) reachability {
	parsed, err := url.Parse(endpoint)
	if err != nil || parsed.Host == "" || parsed.Scheme != "http" && parsed.Scheme != "https" {
		return probeNotLocal
	}
	host := parsed.Hostname()
	if host == "localhost" {
		host = "127.0.0.1"
	}
	if ip := net.ParseIP(host); ip == nil || !ip.IsLoopback() {
		return probeNotLocal
	}
	port := parsed.Port()
	if port == "" {
		port = "80"
		if parsed.Scheme == "https" {
			port = "443"
		}
	}
	// Dial the validated literal, never resolve localhost again via DNS.
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(host, port), 500*time.Millisecond)
	if err != nil {
		return probeUnreachable
	}
	_ = conn.Close()
	return probeReachable
}

// hookLoadEvidence joins the latest runtime self-check record of the pinned
// instance, so hook loading is stated on its own instead of hiding inside the
// generic configuration note.
func (s *Server) hookLoadEvidence(platform, instanceID string) adapterinstall.DiagnosticCheck {
	if platform != adapterinstall.Hermes {
		return adapterinstall.DiagnosticCheck{Code: "hook_load", Status: "unknown", Message: "当前平台尚无运行自检路径，钩子加载情况未验证"}
	}
	status := ""
	if s.runtimeChecks != nil && instanceID != "" {
		if records, err := s.runtimeChecks.Latest(instanceID); err == nil && len(records) > 0 {
			status = records[0].Status
		}
	}
	code, message := hookLoadConclusion(status)
	return adapterinstall.DiagnosticCheck{Code: "hook_load", Status: code, Message: message}
}

// hookLoadConclusion maps a runtime self-check status to a hook-load verdict;
// an empty status means no self-check record exists for the instance.
func hookLoadConclusion(status string) (string, string) {
	switch status {
	case "passed":
		return "pass", "最近一次运行自检通过，原生钩子已加载并完成调用验证"
	case "failed":
		return "fail", "最近一次运行自检失败，钩子可能未加载或未生效，请重跑运行自检"
	case "invalidated":
		return "unknown", "运行自检结果已因实例快照变化失效，请重跑运行自检"
	case "preparing", "waiting_host", "running":
		return "unknown", "运行自检正在进行，完成后再查看钩子加载结论"
	case "cancelled":
		return "unknown", "上次运行自检被取消，请重跑运行自检"
	case "":
		return "unknown", "尚无运行自检记录，宿主钩子加载情况未验证"
	default:
		return "unknown", "最近一次运行自检未得出有效结论，请重跑运行自检"
	}
}

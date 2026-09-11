package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdAdapter(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("adapter: usage: %s adapter install|uninstall|status|preview|recover|instances [platform] [install|uninstall] [--instance ID] [--enable-native]", product.Name)
	}
	action := args[0]
	rest := []string{}
	instanceID := ""
	nativeEnable := false
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--instance":
			i++
			if i >= len(args) {
				return fmt.Errorf("adapter: --instance requires ID")
			}
			instanceID = args[i]
		case "--enable-native":
			nativeEnable = true
		default:
			if strings.HasPrefix(args[i], "--") {
				return fmt.Errorf("adapter: unknown option")
			}
			rest = append(rest, args[i])
		}
	}

	dir, err := stateDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	if action != "preview" && action != "instances" {
		st, err = state.Open(dir)
		if err != nil {
			return err
		}
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	bin, err := os.Executable()
	if err != nil {
		return err
	}
	bin, _ = filepath.Abs(bin)
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	roots := hermeshome.Options{Home: home, Override: os.Getenv("HERMES_HOME"), LocalAppData: os.Getenv("LOCALAPPDATA")}
	if action == "instances" {
		if len(rest) != 1 || rest[0] != "hermes" {
			return fmt.Errorf("adapter: instances requires hermes")
		}
		type row struct {
			ID        string `json:"instance_id"`
			Name      string `json:"name"`
			ConfigDir string `json:"config_dir"`
			Active    bool   `json:"active"`
		}
		report := hermeshome.Scan(roots)
		rows := []row{}
		for _, root := range report.Roots {
			rows = append(rows, row{ID: root.ID, Name: root.Name, ConfigDir: root.Path, Active: root.Active})
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"instances": rows, "issues": report.Issues})
	}
	if nativeEnable && instanceID == "" {
		return fmt.Errorf("adapter: --enable-native requires explicit --instance from adapter instances hermes")
	}

	from := product.Env(product.EnvAdaptersDir, product.EnvAdaptersDirOld)
	if from == "" {
		from = findAdaptersRuntime()
	}

	var platforms []string
	if len(rest) == 0 || rest[0] == "auto" {
		platforms = adapterinstall.Detect(home)
		if action != "status" && len(platforms) == 0 {
			return fmt.Errorf("adapter: no platform config dirs found under %s; pass openclaw|hermes|codebuddy|trae", home)
		}
		if action == "status" && len(platforms) == 0 {
			platforms = []string{adapterinstall.OpenClaw, adapterinstall.Hermes, adapterinstall.CodeBuddy, adapterinstall.Trae}
		}
	} else {
		platforms = []string{rest[0]}
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	var out []adapterinstall.Result
	var previews []adapterinstall.PlanView
	for _, p := range platforms {
		opts := adapterinstall.Options{
			Platform: p, Home: home, StateDir: dir, Binary: bin,
			Endpoint: fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), Mode: cfg.EnforcementMode, From: from,
		}

		opts.NativeEnable = nativeEnable
		opts.NativeCLI = os.Getenv("SIQ_AGENT_SECURITY_HERMES_CLI")
		if instanceID != "" {
			if p != "hermes" {
				return fmt.Errorf("adapter: instance selection requires hermes")
			}
			root, err := hermeshome.Resolve(roots, instanceID)
			if err != nil {
				return err
			}
			opts = adapterinstall.WithHermesInstance(opts, root)
		}
		var res *adapterinstall.Result
		switch action {
		case "preview":
			previewAction := "install"
			if len(rest) > 1 {
				previewAction = rest[1]
			}
			plan, planErr := adapterinstall.Prepare(opts, previewAction)
			if planErr != nil {
				return planErr
			}
			previews = append(previews, plan.View())
			continue
		case "recover":
			res, err = adapterinstall.RecoverInstance(opts)
		case "install":
			res, err = adapterinstall.Install(opts)
		case "uninstall":
			res, err = adapterinstall.Uninstall(opts)
		case "status":
			res, err = adapterinstall.Status(opts)
		default:
			return fmt.Errorf("adapter: unknown action %q", action)
		}
		if err != nil {
			return err
		}
		out = append(out, *res)
	}
	if action == "preview" {
		if len(previews) == 1 {
			return enc.Encode(previews[0])
		}
		return enc.Encode(previews)
	}
	if len(out) == 1 {
		return enc.Encode(out[0])
	}
	return enc.Encode(out)
}

func findAdaptersRuntime() string {
	wd, err := os.Getwd()
	if err != nil {
		return ""
	}
	for d := wd; ; d = filepath.Dir(d) {
		p := filepath.Join(d, "adapters", "runtime")
		if st, err := os.Stat(p); err == nil && st.IsDir() {
			return p
		}
		next := filepath.Dir(d)
		if next == d {
			return ""
		}
	}
}

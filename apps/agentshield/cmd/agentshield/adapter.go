package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdAdapter(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("adapter: usage: %s adapter install|uninstall|status [platform]", product.Name)
	}
	action := args[0]
	rest := args[1:]
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
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
	for _, p := range platforms {
		opts := adapterinstall.Options{
			Platform: p, Home: home, StateDir: dir, Binary: bin,
			Endpoint: fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), Mode: cfg.EnforcementMode, From: from,
		}
		var res *adapterinstall.Result
		switch action {
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

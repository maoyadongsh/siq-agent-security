package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
)

func cmdSetup(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("setup", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	openUI := fs.Bool("open-ui", false, "open local management page after readiness")
	confirm := fs.Bool("confirm-setup", false, "initialize and start a user background service")
	runtimeOnly := fs.Bool("runtime", false, "register only for the current user session")
	port := fs.Int("port", 0, "initial local port")
	if err := fs.Parse(args); err != nil {
		return err
	}
	explicit := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "port" {
			explicit = true
		}
	})
	if !*confirm || fs.NArg() != 0 || *port < 0 || *port > 65535 || (explicit && *port == 0) {
		return errors.New("请使用 setup --confirm-setup [--port 1..65535] [--runtime] 初始化并启动本机管理服务")
	}
	if runtime.GOOS != "linux" {
		return errors.New("setup: 当前后台整合入口仅支持 Linux；可使用 start 前台运行")
	}
	if _, err := runUserSystemctl("show", "--property=Version"); err != nil {
		return errors.New("setup: systemd 用户服务不可用；请在用户登录会话中重试，或使用 start 前台运行")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	client := localClient()
	defer client.CloseIdleConnections()
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	if _, healthErr := probeLocalInstance(client, endpoint, st); healthErr == nil {
		if explicit && *port != cfg.Port {
			return errors.New("setup: requested port differs from existing configuration")
		}
		var unit bytes.Buffer
		if err := cmdServiceUnit(nil, &unit); err != nil {
			return err
		}
		_, props, err := ownedService(st, unit.Bytes(), runUserSystemctl)
		if err != nil {
			return err
		}
		expected := "linked"
		if *runtimeOnly {
			expected = "linked-runtime"
		}
		enabled := "enabled"
		if *runtimeOnly {
			enabled = "enabled-runtime"
		}
		if !serviceRunning(props) || (props["UnitFileState"] != expected && props["UnitFileState"] != enabled) {
			return errors.New("setup: existing instance is not the requested managed service")
		}
	} else {
		initArgs := []string{}
		if explicit {
			initArgs = []string{"--port", strconv.Itoa(*port)}
		}
		if err := cmdInitialize(initArgs, io.Discard); err != nil {
			return fmt.Errorf("setup: 初始化未完成: %w", err)
		}
		registerArgs := []string{}
		if *runtimeOnly {
			registerArgs = []string{"--runtime"}
		}
		if err := cmdServiceRegister(registerArgs, io.Discard); err != nil {
			return fmt.Errorf("setup: 注册未完成，保留本机配置，可排查后重试: %w", err)
		}
		if err := cmdServiceControl("start", nil, io.Discard); err != nil {
			return fmt.Errorf("setup: 启动未确认，请检查 service-status: %w", err)
		}
		cfg, err = st.LoadConfig()
		if err != nil {
			return err
		}
		endpoint = fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	}
	_, err = fmt.Fprintf(out, "本机管理服务已就绪：%s/\n首次连接请运行 siq-agent-security pair 获取配对码。登录自启可用 service-login 管理；智能体权限请在管理页面确认。\n", endpoint)
	if err != nil {
		return err
	}
	if *openUI {
		return cmdUI(nil, out)
	}
	return nil
}

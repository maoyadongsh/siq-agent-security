package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
)

type userSetupActions struct {
	preflight  func() error
	port       func() (int, error)
	health     func() error
	initialize func([]string) error
	register   func() error
	start      func() error
	open       func(io.Writer) error
}

func nativeLocalSetup() userSetupActions {
	store := func() (*state.Store, error) {
		dir, err := state.DefaultDir()
		return &state.Store{Dir: dir}, err
	}
	return userSetupActions{
		port: func() (int, error) {
			st, err := store()
			if err != nil {
				return 0, err
			}
			cfg, err := st.LoadConfig()
			return cfg.Port, err
		},
		health: func() error {
			st, err := store()
			if err != nil {
				return err
			}
			cfg, err := st.LoadConfig()
			if err != nil {
				return err
			}
			client := localClient()
			defer client.CloseIdleConnections()
			_, err = probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st)
			return err
		},
		initialize: func(args []string) error { return cmdInitialize(args, io.Discard) },
		open:       func(out io.Writer) error { return cmdUI(nil, out) },
	}
}

func nativeLaunchSetup() userSetupActions {
	actions := nativeLocalSetup()
	actions.preflight = func() error { return verifyLaunchUserDomain(runUserLaunchctl, os.Getuid()) }
	actions.register = func() error { return cmdLaunchAgentRegister(nil, io.Discard) }
	actions.start = func() error { return cmdLaunchAgentStart([]string{"--confirm-start"}, io.Discard) }
	return actions
}

func setupLaunchAgent(port int, explicit, openUI bool, out io.Writer, actions userSetupActions) error {
	return setupUserService(port, explicit, openUI, out, actions, "macOS GUI 用户域", "launch-agent-status")
}

func setupUserService(port int, explicit, openUI bool, out io.Writer, actions userSetupActions, manager, status string) error {
	if err := actions.preflight(); err != nil {
		return fmt.Errorf("setup: %s 未确认: %w", manager, err)
	}
	currentPort, err := actions.port()
	if err != nil {
		return err
	}
	if actions.health() == nil {
		if explicit && port != currentPort {
			return errors.New("setup: requested port differs from existing configuration")
		}
	} else {
		var args []string
		if explicit {
			args = []string{"--port", strconv.Itoa(port)}
		}
		if err := actions.initialize(args); err != nil {
			return fmt.Errorf("setup: 初始化未完成: %w", err)
		}
		if err := actions.register(); err != nil {
			return fmt.Errorf("setup: %s 注册未完成，保留配置供重试: %w", manager, err)
		}
	}
	if err := actions.start(); err != nil {
		return fmt.Errorf("setup: 启动未确认，请检查 %s: %w", status, err)
	}
	currentPort, err = actions.port()
	if err != nil {
		return err
	}
	if err := actions.health(); err != nil {
		return fmt.Errorf("setup: 当前实例健康未确认: %w", err)
	}
	if _, err := fmt.Fprintf(out, "本机管理服务已就绪：http://127.0.0.1:%d/\n首次连接可在页面选择“通过智能体连接”，将连接请求交给已安装的 SIQ Skill；也可使用同一实例的 pair 命令手动配对。管理会话有效期为 24 小时；智能体权限请在管理页面确认。\n", currentPort); err != nil {
		return err
	}
	if openUI {
		return actions.open(out)
	}
	return writeConsoleAccessGuide(out, currentPort)
}

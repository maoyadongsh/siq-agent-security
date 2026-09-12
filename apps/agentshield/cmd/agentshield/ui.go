package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/state"
	"time"
)

func cmdUI(args []string, out io.Writer) error { return localUI(args, out, openLocalBrowser) }
func localUI(args []string, out io.Writer, open func(string) error) error {
	printOnly := len(args) == 1 && args[0] == "--print"
	if len(args) != 0 && !printOnly {
		return errors.New("ui: expected only optional --print")
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
	if cfg.Port < 1 || cfg.Port > 65535 {
		return errors.New("ui: invalid configured port")
	}
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	client := localClient()
	defer client.CloseIdleConnections()
	if _, err := probeLocalInstance(client, endpoint, st); err != nil {
		return err
	}
	address := endpoint + "/"
	if _, err := fmt.Fprintln(out, address); err != nil {
		return err
	}
	if printOnly {
		return nil
	}
	if err := open(address); err != nil {
		return errors.New("无法打开浏览器；本机服务未停止，请手动打开上方管理地址")
	}
	return nil
}
func browserCommand(goos, address string) (string, []string, error) {
	switch goos {
	case "linux":
		return "xdg-open", []string{address}, nil
	case "darwin":
		return "open", []string{address}, nil
	case "windows":
		return "rundll32.exe", []string{"url.dll,FileProtocolHandler", address}, nil
	default:
		return "", nil, errors.New("unsupported browser launcher")
	}
}
func openLocalBrowser(address string) error {
	name, args, err := browserCommand(runtime.GOOS, address)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, name, args...)
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	command.WaitDelay = time.Second
	return command.Run()
}

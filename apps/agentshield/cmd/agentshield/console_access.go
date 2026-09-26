package main

import (
	"fmt"
	"io"
)

// SSH environment values are hints only, never shell arguments or authority.
func consoleBrowserAvailable(goos string, getenv func(string) string) bool {
	if getenv("SSH_CONNECTION") != "" || getenv("SSH_CLIENT") != "" || getenv("SSH_TTY") != "" {
		return false
	}
	return goos != "linux" || getenv("DISPLAY") != "" || getenv("WAYLAND_DISPLAY") != ""
}

func writeConsoleAccessGuide(out io.Writer, port int) error {
	if port < 1 || port > 65535 {
		return fmt.Errorf("invalid console port")
	}
	_, err := fmt.Fprintf(out, "访问说明：127.0.0.1 指浏览器所在电脑；个人服务只允许本机访问。\n"+
		"浏览器与服务在同一台电脑：打开 http://127.0.0.1:%[1]d/overview\n"+
		"服务装在远程机器：在浏览器所在电脑运行以下模板（先替换 SSH_USER@SSH_HOST 为你实际使用的 SSH 登录目标）：\n"+
		"ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:%[1]d:127.0.0.1:%[1]d SSH_USER@SSH_HOST\n"+
		"保持 SSH 终端打开，再访问 http://127.0.0.1:%[1]d/overview。需要已有 SSH 访问权限；不要把该地址改成服务器 IP。\n"+
		"转发端口应与服务端口一致；若已占用，不要结束未知进程。智能体确认连接时应在服务机器上使用同一实例和状态目录。\n", port)
	return err
}

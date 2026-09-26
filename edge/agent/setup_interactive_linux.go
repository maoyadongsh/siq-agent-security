//go:build linux

package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"syscall"
	"unsafe"

	"siq-agent-security/edge/agent/installplan"
)

var errInteractive = errors.New("enterprise_interactive_confirmation_required")

func terminalState(file *os.File) (syscall.Termios, error) {
	var value syscall.Termios
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), syscall.TCGETS, uintptr(unsafe.Pointer(&value)))
	if errno != 0 {
		return value, errInteractive
	}
	return value, nil
}

func setTerminalState(file *os.File, value *syscall.Termios) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), syscall.TCSETS, uintptr(unsafe.Pointer(value)))
	if errno != 0 {
		return errInteractive
	}
	return nil
}

// Reading one byte at a time prevents a buffered confirmation reader from
// consuming the following secret line. This function is used once per CLI run.
func readConfirmation(input io.Reader) (string, error) {
	var out strings.Builder
	var one [1]byte
	for out.Len() <= 16 {
		n, err := input.Read(one[:])
		if n == 1 {
			if one[0] == '\n' {
				return out.String(), nil
			}
			out.WriteByte(one[0])
		}
		if err != nil {
			return "", errInteractive
		}
		if n == 0 {
			return "", errInteractive
		}
	}
	return "", errInteractive
}

func confirmInteractivePlan(ctx context.Context, input io.Reader, output io.Writer, plan *installplan.Plan, start bool) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	var text strings.Builder
	fmt.Fprintf(&text, "企业资产发现安装确认\n组织：%q\n环境：%q\n控制面：%q\n平台：Linux/%s\n", plan.TenantID, plan.EnvironmentID, plan.ControlPlaneOrigin, plan.TargetArch)
	for _, connector := range plan.Connectors {
		fmt.Fprintf(&text, "采集器：%q\n目录：%q\n文件：%q\n", connector.ID, connector.Scope.Roots, connector.Scope.Include)
	}
	fmt.Fprintf(&text, "启动当前用户后台服务：%t（不启用 linger、不提权）\n", start)
	text.WriteString("此确认仅允许所示范围的资产发现，不授予智能体业务权限。制品仍须通过发行验签。\n确认请输入 yes；其他输入取消 [默认取消]：")
	if _, err := io.WriteString(output, text.String()); err != nil {
		return errInteractive
	}
	type response struct {
		text string
		err  error
	}
	done := make(chan response, 1)
	go func() { value, err := readConfirmation(input); done <- response{value, err} }()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case value := <-done:
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if value.err != nil || strings.TrimSuffix(value.text, "\r") != "yes" {
			return errInteractive
		}
		return nil
	}
}

func readInteractiveEnrollment(ctx context.Context, input *os.File, output io.Writer) (code string, err error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	original, err := terminalState(input)
	if err != nil {
		return "", err
	}
	private := original
	private.Lflag &^= syscall.ECHO | syscall.ECHONL
	if err := setTerminalState(input, &private); err != nil {
		return "", err
	}
	defer func() {
		if restoreErr := setTerminalState(input, &original); restoreErr != nil {
			code, err = "", restoreErr
		}
		if _, writeErr := io.WriteString(output, "\n"); writeErr != nil {
			code, err = "", errInteractive
		}
	}()
	if _, err := io.WriteString(output, "请输入一次性注册码（输入不回显）："); err != nil {
		return "", errInteractive
	}
	return readEnrollmentCodeContext(ctx, input)
}

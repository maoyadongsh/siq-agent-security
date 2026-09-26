package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"runtime"
	"strings"
	"unicode"
)

type hostObservation struct {
	Source string `json:"source"`
	Status string `json:"status"`
	Value  string `json:"value,omitempty"`
}
type hostInspection struct {
	Schema        string            `json:"schema_version"`
	OS            string            `json:"os"`
	ProcessArch   string            `json:"process_arch"`
	KernelMachine hostObservation   `json:"kernel_machine"`
	Distribution  hostObservation   `json:"distribution"`
	Version       hostObservation   `json:"distribution_version"`
	Product       []hostObservation `json:"product_model"`
	Attested      bool              `json:"hardware_attested"`
	Granted       bool              `json:"business_permissions_granted"`
	Uploaded      bool              `json:"uploaded"`
}

func hostReadStatus(err error) string {
	if errors.Is(err, os.ErrNotExist) {
		return "missing"
	}
	if errors.Is(err, os.ErrPermission) {
		return "permission_denied"
	}
	return "unavailable"
}

var osReleaseToken = regexp.MustCompile(`^[a-zA-Z0-9._-]{1,128}$`)

func inspectHost(read func(string) ([]byte, error), machine string) hostInspection {
	r := hostInspection{Schema: "enterprise-host-inspection/v1", OS: runtime.GOOS, ProcessArch: runtime.GOARCH,
		KernelMachine: hostObservation{Source: "uname.machine", Status: "unavailable"},
		Distribution:  hostObservation{Source: "/etc/os-release:ID", Status: "unavailable"},
		Version:       hostObservation{Source: "/etc/os-release:VERSION_ID", Status: "unavailable"}, Product: []hostObservation{}}
	if osReleaseToken.MatchString(machine) {
		r.KernelMachine.Status = "observed"
		r.KernelMachine.Value = machine
	}
	raw, err := read("/etc/os-release")
	if err != nil {
		r.Distribution.Status = hostReadStatus(err)
		r.Version.Status = hostReadStatus(err)
	} else if len(raw) <= 16<<10 {
		values := map[string]string{}
		duplicate := map[string]bool{}
		for _, line := range strings.Split(string(raw), "\n") {
			key, value, ok := strings.Cut(line, "=")
			if !ok || (key != "ID" && key != "VERSION_ID") {
				continue
			}
			if _, seen := values[key]; seen {
				duplicate[key] = true
			}
			value = strings.TrimSpace(value)
			if len(value) >= 2 && ((value[0] == '"' && value[len(value)-1] == '"') || (value[0] == '\'' && value[len(value)-1] == '\'')) {
				value = value[1 : len(value)-1]
			}
			values[key] = value
		}
		for key, target := range map[string]*hostObservation{"ID": &r.Distribution, "VERSION_ID": &r.Version} {
			if value, ok := values[key]; !ok {
				target.Status = "missing"
			} else if !duplicate[key] && osReleaseToken.MatchString(value) {
				target.Status = "observed"
				target.Value = value
			}
		}
	}
	for _, path := range []string{"/sys/class/dmi/id/product_name", "/proc/device-tree/model"} {
		entry := hostObservation{Source: path, Status: "unavailable"}
		raw, err := read(path)
		if err != nil {
			entry.Status = hostReadStatus(err)
		} else if len(raw) <= 16<<10 {
			value := strings.TrimSpace(strings.TrimRight(string(raw), "\x00"))
			valid := len(value) > 0 && len(value) <= 256
			for _, c := range value {
				if unicode.IsControl(c) || c == unicode.ReplacementChar {
					valid = false
				}
			}
			if valid {
				entry.Status = "observed"
				entry.Value = value
			}
		}
		r.Product = append(r.Product, entry)
	}
	return r
}

func printHostInspection(args []string, out io.Writer, read func(string) ([]byte, error), machine string) error {
	if len(args) != 0 {
		return errors.New("inspect-host accepts no arguments")
	}
	return printHostReport(out, inspectHost(read, machine))
}

func printHostReport(out io.Writer, report hostInspection) error {
	encoder := json.NewEncoder(out)
	encoder.SetIndent("", "  ")
	return encoder.Encode(report)
}

func printInstallHostSummary(out io.Writer, report hostInspection) error {
	var text strings.Builder
	fmt.Fprintf(&text, "目标设备本机只读观察（未上传）\n操作系统：%q；当前程序架构：%q\n", report.OS, report.ProcessArch)
	observations := []hostObservation{report.KernelMachine, report.Distribution, report.Version}
	observations = append(observations, report.Product...)
	for _, observation := range observations {
		if observation.Status == "observed" {
			fmt.Fprintf(&text, "来源 %q：%q（本机报告）\n", observation.Source, observation.Value)
		} else {
			fmt.Fprintf(&text, "来源 %q：未观测，状态 %q\n", observation.Source, observation.Status)
		}
	}
	text.WriteString("型号来自本机元数据，未认证硬件；不证明 GPU、OpenShell 或运行时防护可用。环境名称不作为硬件证据。\n")
	_, err := io.WriteString(out, text.String())
	return err
}

package main

import (
	"bytes"
	"errors"
	"os"
	"strings"
	"testing"
)

func TestInstallHostSummaryEvidenceLimitsAndEscaping(t *testing.T) {
	report := inspectHost(func(path string) ([]byte, error) {
		switch path {
		case "/etc/os-release":
			return []byte("ID=ubuntu\nVERSION_ID=24.04\nSECRET=not-for-output\n"), nil
		case "/sys/class/dmi/id/product_name":
			return []byte("DGX Spark"), nil
		default:
			return nil, os.ErrPermission
		}
	}, "aarch64")
	var out bytes.Buffer
	if err := printInstallHostSummary(&out, report); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"未上传", "未认证硬件", "环境名称不作为硬件证据", "DGX Spark", "ubuntu", "permission_denied", "未观测"} {
		if !strings.Contains(out.String(), want) {
			t.Fatal("missing evidence limitation", want)
		}
	}
	if strings.Contains(out.String(), "not-for-output") {
		t.Fatal("unselected field leaked")
	}
	report.Product = []hostObservation{{Source: "fixture", Status: "observed", Value: "\x1b[31m\nforged prompt"}}
	out.Reset()
	if err := printInstallHostSummary(&out, report); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "\x1b") || strings.Contains(out.String(), "\nforged prompt") {
		t.Fatal("terminal injection")
	}
	if printInstallHostSummary(hostSummaryFailWriter{}, report) == nil {
		t.Fatal("output failure ignored")
	}
}

type hostSummaryFailWriter struct{}

func (hostSummaryFailWriter) Write([]byte) (int, error) {
	return 0, errors.New("fixture output unavailable")
}

func TestHostInspectionBoundedSourcesAndNoAttestation(t *testing.T) {
	var paths []string
	r := inspectHost(func(path string) ([]byte, error) {
		paths = append(paths, path)
		if path == "/etc/os-release" {
			return []byte("ID=ubuntu\nVERSION_ID=\"24.04\"\nSECRET=private\n"), nil
		}
		if path == "/sys/class/dmi/id/product_name" {
			return []byte("DGX Spark\n"), nil
		}
		return nil, os.ErrNotExist
	}, "aarch64")
	if len(paths) != 3 || r.Distribution.Value != "ubuntu" || r.Version.Value != "24.04" || r.Product[0].Value != "DGX Spark" || r.Product[1].Status != "missing" {
		t.Fatal(r)
	}
	if r.Attested || r.Granted || r.Uploaded {
		t.Fatal("metadata became authority")
	}
	if r.KernelMachine.Value != "aarch64" || r.ProcessArch == "" {
		t.Fatal("architecture sources missing")
	}
}

func TestHostInspectionErrorsAndUntrustedText(t *testing.T) {
	for _, c := range []struct {
		name, raw string
		err       error
		status    string
	}{
		{"missing", "", os.ErrNotExist, "missing"},
		{"permission", "", os.ErrPermission, "permission_denied"},
		{"unknown", "", errors.New("private diagnostic"), "unavailable"},
		{"shell", "ID=$(touch /tmp/no-execute)", nil, "unavailable"},
		{"duplicate", "ID=ubuntu\nID=debian", nil, "unavailable"},
		{"oversized", strings.Repeat("x", (16<<10)+1), nil, "unavailable"},
		{"control", "ID=bad\tvalue", nil, "unavailable"},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := inspectHost(func(path string) ([]byte, error) {
				if path != "/etc/os-release" {
					return nil, os.ErrNotExist
				}
				return []byte(c.raw), c.err
			}, "bad\nmachine")
			if r.Distribution.Status != c.status || r.Distribution.Value != "" || r.KernelMachine.Status != "unavailable" {
				t.Fatal(r)
			}
		})
	}
}

func TestInspectHostRejectsArgumentsBeforeReading(t *testing.T) {
	var output bytes.Buffer
	err := printHostInspection([]string{"--upload"}, &output, func(string) ([]byte, error) { t.Fatal("read before rejecting args"); return nil, nil }, "")
	if err == nil || output.Len() != 0 {
		t.Fatal("unexpected output")
	}
}

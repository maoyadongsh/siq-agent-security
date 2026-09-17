package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func TestDarwinPathSpellingAndExclusivePublish(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("macOS volume spelling and O_EXCL publication")
	}
	root := t.TempDir()
	nfc := filepath.Join(root, "café 中文")
	if err := os.Mkdir(nfc, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", nfc)
	if err := cmdInitialize([]string{"--port", "47621"}, io.Discard); err != nil {
		t.Fatal(err)
	}
	var status bytes.Buffer
	if err := cmdStateStatus(nil, &status); err != nil {
		t.Fatal(err)
	}
	var result struct {
		Compatible bool   `json:"compatible"`
		Status     string `json:"status"`
	}
	if err := json.Unmarshal(status.Bytes(), &result); err != nil || !result.Compatible || result.Status != state.CompatStatusOK {
		t.Fatalf("NFC/space/CJK state dir rejected: %s %v", status.Bytes(), err)
	}

	nfd := filepath.Join(root, "cafe\u0301 中文")
	_, nfdErr := os.Lstat(nfd)
	nfcInfo, _ := os.Lstat(nfc)
	nfdInfo, _ := os.Lstat(nfd)
	aliased := nfdErr == nil && nfcInfo != nil && nfdInfo != nil && os.SameFile(nfcInfo, nfdInfo)
	t.Logf("unicode_alias nfd_lstat=%v same_file=%v nfc_utf8=%v", nfdErr, aliased, utf8.ValidString(nfc))
	if aliased {
		t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", nfd)
		status.Reset()
		if err := cmdStateStatus(nil, &status); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(status.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		nfcID, _ := stateformat.DirectoryID(nfc)
		nfdID, _ := stateformat.DirectoryID(nfd)
		if nfcID == nfdID && !result.Compatible {
			t.Fatal("canonical DirectoryID matched but status failed closed")
		}
		if nfcID != nfdID && (result.Compatible || result.Status != state.CompatStatusCorrupt) {
			t.Fatalf("divergent Unicode spellings must stay fail-closed: %s ids %s %s", status.Bytes(), nfcID, nfdID)
		}
	}

	upper := filepath.Join(root, "CAFÉ 中文")
	if _, err := os.Lstat(upper); err == nil {
		t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", upper)
		status.Reset()
		if err := cmdStateStatus(nil, &status); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(status.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		nfcID, _ := stateformat.DirectoryID(nfc)
		upperID, _ := stateformat.DirectoryID(upper)
		if nfcID != upperID && result.Compatible {
			t.Fatal("case-alias path accepted as the original directory binding")
		}
	}

	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", nfc)

	marker := filepath.Join(nfc, "exclusive-probe.json")
	if err := os.WriteFile(marker, []byte(`{"keep":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(marker)
	f, err := statefs.OpenFile(marker, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err == nil {
		f.Close()
		t.Fatal("O_EXCL replaced an existing file")
	}
	if !errors.Is(err, os.ErrExist) {
		t.Fatal("exclusive create error", err)
	}
	after, _ := os.ReadFile(marker)
	if !bytes.Equal(before, after) {
		t.Fatal("existing exclusive target mutated")
	}

	xattrFile := filepath.Join(nfc, "config.json")
	if err := exec.Command("xattr", "-w", "siq.test", "keep", xattrFile).Run(); err != nil {
		t.Log("xattr write skipped", err)
	} else {
		if err := os.Chmod(xattrFile, 0600); err != nil {
			t.Fatal(err)
		}
		out, err := exec.Command("xattr", "-p", "siq.test", xattrFile).CombinedOutput()
		if err != nil || !strings.Contains(string(out), "keep") {
			t.Fatal("chmod dropped xattr; N01 still does not copy xattr", string(out), err)
		}
	}
	if err := exec.Command("chmod", "+a", "everyone deny write", xattrFile).Run(); err != nil {
		t.Log("ACL write skipped", err)
	} else {
		if err := os.Chmod(xattrFile, 0600); err != nil {
			t.Fatal(err)
		}
		listing, err := exec.Command("ls", "-le", xattrFile).CombinedOutput()
		if err != nil || !strings.Contains(string(listing), "deny write") {
			t.Fatal("chmod dropped ACL; N01 still does not copy ACL", string(listing), err)
		}
	}

	const sentinel = "PRIVATE_RAW_CONTENT_MUST_NOT_ENTER_CLI_EXPORT"
	rawDir := filepath.Join(nfc, "raw-task-content")
	if err := os.MkdirAll(rawDir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(rawDir, "raw-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json"), []byte(sentinel), 0600); err != nil {
		t.Fatal(err)
	}
	bundle := filepath.Join(t.TempDir(), "bundle.json")
	if err := cmdExport([]string{"--out", bundle}); err != nil {
		t.Fatal(err)
	}
	exported, err := os.ReadFile(bundle)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(exported, []byte(sentinel)) || bytes.Contains(exported, []byte("ciphertext_base64")) {
		t.Fatal("export leaked raw content or ciphertext")
	}
}

func TestDarwinReadOnlyCaseSensitiveAndCrossVolume(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("macOS volume boundaries")
	}
	root := t.TempDir()
	ro := filepath.Join(root, "readonly")
	if err := os.Mkdir(ro, 0700); err != nil {
		t.Fatal(err)
	}
	occupant := filepath.Join(ro, "keep.json")
	if err := os.WriteFile(occupant, []byte("user"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(ro, 0555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(ro, 0700) })
	f, err := statefs.OpenFile(filepath.Join(ro, "new.json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err == nil {
		f.Close()
		t.Fatal("created file in read-only directory")
	}
	raw, _ := os.ReadFile(occupant)
	if string(raw) != "user" {
		t.Fatal("read-only occupant changed")
	}

	readonlyMount, ok := attachTestVolume(t, "1m", "APFS", true)
	if ok {
		_, err = statefs.OpenFile(filepath.Join(readonlyMount, "siq.json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err == nil {
			t.Fatal("wrote onto a read-only volume")
		}
	}

	csMount, ok := attachTestVolume(t, "8m", "Case-sensitive APFS", false)
	if ok {
		lower := filepath.Join(csMount, "instance")
		upper := filepath.Join(csMount, "Instance")
		if err := os.Mkdir(lower, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.Mkdir(upper, 0700); err != nil {
			t.Fatal(err)
		}
		a, _ := os.Lstat(lower)
		b, _ := os.Lstat(upper)
		if os.SameFile(a, b) {
			t.Fatal("case-sensitive volume collapsed Instance/instance")
		}
		lowerID, err := stateformat.DirectoryID(lower)
		if err != nil {
			t.Fatal(err)
		}
		upperID, err := stateformat.DirectoryID(upper)
		if err != nil {
			t.Fatal(err)
		}
		if lowerID == upperID {
			t.Fatal("case-sensitive siblings shared DirectoryID")
		}
		t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", lower)
		if err := cmdInitialize([]string{"--port", "47622"}, io.Discard); err != nil {
			t.Fatal(err)
		}
		var lowerStatus bytes.Buffer
		if err := cmdStateStatus(nil, &lowerStatus); err != nil {
			t.Fatal(err)
		}
		var lowerResult struct {
			Compatible bool   `json:"compatible"`
			Status     string `json:"status"`
		}
		if err := json.Unmarshal(lowerStatus.Bytes(), &lowerResult); err != nil || !lowerResult.Compatible {
			t.Fatal("case-sensitive init rejected", lowerStatus.String(), err)
		}
		if _, err := os.Lstat(filepath.Join(upper, "state-format.json")); !os.IsNotExist(err) {
			t.Fatal("init on instance leaked a marker into Instance")
		}
		t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", upper)
		if err := cmdInitialize([]string{"--port", "47623"}, io.Discard); err != nil {
			t.Fatal(err)
		}
		var upperStatus bytes.Buffer
		if err := cmdStateStatus(nil, &upperStatus); err != nil {
			t.Fatal(err)
		}
		var upperResult struct {
			Compatible bool   `json:"compatible"`
			Status     string `json:"status"`
		}
		if err := json.Unmarshal(upperStatus.Bytes(), &upperResult); err != nil || !upperResult.Compatible {
			t.Fatal("independent case-sensitive sibling refused init", upperStatus.String(), err)
		}
		lowerIDAfter, _ := stateformat.DirectoryID(lower)
		upperIDAfter, _ := stateformat.DirectoryID(upper)
		if lowerIDAfter == upperIDAfter {
			t.Fatal("two case-sensitive instances collapsed to one DirectoryID")
		}
		lowerInst, err := os.ReadFile(filepath.Join(lower, "local-instance.json"))
		if err != nil {
			t.Fatal(err)
		}
		upperInst, err := os.ReadFile(filepath.Join(upper, "local-instance.json"))
		if err != nil {
			t.Fatal(err)
		}
		if bytes.Equal(lowerInst, upperInst) {
			t.Fatal("case-sensitive siblings shared instance identity")
		}
	}

	if writable, ok := attachTestVolume(t, "8m", "APFS", false); ok {
		src := filepath.Join(t.TempDir(), "src.json")
		if err := os.WriteFile(src, []byte(`{"keep":true}`), 0600); err != nil {
			t.Fatal(err)
		}
		err := statefs.Link(src, filepath.Join(writable, "dst.json"))
		if err == nil {
			t.Fatal("cross-volume exclusive link succeeded")
		}
		if !errors.Is(err, syscall.EXDEV) && !strings.Contains(strings.ToLower(err.Error()), "cross-device") {
			t.Log("cross-volume link refused without EXDEV wrapping", err)
		}
		if _, err := os.Lstat(filepath.Join(writable, "dst.json")); !os.IsNotExist(err) {
			t.Fatal("cross-volume failure left a destination occupant")
		}
		big := make([]byte, 8<<20)
		hf, err := statefs.OpenFile(filepath.Join(writable, "huge.json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			t.Fatal(err)
		}
		_, writeErr := hf.Write(big)
		_ = hf.Close()
		if writeErr == nil {
			t.Log("8MiB write fit on the 8MiB test volume; ENOSPC not forced")
		} else {
			t.Log("capacity write refused", writeErr)
		}
	}
}

func attachTestVolume(t *testing.T, size, fs string, readonly bool) (string, bool) {
	t.Helper()
	image := filepath.Join(t.TempDir(), "vol.dmg")
	name := fmt.Sprintf("S%d", time.Now().UnixNano()%100000000)
	create := exec.Command("hdiutil", "create", "-size", size, "-fs", fs, "-volname", name, image)
	if out, err := create.CombinedOutput(); err != nil {
		t.Log("hdiutil create skipped", fs, err, string(out))
		return "", false
	}
	mount := filepath.Join(t.TempDir(), "mnt")
	if err := os.Mkdir(mount, 0700); err != nil {
		t.Fatal(err)
	}
	args := []string{"attach", "-nobrowse", "-mountpoint", mount, image}
	if readonly {
		args = []string{"attach", "-nobrowse", "-readonly", "-mountpoint", mount, image}
	}
	attach := exec.Command("hdiutil", args...)
	if out, err := attach.CombinedOutput(); err != nil {
		t.Log("hdiutil attach skipped", fs, err, string(out))
		return "", false
	}
	t.Cleanup(func() { _ = exec.Command("hdiutil", "detach", mount, "-quiet", "-force").Run() })
	info, err := os.Lstat(mount)
	if err != nil || !info.IsDir() {
		t.Log("test volume not mounted", mount)
		return "", false
	}
	return mount, true
}

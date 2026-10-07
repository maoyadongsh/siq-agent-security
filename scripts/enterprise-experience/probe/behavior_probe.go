// Static Linux ELF for ADR-058. Reports observations, never a policy verdict.
// Build explicitly with CGO_ENABLED=0; no modules or third-party dependencies.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type observation struct {
	SchemaVersion  string `json:"schema_version"`
	VerificationID string `json:"verification_id"`
	Nonce          string `json:"nonce"`
	Endpoint       string `json:"endpoint"`
	ProgramPath    string `json:"program_path"`
	ProgramSHA256  string `json:"program_sha256"`
	UID            int    `json:"uid"`
	Outcome        string `json:"outcome"`
	ElapsedMS      int64  `json:"elapsed_ms"`
}

func positive(value string, low, high int) (int, error) {
	n, err := strconv.Atoi(value)
	if err != nil || n < low || n > high || strconv.Itoa(n) != value {
		return 0, errors.New("invalid argument")
	}
	return n, nil
}

func classify(err error) string {
	if errors.Is(err, syscall.ECONNREFUSED) {
		return "connection_refused"
	}
	if errors.Is(err, syscall.ECONNRESET) {
		return "connection_reset"
	}
	var networkError net.Error
	if errors.As(err, &networkError) && networkError.Timeout() {
		return "timeout"
	}
	return "probe_error"
}

func probe(endpoint, marker string, timeout time.Duration) string {
	deadline := time.Now().Add(timeout)
	conn, err := (&net.Dialer{Deadline: deadline}).Dial("tcp4", endpoint)
	if err != nil {
		return classify(err)
	}
	defer conn.Close()
	if err = conn.SetDeadline(deadline); err != nil {
		return "probe_error"
	}
	if _, err = io.WriteString(conn, marker); err != nil {
		return classify(err)
	}
	answer := make([]byte, len(marker))
	if _, err = io.ReadFull(conn, answer); err != nil {
		return classify(err)
	}
	if !bytes.Equal(answer, []byte(marker)) {
		return "probe_error"
	}
	return "connected"
}

func observe(args []string) (observation, error) {
	var result observation
	if len(args) != 5 || !regexp.MustCompile(`^opv-[a-f0-9]{32}$`).MatchString(args[0]) ||
		!regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(args[1]) {
		return result, errors.New("invalid argument")
	}
	address, err := netip.ParseAddr(args[2])
	if err != nil || !address.Is4() || address.String() != args[2] {
		return result, errors.New("invalid address")
	}
	port, err := positive(args[3], 1, 65535)
	if err != nil {
		return result, err
	}
	timeout, err := positive(args[4], 100, 10000)
	if err != nil {
		return result, err
	}
	// No setuid/root execution. A trusted observer must separately establish
	// image identity and that this path cannot be replaced by the workload.
	if os.Getuid() <= 0 || os.Getuid() != os.Geteuid() || os.Getgid() != os.Getegid() {
		return result, errors.New("invalid identity")
	}
	if err := verifyProcess(); err != nil {
		return result, err
	}
	path, err := os.Readlink("/proc/self/exe")
	if err != nil || filepath.Clean(path) != path || len(path) > 512 ||
		!regexp.MustCompile(`^/[A-Za-z0-9_./-]+$`).MatchString(path) {
		return result, errors.New("invalid program")
	}
	file, err := os.Open("/proc/self/exe")
	if err != nil {
		return result, errors.New("program unavailable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > 64<<20 {
		return result, errors.New("invalid program")
	}
	header := make([]byte, 4)
	if _, err = io.ReadFull(file, header); err != nil || !bytes.Equal(header, []byte{0x7f, 'E', 'L', 'F'}) {
		return result, errors.New("invalid program")
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return result, errors.New("invalid program")
	}
	hash := sha256.New()
	if size, err := io.Copy(hash, io.LimitReader(file, (64<<20)+1)); err != nil || size != info.Size() {
		return result, errors.New("invalid program")
	}
	result = observation{SchemaVersion: "openshell-behavior-agent/v1", VerificationID: args[0], Nonce: args[1],
		Endpoint: net.JoinHostPort(address.String(), strconv.Itoa(port)), ProgramPath: path,
		ProgramSHA256: hex.EncodeToString(hash.Sum(nil)), UID: os.Getuid()}
	start := time.Now()
	result.Outcome = probe(result.Endpoint, "SIQ-BEHAVIOR/1 "+args[0]+" "+args[1]+"\n", time.Duration(timeout)*time.Millisecond)
	result.ElapsedMS = time.Since(start).Milliseconds()
	if result.ElapsedMS > 11000 {
		return observation{}, errors.New("deadline exceeded")
	}
	return result, nil
}

func verifyProcess() error {
	// Linux PR_SET_NO_NEW_PRIVS only restricts this child; inherited capabilities
	// are not silently dropped or treated as an acceptable execution context.
	if _, _, errno := syscall.AllThreadsSyscall6(syscall.SYS_PRCTL, 38, 1, 0, 0, 0, 0); errno != 0 {
		return errors.New("invalid process")
	}
	file, err := os.Open("/proc/self/status")
	if err != nil {
		return errors.New("invalid process")
	}
	defer file.Close()
	raw, err := io.ReadAll(io.LimitReader(file, 65537))
	if err != nil || len(raw) > 65536 {
		return errors.New("invalid process")
	}
	fields := map[string][]string{}
	for _, line := range strings.Split(string(raw), "\n") {
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		if _, exists := fields[key]; exists {
			return errors.New("invalid process")
		}
		fields[key] = strings.Fields(value)
	}
	for key, value := range map[string]int{"Uid": os.Getuid(), "Gid": os.Getgid()} {
		if len(fields[key]) != 4 {
			return errors.New("invalid process")
		}
		for _, actual := range fields[key] {
			if actual != strconv.Itoa(value) {
				return errors.New("invalid process")
			}
		}
	}
	for _, key := range []string{"CapEff", "CapPrm", "CapAmb"} {
		if len(fields[key]) != 1 {
			return errors.New("invalid process")
		}
		value, err := strconv.ParseUint(fields[key][0], 16, 64)
		if err != nil || value != 0 {
			return errors.New("invalid process")
		}
	}
	if len(fields["NoNewPrivs"]) != 1 || fields["NoNewPrivs"][0] != "1" {
		return errors.New("invalid process")
	}
	return nil
}

func main() {
	result, err := observe(os.Args[1:])
	if err != nil {
		fmt.Fprintln(os.Stderr, "behavior_probe_invalid")
		os.Exit(2)
	}
	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		os.Exit(2)
	}
}

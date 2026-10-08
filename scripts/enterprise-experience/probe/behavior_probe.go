// Static Linux ELF for ADR-058. Reports observations, never a policy verdict.
// Build explicitly with CGO_ENABLED=0; no modules or third-party dependencies.
package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
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
	SchemaVersion  string  `json:"schema_version"`
	VerificationID string  `json:"verification_id"`
	Nonce          string  `json:"nonce"`
	Endpoint       string  `json:"endpoint"`
	ProgramPath    string  `json:"program_path"`
	ProgramSHA256  string  `json:"program_sha256"`
	UID            int     `json:"uid"`
	Outcome        string  `json:"outcome"`
	ElapsedMS      int64   `json:"elapsed_ms"`
	Transport      string  `json:"transport,omitempty"`
	ProxyEndpoint  string  `json:"proxy_endpoint,omitempty"`
	ProxyStatus    *int    `json:"proxy_status,omitempty"`
	ProxyError     *string `json:"proxy_error,omitempty"`
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

// The explicit proxy is an operator-approved numeric endpoint. No environment,
// DNS, redirects, credentials or automatic proxy discovery are consulted.
func probeConnect(proxy, endpoint, marker string, timeout time.Duration) (string, int, string) {
	deadline := time.Now().Add(timeout)
	conn, err := (&net.Dialer{Deadline: deadline}).Dial("tcp4", proxy)
	if err != nil {
		return classify(err), 0, ""
	}
	defer conn.Close()
	if err = conn.SetDeadline(deadline); err != nil {
		return "probe_error", 0, ""
	}
	if _, err = io.WriteString(conn, "CONNECT "+endpoint+" HTTP/1.1\r\nHost: "+endpoint+"\r\n\r\n"); err != nil {
		return classify(err), 0, ""
	}
	// Bound headers independently of the body and preserve all tunneled bytes.
	header := make([]byte, 0, 4096)
	var one [1]byte
	for !bytes.HasSuffix(header, []byte("\r\n\r\n")) {
		if len(header) >= 4096 {
			return "probe_error", 0, "other"
		}
		if _, err = io.ReadFull(conn, one[:]); err != nil {
			return classify(err), 0, ""
		}
		header = append(header, one[0])
	}
	response, err := http.ReadResponse(bufio.NewReader(bytes.NewReader(header)), &http.Request{Method: "CONNECT"})
	if err != nil {
		return "probe_error", 0, "other"
	}
	status := response.StatusCode
	if response.Proto != "HTTP/1.1" || status < 100 || status > 599 || len(response.TransferEncoding) != 0 {
		return "probe_error", 0, "other"
	}
	if status == 403 {
		if response.ContentLength < 1 || response.ContentLength > 4096 || response.Header.Get("Content-Type") != "application/json" {
			return "probe_error", status, "other"
		}
		body := make([]byte, response.ContentLength)
		if _, err = io.ReadFull(conn, body); err != nil {
			return classify(err), status, "other"
		}
		if policyDenied(body, endpoint) {
			return "proxy_denied", status, "policy_denied"
		}
		return "probe_error", status, "other"
	}
	if status != 200 || response.ContentLength > 0 {
		return "probe_error", status, "other"
	}
	if _, err = io.WriteString(conn, marker); err != nil {
		return classify(err), status, ""
	}
	answer := make([]byte, len(marker))
	if _, err = io.ReadFull(conn, answer); err != nil {
		return classify(err), status, ""
	}
	if !bytes.Equal(answer, []byte(marker)) {
		return "probe_error", status, ""
	}
	return "connected", status, ""
}

func policyDenied(body []byte, endpoint string) bool {
	decoder := json.NewDecoder(bytes.NewReader(body))
	token, err := decoder.Token()
	if err != nil || token != json.Delim('{') {
		return false
	}
	fields := map[string]string{}
	for decoder.More() {
		token, err = decoder.Token()
		key, ok := token.(string)
		if err != nil || !ok || (key != "error" && key != "detail") {
			return false
		}
		if _, exists := fields[key]; exists {
			return false
		}
		var value string
		if decoder.Decode(&value) != nil {
			return false
		}
		fields[key] = value
	}
	if token, err = decoder.Token(); err != nil || token != json.Delim('}') {
		return false
	}
	if _, err = decoder.Token(); err != io.EOF {
		return false
	}
	return fields["error"] == "policy_denied" && fields["detail"] == "CONNECT "+endpoint+" not permitted by policy"
}

func observe(args []string) (observation, error) {
	var result observation
	if (len(args) != 5 && len(args) != 8) || !regexp.MustCompile(`^opv-[a-f0-9]{32}$`).MatchString(args[0]) ||
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
	proxy := ""
	if len(args) == 8 {
		address, err := netip.ParseAddr(args[6])
		port, portErr := positive(args[7], 1, 65535)
		if args[5] != "http_connect" || err != nil || !address.Is4() || address.String() != args[6] || portErr != nil {
			return result, errors.New("invalid proxy")
		}
		proxy = net.JoinHostPort(address.String(), strconv.Itoa(port))
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
	marker := "SIQ-BEHAVIOR/1 " + args[0] + " " + args[1] + "\n"
	if proxy != "" {
		outcome, status, proxyError := probeConnect(proxy, result.Endpoint, marker, time.Duration(timeout)*time.Millisecond)
		result.SchemaVersion, result.Transport, result.ProxyEndpoint = "openshell-behavior-agent/v2", "http_connect", proxy
		result.Outcome, result.ProxyStatus, result.ProxyError = outcome, &status, &proxyError
	} else {
		result.Outcome = probe(result.Endpoint, marker, time.Duration(timeout)*time.Millisecond)
	}
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

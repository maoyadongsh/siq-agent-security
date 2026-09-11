package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

type localHealth struct {
	SchemaVersion string `json:"schema_version"`
	Product       string `json:"product"`
	Version       string `json:"version"`
	LocalMode     bool   `json:"local_mode"`
	Status        string `json:"status"`
}

func localClient() *http.Client {
	// A proxy must never receive the launcher credential, even if HTTP_PROXY is set.
	return &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{Proxy: nil},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

func decodeLocalResponse(resp *http.Response, out any) error {
	defer resp.Body.Close()
	mediaType, _, err := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	if resp.StatusCode != http.StatusOK || err != nil || mediaType != "application/json" {
		return errors.New("local service returned an unexpected HTTP response; check the port and service version")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8193))
	if err != nil || len(data) > 8192 || json.Unmarshal(data, out) != nil {
		return errors.New("local service returned an invalid response")
	}
	return nil
}

func probeLocalService(client *http.Client, endpoint string) (localHealth, error) {
	var health localHealth
	resp, err := client.Get(endpoint + "/healthz")
	if err != nil {
		return health, errors.New("local service is unreachable; start siq-agent-security serve, then retry")
	}
	if err := decodeLocalResponse(resp, &health); err != nil {
		return health, err
	}
	if health.SchemaVersion != "local-service-health/v1" || health.Product != "siq-agent-security" ||
		!health.LocalMode || health.Status != "ready" || health.Version == "" {
		return localHealth{}, errors.New("this port is not a compatible SIQ local service")
	}
	return health, nil
}

func requestLocalPairing(client *http.Client, endpoint, credential string) (string, error) {
	req, err := http.NewRequest(http.MethodPost, endpoint+"/v1/session/pairing", nil)
	if err != nil {
		return "", errors.New("invalid local endpoint")
	}
	req.Header.Set("Authorization", "Bearer "+credential)
	req.Header.Set("X-SIQ-Local-CLI", "1")
	resp, err := client.Do(req)
	if err != nil {
		return "", errors.New("cannot renew pairing; verify that serve is still running")
	}
	var result struct {
		SchemaVersion string `json:"schema_version"`
		Code          string `json:"code"`
		ExpiresIn     int    `json:"expires_in"`
	}
	if err := decodeLocalResponse(resp, &result); err != nil {
		return "", err
	}
	if result.SchemaVersion != "local-pairing/v1" || result.ExpiresIn != 300 ||
		!regexp.MustCompile(`^[0-9a-f]{4}(-[0-9a-f]{4}){3}$`).MatchString(result.Code) {
		return "", errors.New("local service returned an invalid pairing response")
	}
	return result.Code, nil
}

func cmdLocalSession(command string, args []string) error {
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	port := fs.Int("port", 0, "local service port (default from config.json, 47611)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("unexpected argument")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir} // status is read-only, including when no installation exists.
	if *port == 0 {
		cfg, err := st.LoadConfig()
		if err != nil {
			return err
		}
		*port = cfg.Port
	}
	if *port < 1 || *port > 65535 {
		return errors.New("port must be in 1..65535")
	}
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", *port)
	client := localClient()
	defer client.CloseIdleConnections()
	health, err := probeLocalService(client, endpoint)
	if err != nil {
		return err
	}
	if command == "status" {
		return json.NewEncoder(os.Stdout).Encode(health)
	}
	credential, err := st.ReadRecoveryToken()
	if err != nil {
		return errors.New("local recovery credential unavailable; use the same state directory as serve or upgrade the service")
	}
	code, err := requestLocalPairing(client, endpoint, credential)
	if err != nil {
		return err
	}
	fmt.Fprintln(os.Stdout, "Admin pairing code (single use, 5 minutes):", code)
	fmt.Fprintln(os.Stdout, "Open", endpoint, "to pair. Existing admin sessions remain valid.")
	return nil
}

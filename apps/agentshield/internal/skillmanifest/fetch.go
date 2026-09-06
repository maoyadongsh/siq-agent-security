package skillmanifest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// MaxArtifactBytes is the hard cap for a single release binary download (DEV04-E).
const MaxArtifactBytes int64 = 256 << 20

// FetchOptions controls DownloadVerifiedArtifact / FetchAndStage.
type FetchOptions struct {
	Client            *http.Client
	AllowInsecureHTTP bool // loopback http:// only; production stays HTTPS
	UserAgent         string
}

// SelectArtifact returns the pin for goos/goarch from a signed manifest's artifacts.
func SelectArtifact(arts []Artifact, goos, goarch string) (Artifact, error) {
	for _, a := range arts {
		if a.OS == goos && a.Arch == goarch {
			if len(normalizeHex(a.SHA256)) != 64 {
				return Artifact{}, fmt.Errorf("skillmanifest: artifact sha256 for %s/%s is not 64 hex", goos, goarch)
			}
			if strings.TrimSpace(a.URL) == "" {
				return Artifact{}, fmt.Errorf("skillmanifest: artifact URL missing for %s/%s", goos, goarch)
			}
			return a, nil
		}
	}
	return Artifact{}, fmt.Errorf("skillmanifest: no artifact for %s/%s", goos, goarch)
}

func urlAllowed(raw string, allowInsecure bool) error {
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("skillmanifest: bad artifact URL: %w", err)
	}
	switch strings.ToLower(u.Scheme) {
	case "https":
		return nil
	case "http":
		if !allowInsecure {
			return fmt.Errorf("skillmanifest: refusing non-HTTPS download")
		}
		host := u.Hostname()
		if host == "localhost" || host == "127.0.0.1" || host == "::1" {
			return nil
		}
		ip := net.ParseIP(host)
		if ip != nil && ip.IsLoopback() {
			return nil
		}
		return fmt.Errorf("skillmanifest: insecure HTTP only allowed to loopback")
	default:
		return fmt.Errorf("skillmanifest: unsupported URL scheme %q", u.Scheme)
	}
}

func artifactLeaf(artURL string) string {
	u, err := url.Parse(artURL)
	if err != nil {
		return "siq-agent-security"
	}
	leaf := filepath.Base(u.Path)
	if leaf == "." || leaf == "/" || leaf == "" || leaf == string(filepath.Separator) {
		return "siq-agent-security"
	}
	return leaf
}

func downloadMax(art Artifact) int64 {
	max := art.Bytes
	if max <= 0 {
		max = MaxArtifactBytes
	}
	if max > MaxArtifactBytes {
		max = MaxArtifactBytes
	}
	return max
}

// DownloadVerifiedArtifact GETs art.URL into destPath (exclusive create),
// enforces size and sha256 pins from the signed manifest, and chmod 0700.
// Never executes the file.
func DownloadVerifiedArtifact(ctx context.Context, art Artifact, destPath string, opts FetchOptions) (digest string, err error) {
	if err := urlAllowed(art.URL, opts.AllowInsecureHTTP); err != nil {
		return "", err
	}
	want := normalizeHex(art.SHA256)
	if len(want) != 64 {
		return "", fmt.Errorf("skillmanifest: artifact sha256 must be 64 hex")
	}
	max := downloadMax(art)
	client := opts.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Minute}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, art.URL, nil)
	if err != nil {
		return "", err
	}
	ua := opts.UserAgent
	if ua == "" {
		ua = "siq-agent-security-fetch/1"
	}
	req.Header.Set("User-Agent", ua)

	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("skillmanifest: download failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("skillmanifest: download HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > 0 && resp.ContentLength > max {
		return "", fmt.Errorf("skillmanifest: Content-Length %d exceeds max %d", resp.ContentLength, max)
	}
	if art.Bytes > 0 && resp.ContentLength > 0 && resp.ContentLength != art.Bytes {
		return "", fmt.Errorf("skillmanifest: Content-Length %d != pinned bytes %d", resp.ContentLength, art.Bytes)
	}

	if err := os.MkdirAll(filepath.Dir(destPath), 0o700); err != nil {
		return "", err
	}
	f, err := os.OpenFile(destPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o700)
	if err != nil {
		return "", err
	}
	cleanup := true
	defer func() {
		_ = f.Close()
		if cleanup {
			_ = os.Remove(destPath)
		}
	}()

	h := sha256.New()
	limited := io.LimitReader(resp.Body, max+1)
	n, err := io.Copy(io.MultiWriter(f, h), limited)
	if err != nil {
		return "", fmt.Errorf("skillmanifest: download write: %w", err)
	}
	if n > max {
		return "", fmt.Errorf("skillmanifest: downloaded size exceeds max %d", max)
	}
	if art.Bytes > 0 && n != art.Bytes {
		return "", fmt.Errorf("skillmanifest: downloaded %d bytes != pinned %d", n, art.Bytes)
	}
	if err := f.Sync(); err != nil {
		return "", err
	}
	got := hex.EncodeToString(h.Sum(nil))
	if got != want {
		return "", fmt.Errorf("skillmanifest: downloaded sha256 %s != required %s", got, want)
	}
	cleanup = false
	return got, nil
}

// FetchAndStage downloads a pinned artifact into a temp file, verifies it,
// then StageVerifiedBinary into stageRoot (DEV04-E + DEV04-D).
func FetchAndStage(ctx context.Context, art Artifact, stageRoot string, opts FetchOptions) (stagedPath string, err error) {
	tmp, err := os.MkdirTemp("", "siq-fetch.*")
	if err != nil {
		return "", err
	}
	defer func() { _ = os.RemoveAll(tmp) }()
	if err := os.Chmod(tmp, 0o700); err != nil {
		return "", err
	}
	dest := filepath.Join(tmp, artifactLeaf(art.URL))
	if _, err := DownloadVerifiedArtifact(ctx, art, dest, opts); err != nil {
		return "", err
	}
	return StageVerifiedBinary(dest, stageRoot, art.SHA256)
}

package main

import "testing"

func TestValidateControlPlaneURLRequiresTLSOffLoopback(t *testing.T) {
	for _, raw := range []string{
		"http://control.example.com:8600",
		"ftp://control.example.com",
		"https://user:password@control.example.com",
		"https://control.example.com/api",
	} {
		if _, err := validateControlPlaneURL(raw); err == nil {
			t.Fatalf("validateControlPlaneURL(%q) accepted an unsafe URL", raw)
		}
	}
	for _, raw := range []string{
		"https://control.example.com",
		"http://127.0.0.1:8600",
		"http://[::1]:8600",
		"http://localhost:8600",
	} {
		if _, err := validateControlPlaneURL(raw); err != nil {
			t.Fatalf("validateControlPlaneURL(%q) rejected a supported URL: %v", raw, err)
		}
	}
}

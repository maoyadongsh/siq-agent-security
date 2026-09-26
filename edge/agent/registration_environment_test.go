package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestBoundRegistrationRequestAndResponse(t *testing.T) {
	for _, returned := range []string{"env-expected", "env-other", ""} {
		t.Run("response_"+returned, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				var body RegisterRequest
				if json.NewDecoder(r.Body).Decode(&body) != nil || body.ExpectedEnvironmentID != "env-expected" {
					t.Error("expected environment not sent")
				}
				_ = json.NewEncoder(w).Encode(RegisterResponse{EnvironmentID: returned, EdgeAgentID: "fixture", DeviceSecret: "synthetic", ControlPlanePublicKey: base64.StdEncoding.EncodeToString(make([]byte, 32))})
			}))
			defer server.Close()
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL})
			response, err := client.RegisterBound(context.Background(), "fixture", "identity", "fixture-key", nil, "env-expected")
			if calls != 1 {
				t.Fatal("registration retried")
			}
			if returned == "env-expected" {
				if err != nil || response == nil {
					t.Fatal("valid bound response rejected")
				}
			} else if err == nil || response != nil {
				t.Fatal("environment mismatch accepted")
			}
		})
	}
}

func TestIncompleteRegistrationResponseCannotBecomeState(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(RegisterResponse{EnvironmentID: "env-expected"})
	}))
	defer server.Close()
	client := NewClient(ClientConfig{ControlPlaneURL: server.URL})
	response, err := client.RegisterBound(context.Background(), "fixture", "identity", "fixture-key", nil, "env-expected")
	if err == nil || response != nil {
		t.Fatal("incomplete response accepted")
	}
}

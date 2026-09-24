package openshell

import (
	"reflect"
	"testing"
)

func TestNamedGatewayKeepsEndpointAndCredentialScope(t *testing.T) {
	env := map[string]string{envCLIBin: "/fixture/openshell", envEndpoint: "https://127.0.0.1:17671", envGatewayName: "owned", "XDG_CONFIG_HOME": "/fixture/xdg", "HOME": "/fixture/home"}
	c := New(Options{LookupEnv: func(k string) (string, bool) { v, ok := env[k]; return v, ok }})
	cmd, err := c.BuildCommand([]string{"status"})
	if err != nil || !reflect.DeepEqual(cmd, []string{"/fixture/openshell", "--gateway-endpoint", "https://127.0.0.1:17671", "--gateway", "owned", "status"}) {
		t.Fatal("named gateway lost endpoint or weakened TLS", cmd, err)
	}
	before := c.InvocationFingerprint()
	env[envGatewayName] = "other"
	if before == c.InvocationFingerprint() {
		t.Fatal("name not bound")
	}
	env[envGatewayName] = "owned"
	env["XDG_CONFIG_HOME"] = "/another/xdg"
	if before == c.InvocationFingerprint() {
		t.Fatal("credential location not bound")
	}
	for _, name := range []string{"--help", "../escape", "name with spaces"} {
		env[envGatewayName] = name
		if _, err := c.BuildCommand([]string{"status"}); err == nil {
			t.Fatal("unsafe name accepted")
		}
	}
	env[envGatewayName] = "owned"
	delete(env, envEndpoint)
	if _, err := c.BuildCommand([]string{"status"}); err == nil {
		t.Fatal("unbound named configuration accepted")
	}
}

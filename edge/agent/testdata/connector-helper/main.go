// Synthetic native subprocess for execution-boundary tests; never distributed.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"time"
)

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		if os.Getenv("SIQ_CONNECTOR_VERSION") == "overflow" {
			os.Stdout.Write(bytes.Repeat([]byte("x"), 16385))
			time.Sleep(time.Minute)
			return
		}
		var request struct {
			ID string `json:"id"`
			Op string `json:"op"`
		}
		if json.Unmarshal(scanner.Bytes(), &request) != nil {
			os.Exit(2)
		}
		var result any
		switch request.Op {
		case "describe":
			result = map[string]any{"version": "0.1.0", "objects": []string{"hermes_profile"}, "data_categories": []string{"config_names"}, "max_output_bytes": 8388608}
		case "validate_scope":
			result = map[string]any{"valid": true, "errors": []string{}}
		case "health":
			result = map[string]any{"path": os.Getenv("PATH"), "secret_absent": os.Getenv("SIQ_SYNTHETIC_DEVICE_SECRET") == "", "loader_absent": os.Getenv("LD_LIBRARY_PATH") == "", "alive": true}
		default:
			os.Stderr.WriteString("PRIVATE_DIAGNOSTIC_MUST_NOT_LEAK")
			json.NewEncoder(os.Stdout).Encode(map[string]any{"id": request.ID, "ok": false, "error": map[string]string{"code": "unsupported", "message": "PRIVATE_DIAGNOSTIC_MUST_NOT_LEAK"}})
			continue
		}
		json.NewEncoder(os.Stdout).Encode(map[string]any{"id": request.ID, "ok": true, "result": result})
	}
}

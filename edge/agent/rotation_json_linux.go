//go:build linux

package main

import "encoding/json"

// readDeviceState must first reject duplicate keys, unsafe files and trailing
// JSON. encoding/json's struct decoder alone accepts case-insensitive aliases,
// even with DisallowUnknownFields; reject those before decoding any secrets.
func rotationJSONFields(raw []byte, allowed []string, required bool) (map[string]json.RawMessage, bool) {
	var object map[string]json.RawMessage
	if json.Unmarshal(raw, &object) != nil || object == nil {
		return nil, false
	}
	keys := make(map[string]bool, len(allowed))
	for _, key := range allowed {
		keys[key] = true
	}
	for key, value := range object {
		if !keys[key] || string(value) == "null" {
			return nil, false
		}
	}
	return object, !required || len(object) == len(allowed)
}

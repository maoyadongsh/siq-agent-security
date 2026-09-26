package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"
)

var errConfigInvalid = errors.New("openclaw_config_invalid")

// encoding/json accepts case-folded struct keys, while presence checks below
// use exact keys. Reject those aliases before decoding so a roster cannot be
// silently replaced by an inferred default. Dynamic map keys are identities,
// not struct fields, and must retain their original case.
func checkConfigFieldCase(raw json.RawMessage, schema reflect.Type) error {
	if schema.Kind() == reflect.Pointer {
		return checkConfigFieldCase(raw, schema.Elem())
	}
	switch schema.Kind() {
	case reflect.Struct:
		var object map[string]json.RawMessage
		if json.Unmarshal(raw, &object) != nil {
			return errConfigInvalid
		}
		for key, value := range object {
			for i := 0; i < schema.NumField(); i++ {
				field := schema.Field(i)
				name := strings.Split(field.Tag.Get("json"), ",")[0]
				if name == "" || name == "-" || !strings.EqualFold(key, name) {
					continue
				}
				if key != name {
					return errConfigInvalid
				}
				if err := checkConfigFieldCase(value, field.Type); err != nil {
					return err
				}
			}
		}
	case reflect.Slice:
		// RawMessage is opaque JSON, not a roster of typed objects.
		if schema == reflect.TypeOf(json.RawMessage{}) {
			return nil
		}
		var items []json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			return errConfigInvalid
		}
		for _, item := range items {
			if err := checkConfigFieldCase(item, schema.Elem()); err != nil {
				return err
			}
		}
	case reflect.Map:
		var items map[string]json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			return errConfigInvalid
		}
		for _, item := range items {
			if err := checkConfigFieldCase(item, schema.Elem()); err != nil {
				return err
			}
		}
	}
	return nil
}

// Check every object, including ignored fields: include expansion and duplicate
// keys could otherwise hide a roster and cause a false implicit main candidate.
func checkConfigValue(dec *json.Decoder, depth int) error {
	if depth > 64 {
		return errConfigInvalid
	}
	token, err := dec.Token()
	if err != nil {
		return errConfigInvalid
	}
	delim, compound := token.(json.Delim)
	if !compound {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for dec.More() {
			keyToken, err := dec.Token()
			if err != nil {
				return errConfigInvalid
			}
			key, ok := keyToken.(string)
			if !ok || seen[key] || key == "$include" {
				return errConfigInvalid
			}
			seen[key] = true
			if err := checkConfigValue(dec, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for dec.More() {
			if err := checkConfigValue(dec, depth+1); err != nil {
				return err
			}
		}
	default:
		return errConfigInvalid
	}
	_, err = dec.Token()
	if err != nil {
		return errConfigInvalid
	}
	return nil
}

func parseOpenClawConfig(data []byte) (openclawConfig, error) {
	var cfg openclawConfig
	var err error
	data, err = normalizeConfigJSON5(data)
	if err != nil {
		return cfg, err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := checkConfigValue(dec, 0); err != nil {
		return cfg, err
	}
	if _, err := dec.Token(); err != io.EOF {
		return cfg, errConfigInvalid
	}
	if err := checkConfigFieldCase(data, reflect.TypeOf(cfg)); err != nil {
		return cfg, err
	}
	var root map[string]json.RawMessage
	if json.Unmarshal(data, &root) != nil || root == nil {
		return cfg, errConfigInvalid
	}
	var agents map[string]json.RawMessage
	if raw, present := root["agents"]; present {
		if json.Unmarshal(raw, &agents) != nil || agents == nil {
			return cfg, errConfigInvalid
		}
	}
	for _, key := range []string{"defaults", "list", "entries"} {
		if raw, present := agents[key]; present && bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return cfg, errConfigInvalid
		}
	}
	if json.Unmarshal(data, &cfg) != nil {
		return cfg, errConfigInvalid
	}
	_, listPresent := agents["list"]
	_, entriesPresent := agents["entries"]
	if !listPresent && !entriesPresent {
		cfg.Agents.List = []openclawAgent{{ID: "main", InferredDefault: true,
			Workspace: cfg.Agents.Defaults.Workspace, Model: cfg.Agents.Defaults.Model}}
	}
	return cfg, nil
}

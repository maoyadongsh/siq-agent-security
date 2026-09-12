package state

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
)

type LocalInstance struct {
	SchemaVersion string `json:"schema_version"`
	InstanceID    string `json:"instance_id"`
}

type InitializationResult struct {
	SchemaVersion    string `json:"schema_version"`
	Status           string `json:"status"`
	InstanceID       string `json:"instance_id"`
	StateDirectoryID string `json:"state_directory_id"`
	Port             int    `json:"port"`
}

func readInitializationFile(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > 65536 {
		return nil, errors.New("state: initialization requires a regular file within 64 KiB")
	}
	raw, err := readCommitFile(path)
	if len(raw) > 65536 {
		return nil, errors.New("state: initialization file budget exceeded")
	}
	return raw, err
}

func (s *Store) ReadLocalInstance() (LocalInstance, error) {
	var instance LocalInstance
	raw, err := readInitializationFile(filepath.Join(s.Dir, "local-instance.json"))
	if err != nil {
		return instance, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(&instance) != nil || dec.Decode(new(any)) != io.EOF || instance.SchemaVersion != "local-client-instance/v1" {
		return LocalInstance{}, errors.New("state: invalid or unsupported local instance record; restore it before retrying")
	}
	id, err := hex.DecodeString(instance.InstanceID)
	if err != nil || len(id) != 32 || hex.EncodeToString(id) != instance.InstanceID {
		return LocalInstance{}, errors.New("state: invalid local instance identity; restore it before retrying")
	}
	return instance, nil
}

// Initialize publishes only missing installation metadata under writer ownership.
// Existing configuration is validated but never rewritten by initialization.
func (s *Store) Initialize(w *Writer, port int) (InitializationResult, error) {
	var result InitializationResult
	if port < 0 || port > 65535 {
		return result, errors.New("state: initialization port must be in 1..65535")
	}
	if w == nil || filepath.Clean(w.Dir) != filepath.Clean(s.Dir) {
		return result, ErrWriterBusy
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil || pid != os.Getpid() || pid != w.pid || owner != w.owner {
		return result, ErrWriterBusy
	}
	directoryID, err := s.DirectoryID()
	if err != nil {
		return result, err
	}
	configPath := filepath.Join(s.Dir, "config.json")
	rawConfig, err := readInitializationFile(configPath)
	missingConfig := errors.Is(err, os.ErrNotExist)
	if err != nil && !missingConfig {
		return result, errors.New("state: cannot safely read existing configuration")
	}
	if !missingConfig {
		var object map[string]json.RawMessage
		if json.Unmarshal(rawConfig, &object) != nil || object == nil {
			return result, errors.New("state: invalid configuration; restore it before initializing")
		}
	}
	cfg, err := decodeConfig(rawConfig)
	if err != nil {
		return result, errors.New("state: invalid configuration; restore it before initializing")
	}
	if port != 0 {
		if !missingConfig && cfg.Port != port {
			return result, errors.New("state: configured port differs; initialization will not change an existing port")
		}
		cfg.Port = port
	}
	instance, err := s.ReadLocalInstance()
	missingInstance := errors.Is(err, os.ErrNotExist)
	if err != nil && !missingInstance {
		return result, errors.New("state: invalid or unsupported local instance record; restore it before initializing")
	}
	if missingInstance {
		var id [32]byte
		if _, err := rand.Read(id[:]); err != nil {
			return result, err
		}
		instance = LocalInstance{SchemaVersion: "local-client-instance/v1", InstanceID: hex.EncodeToString(id[:])}
	}
	if missingConfig {
		raw, err := json.Marshal(cfg)
		if err != nil {
			return result, err
		}
		if err := publishCommitFile(configPath, raw); err != nil {
			return result, err
		}
	}
	if missingInstance {
		raw, err := json.Marshal(instance)
		if err != nil {
			return result, err
		}
		if err := publishCommitFile(filepath.Join(s.Dir, "local-instance.json"), raw); err != nil {
			return result, err
		}
	}
	return InitializationResult{SchemaVersion: "local-client-initialization/v1", Status: "initialized", InstanceID: instance.InstanceID, StateDirectoryID: directoryID, Port: cfg.Port}, nil
}

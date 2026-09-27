package adapterinstall

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func captureManagedSecurity(path string, image fileImage, preserveSecurity ...bool) (fileImage, error) {
	if runtime.GOOS != "windows" || (filepath.Base(path) != product.Name+".json" && !(len(preserveSecurity) > 0 && preserveSecurity[0])) {
		return image, nil
	}
	if err := stateformat.RequirePath(path, false); err != nil {
		return fileImage{}, err
	}
	snapshot, err := privatefs.OpenReadSnapshot(filepath.Dir(path))
	if err != nil {
		return fileImage{}, &adapters.WorkBuddyPreflightError{Code: "workbuddy_config_parent_unavailable"}
	}
	defer snapshot.Close()
	raw, err := snapshot.ReadFile(filepath.Base(path), 1<<20)
	if err != nil {
		return fileImage{}, &adapters.WorkBuddyPreflightError{Code: "workbuddy_config_file_unavailable"}
	}
	if !bytes.Equal(raw, image.Data) {
		return fileImage{}, ErrPlanChanged
	}
	image.Security, err = snapshot.FileSecurity(filepath.Base(path))
	if err != nil {
		return fileImage{}, err
	}
	return image, snapshot.Verify()
}

func publishManagedSecurity(path string, image fileImage, replace bool) error {
	if runtime.GOOS != "windows" || image.Security == "" {
		return publishFile(path, image.Data, os.FileMode(image.Mode), replace)
	}
	if err := stateformat.RequirePath(path, true); err != nil {
		return err
	}
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return err
	}
	tmp := filepath.Join(filepath.Dir(path), ".siq-adapter-pending-"+hex.EncodeToString(id[:]))
	f, err := privatefs.CreateNewWithSecurity(tmp, image.Security)
	if err != nil {
		return err
	}
	defer statefs.Remove(tmp)
	if _, err = f.Write(image.Data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if replace {
		return statefs.Rename(tmp, path)
	}
	return statefs.Link(tmp, path)
}

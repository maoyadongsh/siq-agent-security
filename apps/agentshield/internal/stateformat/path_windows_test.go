package stateformat

import (
	"errors"
	"testing"
)

func TestWindowsStatePathSpelling(t *testing.T) {
	valid := []string{"", ".", "..", `C:`, `C:\`, `C:.`, `C:..`, `C:relative`, `\rooted`, `a\..\b`, `a/.hidden/中文 状态`, `C:\normal.name\inner space`, `\\?\C:\normal`, `\\.\C:\normal`, `\??\C:\normal`, `\\server\share`, `\\server.example.\share\normal`, `\\?\UNC\server.example.\share`, `//server.example./share/normal`}
	for _, path := range valid {
		if err := ValidatePath(path); err != nil {
			t.Errorf("valid spelling rejected: %q", path)
		}
	}
	invalid := []string{" ", "   ", "...", ". ", ".. ", `target.`, `target `, `target. .`, `C:target.`, `C:\bad.\target`, `C:/bad /target`, `C:\bad.\`, `C:/bad /`, `C:\bad.\..\good`, `C:/bad /../good`, `\\?\C:\bad.\..\good`, `\\.\C:\bad \good`, `\??\C:\bad.`, `\\server\share.`, `\\server\share \normal`, `\\server.example.\share.`, `\\?\UNC\server\share.`, `\\.\UNC\server\share `, `\??\UNC\server\share.`, `//server/share./normal`, `\\server\share\bad.`, `\\?\UNC\server\share\bad `}
	for _, path := range invalid {
		if err := ValidatePath(path); !errors.Is(err, ErrCorrupt) {
			t.Errorf("unsafe spelling not rejected: %q", path)
		}
	}
}

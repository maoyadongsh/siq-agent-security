package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUserServiceRegistrationAndRecovery(t *testing.T) {
	path := filepath.Join(t.TempDir(), "siq.service")
	if err := os.WriteFile(path, []byte("unit"), 0600); err != nil {
		t.Fatal(err)
	}
	loaded := fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\n", path)
	for _, retry := range []bool{false, true} {
		t.Run(fmt.Sprint(retry), func(t *testing.T) {
			linked := retry
			links, reloads := 0, 0
			control := func(args ...string) (string, error) {
				switch args[0] {
				case "show":
					if linked {
						return loaded, nil
					}
					return "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\n", nil
				case "link":
					if strings.Join(args, " ") != "link --runtime -- "+path {
						t.Fatalf("unsafe link args: %v", args)
					}
					linked = true
					links++
				case "daemon-reload":
					reloads++
				default:
					t.Fatalf("unexpected mutation: %v", args)
				}
				return "", nil
			}
			if err := registerUserUnit(control, path, "siq.service", true); err != nil {
				t.Fatal(err)
			}
			if reloads != 1 || (!retry && links != 1) || (retry && links != 0) {
				t.Fatal("incorrect retry behavior")
			}
		})
	}
}

func TestUserServiceRegistrationRejectsForeignAndIncomplete(t *testing.T) {
	path := filepath.Join(t.TempDir(), "unit.service")
	if err := os.WriteFile(path, []byte("unit"), 0600); err != nil {
		t.Fatal(err)
	}
	valid := fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked\n", path)
	for _, response := range []string{
		strings.Replace(valid, path, path+".foreign", 1),
		strings.Replace(valid, "DropInPaths=", "DropInPaths=/foreign.conf", 1),
		strings.Replace(valid, "linked", "linked-runtime", 1),
		strings.Replace(valid, "loaded", "masked", 1),
		strings.Replace(valid, "loaded", "not-found", 1),
		"LoadState=not-found\n", valid + "LoadState=loaded\n",
	} {
		err := registerUserUnit(func(args ...string) (string, error) {
			if args[0] != "show" {
				t.Fatal("mutated unknown unit")
			}
			return response, nil
		}, path, "unit.service", false)
		if err == nil {
			t.Fatalf("accepted invalid response: %s", response)
		}
	}
	for _, failAt := range []string{"link", "daemon-reload", "readback"} {
		t.Run(failAt, func(t *testing.T) {
			reads := 0
			err := registerUserUnit(func(args ...string) (string, error) {
				if args[0] == failAt {
					return "", errors.New("injected")
				}
				if args[0] == "show" {
					reads++
					if reads == 1 {
						return "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\n", nil
					}
					if failAt == "readback" {
						return "", errors.New("injected")
					}
					return valid, nil
				}
				if args[0] != "link" && args[0] != "daemon-reload" {
					t.Fatal("unexpected rollback")
				}
				return "", nil
			}, path, "unit.service", false)
			if err == nil {
				t.Fatal("reported success after failure")
			}
		})
	}
}

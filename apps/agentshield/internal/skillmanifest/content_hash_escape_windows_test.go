package skillmanifest

import (
	"bytes"
	"encoding/binary"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
)

// A real junction exercises directory escape without SeCreateSymbolicLinkPrivilege.
// It is explicitly different from the file-symlink fixture on other platforms.
func makeHashEscape(t *testing.T, root, outside string) {
	t.Helper()
	makeHashJunction(t, outside, filepath.Join(root, "leak"))
}

func makeHashJunction(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Mkdir(link, 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Remove(link); err != nil {
			t.Errorf("junction cleanup: %v", err)
		}
	})
	sub, err := syscall.UTF16FromString(`\??\` + target)
	if err != nil {
		t.Fatal(err)
	}
	printName, err := syscall.UTF16FromString(target)
	if err != nil {
		t.Fatal(err)
	}
	data := make([]byte, 16+2*(len(sub)+len(printName)))
	binary.LittleEndian.PutUint32(data[0:], 0xa0000003)
	binary.LittleEndian.PutUint16(data[4:], uint16(len(data)-8))
	binary.LittleEndian.PutUint16(data[10:], uint16((len(sub)-1)*2))
	binary.LittleEndian.PutUint16(data[12:], uint16(len(sub)*2))
	binary.LittleEndian.PutUint16(data[14:], uint16((len(printName)-1)*2))
	for i, v := range append(sub, printName...) {
		binary.LittleEndian.PutUint16(data[16+i*2:], v)
	}
	p, err := syscall.UTF16PtrFromString(link)
	if err != nil {
		t.Fatal(err)
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT|syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.CloseHandle(h)
	var returned uint32
	if err := syscall.DeviceIoControl(h, 0x000900a4, &data[0], uint32(len(data)), nil, 0, &returned, nil); err != nil {
		t.Fatal(err)
	}
}

func TestPythonHashSkillDirWindowsInternalJunctionParity(t *testing.T) {
	skillDir, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := exec.LookPath("python3"); err != nil {
		t.Fatal("native Python required for Windows junction parity", err)
	}
	root := t.TempDir()
	target := filepath.Join(root, "real")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("# harmless\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(target, "plain.txt"), []byte("retained content\n"), 0600); err != nil {
		t.Fatal(err)
	}
	before, err := HashSkillDir(root)
	if err != nil {
		t.Fatal(err)
	}
	makeHashJunction(t, target, filepath.Join(root, "alias"))
	after, err := HashSkillDir(root)
	if err != nil || before != after {
		t.Fatal("Go internal directory link changed hash", err)
	}
	py := filepath.Join(skillDir, "scripts", "verify_manifest.py")
	if got := pythonContentHash(t, py, root); got != before {
		t.Fatal("Python descended an internal directory link")
	}
	if got, err := os.ReadFile(filepath.Join(target, "plain.txt")); err != nil || string(got) != "retained content\n" {
		t.Fatal("internal junction probe changed source", err)
	}
}

func TestPythonVerifierWindowsJunctionRejectsSignedTree(t *testing.T) {
	skillDir, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	root, outside := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("# harmless\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "secret"), []byte("outside fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	hash, err := HashSkillDir(root)
	if err != nil {
		t.Fatal(err)
	}
	key := testKey(t) // An explicit test trust root; never the publisher key.
	manifest, err := Build(Options{ContentHash: hash, Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(manifest, key); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "skill-manifest.json")
	if err := WriteFile(path, manifest); err != nil {
		t.Fatal(err)
	}
	verify := func() ([]byte, error) {
		return exec.Command("python3", filepath.Join(skillDir, "scripts", "verify_manifest.py"), "--manifest", path, "--pubkey", key.PublicBase64(), "--skill-dir", root).CombinedOutput()
	}
	if out, err := verify(); err != nil {
		t.Fatalf("valid test-signed tree rejected: %v %s", err, out)
	}
	makeHashEscape(t, root, outside)
	if out, err := verify(); err == nil || !bytes.Contains(out, []byte("incomplete")) {
		t.Fatalf("signed tree with a root escape was not rejected as incomplete: %v %s", err, out)
	}
}

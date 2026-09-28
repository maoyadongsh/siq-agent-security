package privatefs

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSecurityDescriptorInheritancePreservedAtCreation(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "source.json")
	if err := os.WriteFile(src, []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	snap, err := OpenReadSnapshot(root)
	if err != nil {
		t.Fatal(err)
	}
	original, err := snap.FileSecurity("source.json")
	if err != nil {
		t.Fatal(err)
	}
	snap.Close()
	dst := filepath.Join(root, "new.json")
	f, createErr := CreateNewWithSecurity(dst, original)
	if f != nil {
		f.Close()
	}
	snap, err = OpenReadSnapshot(root)
	if err != nil {
		t.Fatal(err)
	}
	defer snap.Close()
	actual, err := snap.FileSecurity("new.json")
	if err != nil {
		t.Fatal(err)
	}
	if !EquivalentSecurity(original, actual) {
		t.Fatal("creation changed permission semantics")
	}
	if createErr != nil {
		t.Fatal(createErr)
	}
}
func TestSecurityEquivalenceDoesNotIgnorePermissionChanges(t *testing.T) {
	original := "O:SYD:AI(A;ID;FA;;;SY)(D;;0x20;;;WD)"
	if !EquivalentSecurity(original, "O:SYD:(A;ID;FA;;;SY)(D;;0x20;;;WD)") {
		t.Fatal("bookkeeping bit changed comparison")
	}
	for _, changed := range []string{
		"O:SYD:P(A;ID;FA;;;SY)(D;;0x20;;;WD)",
		"O:SYD:(A;;FA;;;SY)(D;;0x20;;;WD)",
		"O:SYD:(A;ID;FA;;;SY)",
		"O:SYD:(D;;0x20;;;WD)(A;ID;FA;;;SY)",
		"O:BAD:(A;ID;FA;;;SY)(D;;0x20;;;WD)",
	} {
		if EquivalentSecurity(original, changed) {
			t.Fatal("permission change ignored")
		}
	}
}

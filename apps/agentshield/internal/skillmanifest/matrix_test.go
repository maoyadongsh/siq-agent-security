package skillmanifest

import (
	"strings"
	"testing"
)

// Historical vectors are verified with their original matrix; the current
// builder is independently checked against the supported product scope.
func historicalMatrix(t *testing.T, name string) []Row {
	t.Helper()
	m, err := LoadFile("../../testdata/contracts/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return m.SupportMatrix
}

func TestCurrentManifestOmitsRetiredPlatform(t *testing.T) {
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range m.SupportMatrix {
		if row.Platform == "codebuddy" {
			t.Fatal("current release advertises a retired platform")
		}
	}
}

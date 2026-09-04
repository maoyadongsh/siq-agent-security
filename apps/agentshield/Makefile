.PHONY: ui test vet

ui:
	cd ../web && npm ci && npm run build:local

vet:
	gofmt -l .
	go vet ./...

test: vet
	go test ./...

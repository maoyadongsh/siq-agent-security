"""Validate Pages links, release identity and generated source-diagram inputs."""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids = set()
        self.links = []
        self.h1 = 0
        self.feed(path.read_text())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, "duplicate HTML id"
            self.ids.add(attrs["id"])
        self.h1 += tag == "h1"
        for name in ("href", "src"):
            if name in attrs:
                self.links.append(attrs[name])
        if tag == "img":
            assert "alt" in attrs, "image without alt text"


def main():
    pages = {path: Page(path) for path in SITE.glob("*.html")}
    for path, page in pages.items():
        assert page.h1 == 1, f"expected one h1: {path}"
        assert "cursor/agentshield-w0" not in path.read_text(), "obsolete branch reference"
        for link in page.links:
            url = urlsplit(link)
            repo_prefix = "/maoyadongsh/siq-agent-security/"
            if url.netloc == "github.com" and url.path.startswith(repo_prefix):
                relative = url.path[len(repo_prefix):]
                for prefix in ("blob/main/", "tree/main/"):
                    if relative.startswith(prefix):
                        assert (ROOT / unquote(relative[len(prefix):])).exists(), link
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.is_relative_to(SITE), link
            if target.is_dir():
                target /= "index.html"
            assert target.exists(), f"missing local link: {link} in {path.name}"
            if url.fragment and target in pages:
                assert unquote(url.fragment) in pages[target].ids, link
    index = (SITE / "index.html").read_text()
    release = json.loads((ROOT / "docs/research/evidence/release-signing-20260909.json").read_text())
    assert release["release_tag"] in index
    for asset in release["assets"]:
        assert asset["url"] in index, "missing release asset link"
    assert release["certificate_identity"] in index
    assert release["certificate_oidc_issuer"] in index
    assert "--mode test --port 47621" in index
    diagrams = json.loads((SITE / "diagrams/index.json").read_text())
    assert len(diagrams["source_sha"]) == 40
    for field in ("cli", "http_routes", "packages", "grant_transitions", "diagrams"):
        assert diagrams[field], f"empty source extraction: {field}"
    for item in diagrams["diagrams"]:
        assert (SITE / "diagrams" / item["file"]).is_file()
    print(json.dumps({"pages": len(pages), "diagrams": len(diagrams["diagrams"]),
                      "local_links": "passed", "release_identity": "passed"}))


if __name__ == "__main__":
    main()

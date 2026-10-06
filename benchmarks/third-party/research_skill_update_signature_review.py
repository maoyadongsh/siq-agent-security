"""Supplemental signature decoder; original frozen measurement is unchanged.

Installation records use a versioned schema and canonical signatures without
the Grant/SEC signing_schema field (skillinstall/record.go, publication.go).
"""
import research_skill_update_verify as original

grant_context_verify = original.verify
INSTALLATION_SCHEMAS = {'local-skill-install-operation/v1', 'local-skill-update-plan/v1'}


def verify_authority(key, document):
    if document.get('schema_version') not in INSTALLATION_SCHEMAS:
        return grant_context_verify(key, document)
    if 'signing_schema' in document:
        raise ValueError('unexpected installation signature encoding')
    key.verify(bytes.fromhex(document['signature']), original.canonical(
        {k: v for k, v in document.items() if k != 'signature'}))


def main():
    original.verify = verify_authority
    return original.main()


if __name__ == '__main__':
    raise SystemExit(main())

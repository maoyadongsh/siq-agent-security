"""Join captured ZIP bytes to discovered files, real import path and signed record."""
import base64
import hashlib
import io
import stat
import zipfile


def verify_archive_source(obs, kind, record):
    capture = obs['zip_sources'][kind]
    raw = base64.b64decode(capture['archive_base64'], validate=True)
    if len(raw) > 1 << 20 or hashlib.sha256(raw).hexdigest() != capture['archive_sha256']:
        raise ValueError('ZIP capture digest differs')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for item in archive.infolist():
            mode = item.external_attr >> 16
            if item.filename in files or not stat.S_ISREG(mode) or item.file_size > 1 << 20:
                raise ValueError('unexpected archive member')
            data = archive.read(item)
            files[item.filename] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'executable': bool(mode & 0o111)}
    if files != obs['sources_before'][kind] or capture['archive_sha256'] != capture['archive_after_sha256']:
        raise ValueError('archive/source identity differs')
    if record['source_kind'] != 'local_zip' or record['source_locator_digest'] != hashlib.sha256(capture['path'].encode()).hexdigest():
        raise ValueError('signed record does not identify ZIP source')
    return capture['path']

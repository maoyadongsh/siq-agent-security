package skillimport

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Bound the central-directory parser before archive/zip allocates its file list.
// ZIP64/multi-volume archives are intentionally outside this contract.
func checkZipDirectory(raw []byte) error {
	if int64(len(raw)) > maxArchiveBytes {
		return ErrLimit
	}
	end := -1
	for i := len(raw) - 22; i >= 0 && i >= len(raw)-22-65535; i-- {
		if binary.LittleEndian.Uint32(raw[i:i+4]) == 0x06054b50 && i+22+int(binary.LittleEndian.Uint16(raw[i+20:i+22])) == len(raw) {
			end = i
			break
		}
	}
	if end < 0 {
		return ErrInvalid
	}
	e := raw[end:]
	if binary.LittleEndian.Uint16(e[4:6]) != 0 || binary.LittleEndian.Uint16(e[6:8]) != 0 {
		return ErrInvalid
	}
	count := int(binary.LittleEndian.Uint16(e[10:12]))
	if count != int(binary.LittleEndian.Uint16(e[8:10])) || count == 65535 {
		return ErrInvalid
	}
	size := uint64(binary.LittleEndian.Uint32(e[12:16]))
	offset := uint64(binary.LittleEndian.Uint32(e[16:20]))
	if count > maxFiles+maxDirs || size > 4<<20 {
		return ErrLimit
	}
	if offset == 0xffffffff || size == 0xffffffff || offset+size > uint64(end) {
		return ErrInvalid
	}
	at, finish := int(offset), int(offset+size)
	actual := 0
	for at < finish {
		if at+46 > finish || binary.LittleEndian.Uint32(raw[at:at+4]) != 0x02014b50 {
			return ErrInvalid
		}
		actual++
		if actual > maxFiles+maxDirs {
			return ErrLimit
		}
		header := raw[at : at+46]
		if binary.LittleEndian.Uint16(header[34:36]) != 0 || binary.LittleEndian.Uint32(header[20:24]) == 0xffffffff || binary.LittleEndian.Uint32(header[24:28]) == 0xffffffff || binary.LittleEndian.Uint32(header[42:46]) == 0xffffffff {
			return ErrInvalid
		}
		name, extra, comment := int(binary.LittleEndian.Uint16(header[28:30])), int(binary.LittleEndian.Uint16(header[30:32])), int(binary.LittleEndian.Uint16(header[32:34]))
		if name > 513 {
			return ErrLimit
		}
		at += 46 + name + extra + comment
		if at > finish {
			return ErrInvalid
		}
	}
	if actual != count {
		return ErrInvalid
	}
	return nil
}

func extractZip(ctx context.Context, raw []byte, target string) (tree, bool, error) {
	out := emptyTree()
	if err := checkZipDirectory(raw); err != nil {
		return out, false, err
	}
	archive, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		return out, false, ErrInvalid
	}
	paths := map[string]string{}
	explicit := map[string]bool{}
	kinds := map[string]bool{}
	var total int64
	excluded := false
	var directory func(string) error
	directory = func(path string) error {
		if path == "" {
			return nil
		}
		if i := strings.LastIndex(path, "/"); i >= 0 {
			if err := directory(path[:i]); err != nil {
				return err
			}
		}
		key := strings.ToLower(path)
		if known, ok := paths[key]; ok {
			if known != path || !kinds[key] {
				return ErrInvalid
			}
			return nil
		}
		if len(out.Directories) >= maxDirs {
			return ErrLimit
		}
		if err := os.Mkdir(filepath.Join(target, filepath.FromSlash(path)), 0700); err != nil {
			return ErrUnavailable
		}
		paths[key] = path
		kinds[key] = true
		out.Directories = append(out.Directories, path)
		return nil
	}
	for _, entry := range archive.File {
		if err := ctx.Err(); err != nil {
			return out, excluded, err
		}
		name := strings.TrimSuffix(entry.Name, "/")
		if !validPath(name) {
			return out, excluded, ErrInvalid
		}
		mode := entry.Mode()
		isDir := strings.HasSuffix(entry.Name, "/")
		if mode&os.ModeSymlink != 0 || (!mode.IsRegular() && !mode.IsDir()) || mode.IsDir() != isDir || entry.Flags&1 != 0 || (entry.Method != zip.Store && entry.Method != zip.Deflate) {
			return out, excluded, ErrInvalid
		}
		if gitMetadata(name) {
			excluded = true
			continue
		}
		key := strings.ToLower(name)
		if explicit[key] {
			return out, excluded, ErrInvalid
		}
		explicit[key] = true
		if isDir {
			if err := directory(name); err != nil {
				return out, excluded, err
			}
			continue
		}
		if _, ok := paths[key]; ok {
			return out, excluded, ErrInvalid
		}
		if len(out.Files) >= maxFiles || entry.UncompressedSize64 > uint64(maxFileBytes) || entry.UncompressedSize64 > uint64(maxTotalBytes-total) {
			return out, excluded, ErrLimit
		}
		if i := strings.LastIndex(name, "/"); i >= 0 {
			if err := directory(name[:i]); err != nil {
				return out, excluded, err
			}
		}
		reader, err := entry.Open()
		if err != nil {
			return out, excluded, ErrInvalid
		}
		data, err := io.ReadAll(io.LimitReader(contextReader{ctx, reader}, int64(entry.UncompressedSize64)+1))
		closeErr := reader.Close()
		if ctx.Err() != nil {
			return out, excluded, ctx.Err()
		}
		if err != nil || closeErr != nil || uint64(len(data)) != entry.UncompressedSize64 {
			return out, excluded, ErrInvalid
		}
		executable := mode.Perm()&0111 != 0
		if err := writeFile(filepath.Join(target, filepath.FromSlash(name)), data, executable); err != nil {
			return out, excluded, err
		}
		paths[key] = name
		kinds[key] = false
		total += int64(len(data))
		out.Files = append(out.Files, File{name, sum(data), int64(len(data)), executable})
	}
	out.finish()
	return out, excluded, nil
}

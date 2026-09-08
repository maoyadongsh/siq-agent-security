#!/usr/bin/env python3
"""Add Chinese narration and bilingual subtitles without changing the demo timeline.

Media-only dependency: edge-tts==7.2.8 in an isolated environment, plus ffmpeg
with libass and Noto Sans CJK SC. This is not a Secure Agent runtime dependency.
Only the reviewed public narration script is sent to the speech service.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_name,width,height', '-of', 'json', str(path)]))


def timestamp(seconds, ass=False):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    if ass:
        return f'{hours}:{minutes:02}:{seconds:02}.{millis // 10:02}'
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    source = Path(record['file']).resolve()
    if not record['passed'] or digest(source) != record['sha256']:
        raise ValueError('source recording must be accepted and match its recorded hash')
    narration = json.loads(args.script.read_text())
    segments = narration['segments']
    source_probe = probe(source)
    duration = float(source_probe['format']['duration'])
    if len(source_probe['streams']) != 1 or not 120 <= duration <= 180:
        raise ValueError('expected the silent accepted 2–3 minute source recording')
    previous_end = 0
    for segment in segments:
        if not previous_end <= segment['start'] < segment['end'] <= duration:
            raise ValueError('subtitle windows overlap or exceed the source timeline')
        if any(char in segment[key] for char in '{}\\\n' for key in ('zh', 'en')):
            raise ValueError('narration text must be plain, single-line subtitle text')
        previous_end = segment['end']
    args.out_dir.mkdir(parents=True, exist_ok=False)
    out = args.out_dir.resolve()
    import edge_tts  # optional media-only dependency
    # Generate sequentially; preserve each complete clip at its native speaking rate.
    for index, segment in enumerate(segments):
        audio = out / f'voice-{index:02}.mp3'
        asyncio.run(edge_tts.Communicate(segment['zh'], narration['voice']).save(str(audio)))
        segment['audio_duration'] = float(probe(audio)['format']['duration'])
        if segment['audio_duration'] > segment['end'] - segment['start']:
            raise ValueError(f'narration {index} exceeds its window; shorten the script instead of speeding it up')
        segment['audio_sha256'] = digest(audio)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(audio),
                        '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', str(out / f'voice-{index:02}.wav')], check=True)
    pcm = bytearray(round(duration * 24000) * 2)
    for index, segment in enumerate(segments):
        with wave.open(str(out / f'voice-{index:02}.wav')) as clip:
            data = clip.readframes(clip.getnframes())
        offset = round(segment['start'] * 24000) * 2
        if offset + len(data) > len(pcm):
            raise ValueError('audio exceeds the video timeline')
        pcm[offset:offset + len(data)] = data
    with wave.open(str(out / 'narration.wav'), 'wb') as stream:
        stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        stream.writeframes(pcm)
    width, height = source_probe['streams'][0]['width'], source_probe['streams'][0]['height']
    # A new band below the original full frame avoids covering any UI or evidence.
    band = 180
    ass = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height + band}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narration,Noto Sans CJK SC,30,&H00FFFFFF,&H00FFFFFF,&H00102030,&H00102030,0,0,0,0,100,100,0,0,1,0,0,5,32,32,12,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    srt = []
    for index, segment in enumerate(segments):
        text = ('{\\pos(' + str(width // 2) + ',' + str(height + band // 2) + ')}'
                + segment['zh'] + '\\N{\\fs21}' + segment['en'])
        ass += f"Dialogue: 0,{timestamp(segment['start'], True)},{timestamp(segment['end'], True)},Narration,,0,0,0,,{text}\n"
        srt.append(f"{index + 1}\n{timestamp(segment['start'])} --> {timestamp(segment['end'])}\n{segment['zh']}\n{segment['en']}\n")
    (out / 'subtitles.ass').write_text(ass)
    (out / 'subtitles.zh-en.srt').write_text('\n'.join(srt))
    output = out / 'siq-v4-demo-zh.mp4'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(source),
        '-i', str(out / 'narration.wav'), '-vf', f'pad=iw:ih+{band}:0:0:color=0x102030,ass=subtitles.ass',
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-t', str(duration), '-movflags', '+faststart', str(output)], cwd=out, check=True)
    final_probe = probe(output)
    if abs(float(final_probe['format']['duration']) - duration) > .15 or len(final_probe['streams']) != 2:
        raise ValueError('final audio/video duration or stream count mismatch')
    result = {'schema_version': 'hackathon-narrated-video/v1', 'source_sha': record['source_sha'],
              'source_video_sha256': record['sha256'], 'source_video': str(source),
              'file': str(output), 'sha256': digest(output), 'script_sha256': digest(args.script),
              'speech_provider': 'Microsoft Edge speech via edge-tts', 'edge_tts_version': '7.2.8',
              'voice': narration['voice'], 'synthetic_narration': True, 'language': 'zh-CN',
              'subtitles': ['zh-CN', 'en'], 'subtitle_file': str(out / 'subtitles.zh-en.srt'),
              'segments': segments, 'probe': final_probe, 'source_timeline_changed': False,
              'source_frame_cropped': False, 'source_ui_edited': False, 'subtitle_band_added_pixels': band,
              'uploaded': False, 'passed': True, 'visual_and_audio_review': 'pending'}
    (out / 'narrated-video.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'file': str(output), 'sha256': result['sha256'], 'passed': True}))


if __name__ == '__main__':
    main()

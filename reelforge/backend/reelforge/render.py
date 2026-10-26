"""Render de la línea de tiempo con FFmpeg: normalización de clips, transiciones
(xfade), Ken Burns, filtros de color, subtítulos animados, mezcla con ducking y
exportación en distintas calidades."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel

from . import captions, config, ffmpeg
from .project import Clip, Project, clip_lengths, effective_transitions, get_media, new_id

# Etiqueta -> nombre del efecto xfade de FFmpeg
TRANSITIONS: dict[str, str] = {
    "none": "Corte",
    "fade": "Fundido",
    "fadeblack": "Fundido a negro",
    "fadewhite": "Flash blanco",
    "dissolve": "Disolver",
    "zoomin": "Zoom",
    "smoothleft": "Barrido izquierda",
    "smoothright": "Barrido derecha",
    "smoothup": "Barrido arriba",
    "smoothdown": "Barrido abajo",
    "slideleft": "Deslizar izquierda",
    "slideright": "Deslizar derecha",
    "slideup": "Deslizar arriba",
    "slidedown": "Deslizar abajo",
    "wipeleft": "Cortina izquierda",
    "wiperight": "Cortina derecha",
    "circleopen": "Círculo abrir",
    "circleclose": "Círculo cerrar",
    "radial": "Radial",
    "pixelize": "Pixelar",
    "hblur": "Desenfoque",
    "squeezeh": "Comprimir",
    "diagtl": "Diagonal",
    "hlslice": "Rebanadas",
    "vertopen": "Apertura vertical",
    "horzopen": "Apertura horizontal",
}

MOTIONS = {
    "none": "Estático",
    "zoom_in": "Acercar",
    "zoom_out": "Alejar",
    "pan_left": "Panorámica izq.",
    "pan_right": "Panorámica der.",
    "pan_up": "Subir",
    "pan_down": "Bajar",
}

COLOR_FILTERS: dict[str, tuple[str, str]] = {
    "none": ("Original", ""),
    "vivid": ("Vívido", "eq=saturation=1.35:contrast=1.06"),
    "cinematic": (
        "Cinemático",
        "eq=contrast=1.08:saturation=0.92,colorbalance=rs=-0.05:bs=0.07:rh=0.07:bh=-0.05,vignette=PI/5",
    ),
    "warm": ("Cálido", "colorbalance=rm=0.08:gm=0.02:bm=-0.08"),
    "cool": ("Frío", "colorbalance=rm=-0.06:bm=0.08"),
    "bw": ("Blanco y negro", "hue=s=0,eq=contrast=1.15"),
    "vintage": ("Vintage", "curves=preset=vintage"),
    "matte": ("Mate", "curves=all='0/0.07 1/0.94',eq=saturation=0.86"),
}

RESOLUTIONS = {"540p": 540, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}

QUALITY = {
    #          crf  cq   x264 preset  nvenc preset  audio kbps
    "draft": (28, 31, "ultrafast", "p1", 128),
    "standard": (21, 24, "veryfast", "p4", 192),
    "high": (18, 20, "medium", "p6", 256),
    "max": (15, 17, "slow", "p7", 320),
}

PRESETS = {
    "tiktok": {"name": "TikTok", "resolution": "1080p", "fps": 30, "codec": "h264", "quality": "high"},
    "reels": {"name": "Instagram Reels", "resolution": "1080p", "fps": 30, "codec": "h264", "quality": "high"},
    "shorts": {"name": "YouTube Shorts", "resolution": "1080p", "fps": 60, "codec": "h264", "quality": "high"},
    "draft": {"name": "Borrador rápido", "resolution": "720p", "fps": 30, "codec": "h264", "quality": "draft"},
    "master": {"name": "Máster 4K", "resolution": "2160p", "fps": 30, "codec": "h265", "quality": "max"},
}


class ExportOptions(BaseModel):
    resolution: str = "1080p"
    fps: Optional[int] = None
    codec: str = "h264"  # h264 | h265 | av1
    quality: str = "high"
    hardware: bool = True
    audio_only: bool = False
    subtitles_file: bool = False  # .srt adicional
    thumbnail: bool = False
    filename: Optional[str] = None
    burn_captions: bool = True


@dataclass
class RenderSize:
    width: int
    height: int
    fps: int


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def output_size(project: Project, opts: ExportOptions) -> RenderSize:
    short = RESOLUTIONS.get(opts.resolution, 1080)
    w, h = project.format.width, project.format.height
    k = short / min(w, h)
    return RenderSize(_even(w * k), _even(h * k), int(opts.fps or project.format.fps or 30))


def video_codec_args(codec: str, quality: str, hardware: bool) -> list[str]:
    crf, cq, x264p, nvp, _ = QUALITY.get(quality, QUALITY["high"])
    caps = ffmpeg.capabilities()
    enc = set(caps.get("encoders", []))
    nv = hardware and caps.get("nvenc")
    if codec == "av1":
        if nv and "av1_nvenc" in enc:
            return ["-c:v", "av1_nvenc", "-preset", nvp, "-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-pix_fmt", "yuv420p"]
        if "libsvtav1" in enc:
            return ["-c:v", "libsvtav1", "-crf", str(crf + 8), "-preset", "8", "-pix_fmt", "yuv420p"]
        codec = "h265"
    if codec == "h265":
        if nv and "hevc_nvenc" in enc:
            return ["-c:v", "hevc_nvenc", "-preset", nvp, "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                    "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        if "libx265" in enc:
            return ["-c:v", "libx265", "-preset", x264p, "-crf", str(crf + 2), "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    if nv and "h264_nvenc" in enc:
        return ["-c:v", "h264_nvenc", "-preset", nvp, "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", x264p, "-crf", str(crf), "-profile:v", "high", "-pix_fmt", "yuv420p"]


def _intermediate_args() -> list[str]:
    caps = ffmpeg.capabilities()
    if caps.get("nvenc"):
        return ["-c:v", "h264_nvenc", "-preset", "p2", "-rc", "constqp", "-qp", "14", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p"]


def _atempo(speed: float) -> str:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def _fit_chain(fit: str, w: int, h: int) -> str:
    """Encadena filtros que llevan [in] a exactamente w×h. Devuelve un subgrafo."""
    if fit == "contain":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    if fit == "blur":
        return (
            f"split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:4,eq=brightness=-0.08[bg];"
            f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _motion_expr(motion: str, frames: int) -> tuple[str, str, str]:
    p = f"(on/{max(1, frames - 1)})"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if motion == "zoom_in":
        return f"1+0.18*{p}", center_x, center_y
    if motion == "zoom_out":
        return f"1.18-0.18*{p}", center_x, center_y
    if motion == "pan_left":
        return "1.16", f"(iw-iw/zoom)*(1-{p})", center_y
    if motion == "pan_right":
        return "1.16", f"(iw-iw/zoom)*{p}", center_y
    if motion == "pan_up":
        return "1.16", center_x, f"(ih-ih/zoom)*(1-{p})"
    if motion == "pan_down":
        return "1.16", center_x, f"(ih-ih/zoom)*{p}"
    return "1", "0", "0"


def _segment_command(clip: Clip, media_path: str, has_audio: bool, length: float, size: RenderSize,
                     out: Path) -> list[str]:
    w, h, fps = size.width, size.height, size.fps
    color = COLOR_FILTERS.get(clip.filter, ("", ""))[1]
    args = [ffmpeg.binary()]
    if clip.kind == "image":
        frames = max(1, int(round(length * fps)))
        k = 1.5 if max(w, h) > 2000 else 2.0
        bw, bh = _even(w * k), _even(h * k)
        z, x, y = _motion_expr(clip.motion, frames)
        args += ["-i", media_path, "-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        vf = (
            f"[0:v]format=yuv444p,{_fit_chain(clip.fit, bw, bh)},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}"
            f"{',' + color if color else ''},trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v]"
        )
        af = "[1:a]anull[a]"
    else:
        dur_src = length * clip.speed
        args += ["-ss", f"{clip.src_in:.3f}", "-t", f"{dur_src + 0.1:.3f}", "-i", media_path]
        if not has_audio:
            args += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        vf = (
            f"[0:v]setpts=(PTS-STARTPTS)/{clip.speed:.4f},fps={fps},{_fit_chain(clip.fit, w, h)}"
            f"{',' + color if color else ''},tpad=stop_mode=clone:stop_duration={length:.3f},"
            f"trim=duration={length:.3f},setpts=PTS-STARTPTS,format=yuv420p[v]"
        )
        if has_audio:
            af = (
                f"[0:a]asetpts=PTS-STARTPTS,{_atempo(clip.speed)},volume={clip.volume:.3f},"
                f"aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={length:.3f}[a]"
            )
        else:
            af = "[1:a]anull[a]"
    args += [
        "-filter_complex",
        f"{vf};{af}",
        "-map",
        "[v]",
        "-map",
        "[a]",
        *_intermediate_args(),
        "-r",
        str(fps),
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        "-t",
        f"{length:.3f}",
        str(out),
    ]
    return args


def _segment_key(clip: Clip, media_path: str, length: float, size: RenderSize) -> str:
    p = Path(media_path)
    st = p.stat()
    payload = {
        "clip": clip.model_dump(exclude={"id", "transition"}),
        "path": str(p.resolve()),
        "mtime": st.st_mtime,
        "bytes": st.st_size,
        "len": round(length, 3),
        "size": [size.width, size.height, size.fps],
        "enc": _intermediate_args(),
        "v": 3,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


Progress = Callable[[float, str], None]


def render_project(
    project: Project,
    opts: ExportOptions,
    out_path: Path,
    progress: Progress | None = None,
    track: Callable | None = None,
) -> dict:
    progress = progress or (lambda p, m: None)
    size = output_size(project, opts)
    work = config.CACHE_DIR / "render" / f"{project.id}-{new_id()}"
    work.mkdir(parents=True, exist_ok=True)
    seg_dir = config.CACHE_DIR / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    total = sum(lengths) - sum(trans)

    segments: list[Path] = []
    if not project.clips:
        total = max(1.0, _audio_extent(project))
        black = work / "black.mkv"
        ffmpeg.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s={size.width}x{size.height}:r={size.fps}:d={total:.3f}",
                    "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                    *_intermediate_args(), "-c:a", "pcm_s16le", "-t", f"{total:.3f}", str(black)])
        segments.append(black)
        lengths, trans = [total], []

    for i, clip in enumerate(project.clips):
        media = get_media(clip.media_id)
        if not media or not Path(media.path).is_file():
            raise FileNotFoundError(f"Falta el medio del clip {i + 1}")
        seg = seg_dir / f"{_segment_key(clip, media.path, lengths[i], size)}.mkv"
        if not seg.exists():
            tmp = seg.with_suffix(".part.mkv")
            cmd = _segment_command(clip, media.path, media.has_audio, lengths[i], size, tmp)
            base = 0.5 * i / max(1, len(project.clips))
            ffmpeg.run_with_progress(
                cmd,
                lengths[i],
                lambda p, b=base: progress(b + 0.5 * p / max(1, len(project.clips)), f"Preparando clip {i + 1}/{len(project.clips)}"),
                track=track,
            )
            tmp.replace(seg)
        segments.append(seg)
        progress(0.5 * (i + 1) / max(1, len(project.clips)), f"Clip {i + 1} listo")

    # ----------------------------------------------------------- composición
    inputs: list[str] = []
    for seg in segments:
        inputs += ["-i", str(seg)]
    graph: list[str] = []
    n = len(segments)
    for i in range(n):
        graph.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[sv{i}]")
        graph.append(f"[{i}:a]asetpts=PTS-STARTPTS[sa{i}]")
    vcur, acur, acc = "sv0", "sa0", lengths[0]
    for i in range(1, n):
        t = trans[i - 1]
        vtag, atag = f"vx{i}", f"ax{i}"
        if t > 0:
            ttype = project.clips[i - 1].transition.type
            ttype = ttype if ttype in TRANSITIONS else "fade"
            graph.append(f"[{vcur}][sv{i}]xfade=transition={ttype}:duration={t:.3f}:offset={acc - t:.3f}[{vtag}]")
            graph.append(f"[{acur}][sa{i}]acrossfade=d={t:.3f}:c1=tri:c2=tri[{atag}]")
        else:
            graph.append(f"[{vcur}][sv{i}]concat=n=2:v=1:a=0[{vtag}]")
            graph.append(f"[{acur}][sa{i}]concat=n=2:v=0:a=1[{atag}]")
        vcur, acur = vtag, atag
        acc += lengths[i] - t

    # Subtítulos y textos
    has_text = (project.captions.enabled and project.captions.words) or project.texts
    vfinal = vcur
    if has_text and opts.burn_captions and not opts.audio_only:
        ass = work / "captions.ass"
        captions.write_ass(
            ass,
            width=size.width,
            height=size.height,
            words=[w.model_dump() for w in project.captions.words],
            style_id=project.captions.style,
            max_words=project.captions.max_words,
            uppercase=project.captions.uppercase,
            position=project.captions.position,
            scale=project.captions.scale,
            overlays=[t.model_dump() for t in project.texts],
            captions_enabled=project.captions.enabled,
        )
        fonts = f":fontsdir={ffmpeg.escape_filter_path(config.FONTS_DIR)}" if config.FONTS_DIR.is_dir() else ""
        graph.append(f"[{vcur}]subtitles=captions.ass{fonts},format=yuv420p[vout]")
        vfinal = "vout"

    # Pistas de audio
    voices, musics = [], []
    idx = n
    for item in project.audio:
        media = get_media(item.media_id)
        if not media or not Path(media.path).is_file():
            continue
        src_len = (item.src_out if item.src_out is not None else (media.duration or total)) - item.src_in
        if item.start >= total or src_len <= 0:
            continue
        play = min(src_len, total - item.start) if not item.loop else total - item.start
        if item.loop:
            inputs += ["-stream_loop", "-1"]
        inputs += ["-ss", f"{item.src_in:.3f}", "-t", f"{play:.3f}", "-i", media.path]
        chain = f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={item.volume:.3f}"
        if item.fade_in > 0:
            chain += f",afade=t=in:d={item.fade_in:.2f}"
        if item.fade_out > 0:
            chain += f",afade=t=out:st={max(0.0, play - item.fade_out):.3f}:d={item.fade_out:.2f}"
        delay = int(item.start * 1000)
        if delay:
            chain += f",adelay={delay}|{delay}"
        tag = f"tr{idx}"
        graph.append(f"{chain}[{tag}]")
        (musics if item.role == "music" else voices).append(tag)
        idx += 1

    mix_inputs = [acur]
    if voices:
        if len(voices) > 1:
            graph.append("".join(f"[{v}]" for v in voices) + f"amix=inputs={len(voices)}:normalize=0:duration=longest[voxmix]")
            vox = "voxmix"
        else:
            vox = voices[0]
        if musics and project.ducking:
            graph.append(f"[{vox}]asplit=2[voxout][voxsc]")
            mix_inputs.append("voxout")
            vox_sc = "voxsc"
        else:
            mix_inputs.append(vox)
            vox_sc = None
    else:
        vox_sc = None
    if musics:
        if len(musics) > 1:
            graph.append("".join(f"[{m}]" for m in musics) + f"amix=inputs={len(musics)}:normalize=0:duration=longest[musmix]")
            mus = "musmix"
        else:
            mus = musics[0]
        if vox_sc:
            graph.append(f"[{mus}][{vox_sc}]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350:makeup=1[musduck]")
            mus = "musduck"
        mix_inputs.append(mus)
    # loudnorm falla con silencio digital puro: sólo se aplica si hay sonido real.
    has_sound = bool(voices or musics) or any(
        c.kind == "video" and (m := get_media(c.media_id)) is not None and m.has_audio for c in project.clips
    )
    post = ",loudnorm=I=-14:TP=-1.5:LRA=11" if project.loudnorm and has_sound else ""
    if len(mix_inputs) > 1:
        graph.append("".join(f"[{m}]" for m in mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=longest{post},aresample=48000,apad,atrim=duration={total:.3f}[aout]")
    else:
        graph.append(f"[{acur}]anull{post},aresample=48000,apad,atrim=duration={total:.3f}[aout]")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _, _, _, _, akbps = QUALITY.get(opts.quality, QUALITY["high"])
    if opts.audio_only:
        graph.append(f"[{vcur}]nullsink")
        cmd = [ffmpeg.binary(), *inputs, "-filter_complex", ";".join(graph), "-map", "[aout]"]
        if out_path.suffix.lower() == ".wav":
            cmd += ["-c:a", "pcm_s16le"]
        else:
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{min(320, akbps)}k"]
        cmd += ["-t", f"{total:.3f}", str(out_path)]
    else:
        cmd = [
            ffmpeg.binary(),
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{vfinal}]",
            "-map",
            "[aout]",
            *video_codec_args(opts.codec, opts.quality, opts.hardware),
            "-r",
            str(size.fps),
            "-c:a",
            "aac",
            "-b:a",
            f"{akbps}k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            f"{total:.3f}",
            str(out_path),
        ]
    (work / "command.json").write_text(json.dumps(cmd, ensure_ascii=False, indent=1), "utf-8")
    started = time.time()
    ffmpeg.run_with_progress(cmd, total, lambda p: progress(0.5 + 0.48 * p, "Renderizando"), cwd=work, track=track)

    extras: dict[str, str] = {}
    if opts.subtitles_file and project.captions.words:
        srt = out_path.with_suffix(".srt")
        srt.write_text(captions.build_srt([w.model_dump() for w in project.captions.words]), "utf-8")
        extras["srt"] = str(srt)
    if opts.thumbnail and not opts.audio_only:
        thumb = out_path.with_suffix(".jpg")
        ffmpeg.thumbnail(out_path, thumb, at=min(1.0, total / 3), width=size.width)
        extras["thumbnail"] = str(thumb)
    progress(1.0, "Listo")
    return {
        "path": str(out_path),
        "duration": round(total, 3),
        "width": size.width,
        "height": size.height,
        "fps": size.fps,
        "seconds": round(time.time() - started, 1),
        "bytes": out_path.stat().st_size,
        "extras": extras,
    }


def _audio_extent(project: Project) -> float:
    end = 0.0
    for a in project.audio:
        m = get_media(a.media_id)
        length = (a.src_out if a.src_out is not None else (m.duration if m else 0) or 0) - a.src_in
        end = max(end, a.start + max(0.0, length))
    return end


def export_filename(project: Project, opts: ExportOptions) -> Path:
    base = opts.filename or project.name or "reel"
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in base).strip() or "reel"
    ext = ".mp3" if opts.audio_only else ".mp4"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return config.EXPORTS_DIR / f"{safe}-{opts.resolution}-{stamp}{ext}"


def suggested_duration(text: str, wpm: float = 165) -> float:
    return max(3.0, math.ceil(len(text.split()) / wpm * 60))

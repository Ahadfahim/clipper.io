"""Job handlers: download, analyze, render_preview (review preview + QA), render_final."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlmodel import select

from clipper.db.engine import WriteTx
from clipper.db.models import Analysis, Campaign, Clip, Moment, Review, ReviewBatch, Source
from clipper.db.types import BatchStatus, ClipStatus, SourceStatus
from clipper.events.types import ClipUpdated, PreviewReplaced
from clipper.media.download import file_hash
from clipper.media.edl.qa import measure, qa_report
from clipper.media.edl.render import encode_to_size, render_edl, thumbnail
from clipper.media.encode import final_profile, review_profile
from clipper.media.ffmpeg import detect_silences, energy_curve, probe, run_ffmpeg, scene_cuts
from clipper.rules.spec import ClipSpec
from clipper.services.media import load_faces
from clipper.worker.jobs import JobContext, JobQueue

if TYPE_CHECKING:
    from clipper.core import Core


def _source(core: Core, source_id: int) -> Source:
    with core.db.read() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise ValueError(f"source {source_id} not found")
        return src


def _set_source(core: Core, source_id: int, **fields: Any) -> None:
    def job(tx: WriteTx) -> None:
        src = tx.session.get(Source, source_id)
        assert src is not None
        for k, v in fields.items():
            setattr(src, k, v)
        tx.add(src)

    core.db.write(job)


# ---------------------------------------------------------------- download


def download(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
    core = ctx.core
    source_id = int(data["source_id"])
    src = _source(core, source_id)
    _set_source(core, source_id, status=SourceStatus.DOWNLOADING)
    dest = core.dir("sources") / f"campaign_{src.campaign_id}"
    try:
        res = core.adapters.downloader.download(str(data["url"]), dest)
    except Exception as exc:
        _set_source(core, source_id, status=SourceStatus.FAILED)
        raise RuntimeError(
            f"{exc}\n\nDownload it yourself and put the video in {dest} (Clipper attaches it on its own), "
            "or use Attach file on the source."
        ) from exc
    ctx.progress(0.8)
    digest = file_hash(res.path)
    with core.db.read() as s:
        twin = s.exec(select(Source).where(Source.hash == digest, Source.id != source_id)).first()
    path = res.path
    if twin is not None and twin.path and Path(twin.path).exists() and twin.path != str(res.path):
        res.path.unlink(missing_ok=True)  # same file already on disk (PLAN §6: skip by hash)
        path = Path(twin.path)
        sidecar = res.path.with_suffix(".words.json")
        sidecar.unlink(missing_ok=True)
    _set_source(
        core,
        source_id,
        path=str(path),
        hash=digest,
        duration=res.duration or probe(path, core.settings).duration,
        title=res.title,
        heatmap_json=res.heatmap,
        status=SourceStatus.DOWNLOADED,
    )
    if data.get("analyze", True):
        ctx.enqueue("analyze", {"source_id": source_id, "chapters": res.chapters})
    return {
        "source_id": source_id,
        "path": str(path),
        "duration": res.duration,
        "deduplicated": path != res.path,
    }


# ---------------------------------------------------------------- analyze


def heatmap_peaks(heatmap: list[dict[str, float]], top: int = 5) -> list[dict[str, float]]:
    ranked = sorted(heatmap, key=lambda h: -float(h.get("value", 0.0)))[:top]
    return [
        {"start": float(h["start_time"]), "end": float(h["end_time"]), "value": round(float(h["value"]), 3)}
        for h in ranked
    ]


def energy_spikes(curve: list[tuple[float, float]], z: float = 1.5) -> list[dict[str, float]]:
    vals = [v for _, v in curve if v > -70]
    if len(vals) < 4:
        return []
    mean, sd = statistics.fmean(vals), statistics.pstdev(vals) or 1.0
    return [
        {"t": t, "lufs": round(v, 1), "z": round((v - mean) / sd, 2)}
        for t, v in curve
        if (v - mean) / sd >= z
    ]


def analyze(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
    core = ctx.core
    settings = core.settings
    source_id = int(data["source_id"])
    src = _source(core, source_id)
    if not src.path:
        raise ValueError(f"source {source_id} is not downloaded")
    video = Path(src.path)
    _set_source(core, source_id, status=SourceStatus.ANALYZING)
    work = core.dir("work") / f"src_{source_id}"
    work.mkdir(parents=True, exist_ok=True)
    info = probe(video, settings)
    wav = work / "audio16k.wav"
    if info.has_audio:
        run_ffmpeg(["-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)], settings=settings)
    ctx.progress(0.1)
    transcript = core.adapters.transcriber.transcribe(wav, media=video)
    transcript_path = work / "transcript.json"
    transcript_path.write_text(json.dumps(transcript.to_json()), encoding="utf-8")
    ctx.progress(0.5)
    cuts = scene_cuts(video, settings)
    curve = energy_curve(video, settings) if info.has_audio else []
    silences = (
        detect_silences(video, settings, noise_db=settings.media.silence_threshold_db, min_s=0.3)
        if info.has_audio
        else []
    )
    (work / "energy.json").write_text(json.dumps(curve), encoding="utf-8")
    ctx.progress(0.7)
    faces = core.adapters.faces.track(video, info.duration)
    faces_path = work / "faces.json"
    faces_path.write_text(json.dumps([[t, b.model_dump()] for t, b in faces]), encoding="utf-8")
    proxy = work / "proxy.mp4"
    run_ffmpeg(
        ["-y", "-i", str(video), "-vf", f"scale=-2:{settings.media.proxy_height}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
         "-g", "15", "-c:a", "aac", "-b:a", "64k", str(proxy)],
        settings=settings,
    )  # fmt: skip
    ctx.progress(0.9)
    signals: dict[str, Any] = {
        "duration": info.duration,
        "heatmap_peaks": heatmap_peaks(list(src.heatmap_json or [])),
        "energy_spikes": energy_spikes(curve),
        "scene_cuts": [round(c, 2) for c in cuts[:500]],
        "silences": [[round(a, 3), round(b, 3)] for a, b in silences],
        "chapters": data.get("chapters", []),
        "faces_summary": {"samples": len(faces)},
        "language": transcript.language,
        "words": len(transcript.words),
    }

    def job(tx: WriteTx) -> None:
        row = tx.session.get(Analysis, source_id) or Analysis(source_id=source_id)
        row.transcript_path = str(transcript_path)
        row.scenes_json = signals["scene_cuts"]
        row.energy_path = str(work / "energy.json")
        row.faces_path = str(faces_path)
        row.signals_json = signals
        tx.add(row)
        s = tx.session.get(Source, source_id)
        assert s is not None
        s.status = SourceStatus.ANALYZED
        s.proxy_path = str(proxy)
        tx.add(s)

    core.db.write(job)
    return {
        "source_id": source_id,
        "words": len(transcript.words),
        "scene_cuts": len(cuts),
        "silences": len(silences),
    }


# ---------------------------------------------------------------- renders


def _clip_context(core: Core, clip_id: int) -> tuple[Clip, ClipSpec, list[Any]]:
    with core.db.read() as s:
        clip = s.get(Clip, clip_id)
        if clip is None:
            raise ValueError(f"clip {clip_id} not found")
        moment = s.get(Moment, clip.moment_id)
        campaign = s.get(Campaign, clip.campaign_id) if clip.campaign_id else None
        analysis = s.get(Analysis, moment.source_id) if moment else None
    spec = ClipSpec.model_validate(campaign.spec_json or {}) if campaign else ClipSpec()
    faces = load_faces(analysis.faces_path if analysis else None)
    return clip, spec, faces


def render_preview(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
    core = ctx.core
    clip_id = int(data["clip_id"])
    _clip, spec, faces = _clip_context(core, clip_id)
    edl, version, _ = core.edl.get(clip_id)
    out_dir = core.dir("previews")
    work = core.dir("work") / f"clip_{clip_id}_v{version}"
    out = out_dir / f"clip_{clip_id}_v{version}.mp4"
    res = render_edl(
        edl, out, review_profile(core.settings.media), core.adapters.encoder, core.settings, work
    )
    ctx.progress(0.7)
    limit = core.settings.media.discord_preview_mb * 1_000_000
    if out.stat().st_size > limit:
        sized = out_dir / f"clip_{clip_id}_v{version}_discord.mp4"
        encode_to_size(
            out, sized, core.settings.media.discord_preview_mb, core.settings, work / "size", height=1280
        )
        out = sized
    thumb = thumbnail(out, out_dir / f"clip_{clip_id}_v{version}.jpg", core.settings)
    report = qa_report(
        edl,
        measure(out, core.settings),
        min_s=spec.duration_min_s,
        max_s=spec.duration_max_s,
        face_track=faces,
    )

    def job(tx: WriteTx) -> int | None:
        c = tx.session.get(Clip, clip_id)
        assert c is not None
        c.preview_path = str(out)
        c.thumb_path = str(thumb)
        c.duration = res.duration
        c.qa_json = report
        c.version = version
        c.layout = edl.camera[0].layout
        c.caption_style = edl.captions.style
        if c.status in (ClipStatus.RENDERING, ClipStatus.DRAFT, ClipStatus.FAILED):
            c.status = ClipStatus.READY
        c.updated_at = core.clock.now()
        tx.add(c)
        tx.publish(ClipUpdated(clip_id=clip_id, status=c.status, campaign_id=c.campaign_id, version=version))
        review = tx.session.get(Review, clip_id)
        batch = tx.session.get(ReviewBatch, review.batch_id) if review and review.batch_id else None
        if batch is not None and batch.status != BatchStatus.SHIPPED:
            tx.publish(PreviewReplaced(clip_id=clip_id, batch_id=batch.id, preview_path=str(out)))
            return batch.id
        return None

    replaced_batch = core.db.write(job)
    return {
        "clip_id": clip_id,
        "preview": str(out),
        "duration": round(res.duration, 2),
        "qa_ok": report["ok"],
        "replaced_in_batch": replaced_batch,
    }


def render_final(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
    core = ctx.core
    clip_id = int(data["clip_id"])
    _clip_context(core, clip_id)
    edl, version, _ = core.edl.get(clip_id)
    out = core.dir("clips") / f"clip_{clip_id}_v{version}_final.mp4"
    work = core.dir("work") / f"clip_{clip_id}_v{version}_final"
    res = render_edl(edl, out, final_profile(core.settings.media), core.adapters.encoder, core.settings, work)

    def job(tx: WriteTx) -> None:
        c = tx.session.get(Clip, clip_id)
        assert c is not None
        c.path = str(out)
        c.version = version
        if c.status in (ClipStatus.APPROVED, ClipStatus.READY, ClipStatus.IN_REVIEW):
            c.status = ClipStatus.FINAL
        tx.add(c)
        tx.publish(ClipUpdated(clip_id=clip_id, status=c.status, campaign_id=c.campaign_id, version=version))

    core.db.write(job)
    return {
        "clip_id": clip_id,
        "path": str(out),
        "duration": round(res.duration, 2),
        "width": res.width,
        "height": res.height,
    }


def register_handlers(queue: JobQueue) -> None:
    queue.register("download", download, "download")
    queue.register("analyze", analyze, "gpu")
    queue.register("render_preview", render_preview, "encode")
    queue.register("render_final", render_final, "encode")

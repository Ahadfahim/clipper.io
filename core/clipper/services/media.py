"""Media service: sources, analysis outputs (paged), frames/contact sheets/OCR, moments and clip renders."""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Analysis, Campaign, Clip, Job, Moment, Question, Source
from clipper.db.types import ClipStatus, QuestionStatus, SourceStatus
from clipper.events.types import ClipUpdated
from clipper.media.download import file_hash
from clipper.media.edl.schema import Box, CaptionWord, SourceInfo, new_edl
from clipper.media.ffmpeg import probe, run_ffmpeg
from clipper.media.reframe import auto_camera_keys
from clipper.rules.spec import ClipSpec
from clipper.rules.urls import canonical_source
from clipper.services.base import Service, ServiceError

MAX_TRANSCRIPT_WORDS = 400
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
WAITING = (SourceStatus.FAILED, SourceStatus.LISTED, SourceStatus.QUEUED)
DROP_SCAN_EVERY_S = 10.0
_FOOTAGE_QUESTION = re.compile(r"download|footage|source|episode|video|frame\.io|wetransfer|drive", re.I)
SAFE_ZONE_FOR = {"tiktok": "tiktok", "youtube": "shorts", "instagram": "reels", "x": "shorts"}


def load_words(path: str | None) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("words", []))


def load_faces(path: str | None) -> list[tuple[float, Box]]:
    if not path or not Path(path).exists():
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(float(t), Box.model_validate(b)) for t, b in raw]


class MediaService(Service):
    # ------------------------------------------------------------ sources

    def request_download(self, campaign_id: int, url: str, *, analyze: bool = True) -> dict[str, Any]:
        key = canonical_source(url)

        def job(tx: WriteTx) -> tuple[int, str]:
            if tx.session.get(Campaign, campaign_id) is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            existing = [
                s
                for s in tx.session.exec(select(Source).where(Source.campaign_id == campaign_id)).all()
                if canonical_source(s.url) == key
            ]
            src = (
                existing[0]
                if existing
                else Source(campaign_id=campaign_id, url=url, status=SourceStatus.QUEUED)
            )
            if src.status in (SourceStatus.LISTED, SourceStatus.FAILED, SourceStatus.DELETED):
                src.status = SourceStatus.QUEUED
            tx.add(src)
            tx.flush()
            assert src.id is not None
            return src.id, src.status

        source_id, status = self.db.write(job)
        if status in (
            SourceStatus.DOWNLOADED,
            SourceStatus.ANALYZING,
            SourceStatus.ANALYZED,
            SourceStatus.DOWNLOADING,
        ):
            return {
                "source_id": source_id,
                "job_id": None,
                "status": status,
                "note": "already downloaded or in progress",
            }
        if status == SourceStatus.QUEUED and self._open_job("download", source_id):
            return {
                "source_id": source_id,
                "job_id": None,
                "status": status,
                "note": "download already queued",
            }
        job_id = self.core.jobs.enqueue(
            "download", {"source_id": source_id, "url": url, "analyze": analyze}, campaign_id=campaign_id
        )
        return {"source_id": source_id, "job_id": job_id, "status": "queued"}

    # ------------------------------------------------------------ sources you supply yourself

    def drop_folder(self, campaign_id: int) -> Path:
        """Where to put footage you downloaded yourself: Clipper attaches it on its own."""
        return self.core.dir("sources") / f"campaign_{campaign_id}"

    def attach_file(self, source_id: int, path: str | Path, *, by: str = "user") -> dict[str, Any]:
        """Use a video file you supplied as a source's footage (when the site can't be downloaded
        from: Frame.io, WeTransfer, Drive). A file outside the campaign's folder is copied in. Then the
        analysis is queued, which resumes the campaign's agent when it finishes."""
        src = self.source(source_id)
        if src.status in (SourceStatus.DOWNLOADING, SourceStatus.ANALYZING):
            raise ServiceError(f"source {source_id} is {src.status} right now")
        file = Path(path).expanduser()
        if not file.is_file():
            raise ServiceError(f"no such file: {file}")
        if file.suffix.lower() not in VIDEO_EXTS:
            raise ServiceError(f"{file.name} isn't a video ({', '.join(sorted(VIDEO_EXTS))})")
        try:
            info = probe(file, self.settings)
        except Exception as exc:
            raise ServiceError(f"{file.name} doesn't read as a video: {exc}") from exc
        if not info.duration or info.duration < 1:
            raise ServiceError(f"{file.name} has no playable video")
        folder = self.drop_folder(src.campaign_id)
        folder.mkdir(parents=True, exist_ok=True)
        if file.resolve().parent != folder.resolve():
            target = folder / file.name
            if target.exists():
                target = folder / f"{file.stem}_{source_id}{file.suffix}"
            shutil.copy2(file, target)
            file = target
        digest = file_hash(file)

        def job(tx: WriteTx) -> list[int]:
            row = tx.session.get(Source, source_id)
            assert row is not None
            row.path, row.hash, row.duration = str(file), digest, info.duration
            row.title = row.title or file.stem
            row.status = SourceStatus.DOWNLOADED
            tx.add(row)
            # the agent asked you for this footage: that question is answered now
            asked = tx.session.exec(
                select(Question).where(
                    Question.campaign_id == row.campaign_id, Question.status == QuestionStatus.OPEN
                )
            ).all()
            return [q.id for q in asked if q.id is not None and _FOOTAGE_QUESTION.search(q.text)]

        questions = self.db.write(job)
        job_id = self.request_analyze(source_id)
        for qid in questions:
            with contextlib.suppress(ServiceError):  # answered meanwhile
                self.core.notify.answer(
                    qid,
                    f"Footage supplied by hand: {file.name}. Analysis is queued (job {job_id}).",
                    by=by,
                    via="file",
                )
        self.core.notify.alert(
            "info",
            f"Attached {file.name} to source {source_id}; analyzing",
            source="media",
            campaign_id=src.campaign_id,
        )
        return {"source_id": source_id, "path": str(file), "duration": info.duration, "job_id": job_id}

    def scan_drop_folders(self) -> list[dict[str, Any]]:
        """Attach new videos you put in ``sources/campaign_<id>/`` to that campaign's source that is
        waiting for footage (failed, listed or queued). A file is taken once its size has stopped
        changing between two scans, so a copy in progress is left alone."""
        now = time.monotonic()
        if now - getattr(self, "_last_scan", 0.0) < DROP_SCAN_EVERY_S:
            return []
        self._last_scan = now
        sizes: dict[str, int] = getattr(self, "_drop_sizes", {})
        root = self.core.dir("sources")
        with self.db.read() as s:
            sources = s.exec(select(Source)).all()
        known = {str(Path(x.path).resolve()).lower() for x in sources if x.path}
        attached: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for folder in root.glob("campaign_*"):
            m = re.fullmatch(r"campaign_(\d+)", folder.name)
            if m is None or not folder.is_dir():
                continue
            cid = int(m.group(1))
            waiting = sorted(
                (x for x in sources if x.campaign_id == cid and x.status in WAITING and x.id is not None),
                key=lambda x: (x.status != SourceStatus.FAILED, x.id),
            )
            for f in sorted(folder.iterdir(), key=lambda f: f.stat().st_mtime):
                if f.suffix.lower() not in VIDEO_EXTS or not f.is_file():
                    continue
                if str(f.resolve()).lower() in known:
                    continue
                size = f.stat().st_size
                seen[str(f)] = size
                if not waiting or size == 0 or sizes.get(str(f)) != size:
                    continue  # nothing waiting, or still being copied
                src = waiting.pop(0)
                assert src.id is not None
                try:
                    attached.append(self.attach_file(src.id, f, by="user"))
                except ServiceError as exc:
                    self.core.notify.alert(
                        "warning", f"Couldn't use {f.name}: {exc}", source="media", campaign_id=cid
                    )
                    known.add(str(f.resolve()).lower())
        self._drop_sizes = seen
        return attached

    def _open_job(self, kind: str, source_id: int) -> bool:
        with self.db.read() as s:
            rows = s.exec(
                select(Job).where(Job.kind == kind, col(Job.status).in_(["queued", "running"]))
            ).all()
        return any(r.input_json.get("source_id") == source_id for r in rows)

    def request_analyze(self, source_id: int) -> int:
        src = self.source(source_id)
        if not src.path:
            raise ServiceError(f"source {source_id} is not downloaded yet")
        return self.core.jobs.enqueue("analyze", {"source_id": source_id}, campaign_id=src.campaign_id)

    def source(self, source_id: int) -> Source:
        with self.db.read() as s:
            src = s.get(Source, source_id)
            if src is None:
                raise ServiceError(f"source {source_id} not found")
            return src

    def analysis(self, source_id: int) -> Analysis:
        with self.db.read() as s:
            a = s.get(Analysis, source_id)
            if a is None:
                raise ServiceError(f"source {source_id} has no analysis yet")
            return a

    # ------------------------------------------------------------ reads for the editor

    def transcript(
        self, source_id: int, start: float, end: float, max_words: int = MAX_TRANSCRIPT_WORDS
    ) -> dict[str, Any]:
        words = [
            w
            for w in load_words(self.analysis(source_id).transcript_path)
            if w["end"] > start and w["start"] < end
        ]
        page = words[:max_words]
        next_from = page[-1]["end"] if len(words) > max_words else None
        text = " ".join(
            f"[{w['start']:.1f}]{w['text']}" if i % 12 == 0 else w["text"] for i, w in enumerate(page)
        )
        return {
            "source_id": source_id,
            "from": start,
            "to": end,
            "words": len(page),
            "text": text,
            "next_from": next_from,
        }

    def signals(self, source_id: int) -> dict[str, Any]:
        a = self.analysis(source_id)
        sig = dict(a.signals_json)
        return {
            "source_id": source_id,
            "duration": sig.get("duration"),
            "heatmap_peaks": sig.get("heatmap_peaks", [])[:8],
            "energy_spikes": sig.get("energy_spikes", [])[:12],
            "scene_cuts": len(sig.get("scene_cuts", [])),
            "scene_cut_sample": sig.get("scene_cuts", [])[:20],
            "silences": len(sig.get("silences", [])),
            "chapters": sig.get("chapters", [])[:12],
            "faces": sig.get("faces_summary"),
        }

    def comments(self, source_id: int, limit: int = 30) -> list[dict[str, Any]]:
        src = self.source(source_id)
        out = self.core.adapters.downloader.comments(src.url, limit=limit)
        return [{"text": c.text[:200], "likes": c.likes, "timestamps": c.timestamps} for c in out]

    def _work(self, name: str) -> Path:
        path = self.core.dir("work") / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def frames(
        self,
        *,
        source_id: int | None = None,
        clip_id: int | None = None,
        times: list[float],
        width: int = 360,
    ) -> list[tuple[float, Path]]:
        if not times or len(times) > 8:
            raise ServiceError("ask for 1-8 frames at a time")
        video, label = self._video_for(source_id, clip_id)
        out: list[tuple[float, Path]] = []
        work = self._work(f"frames_{label}")
        for t in times:
            dest = work / f"t{t:09.3f}.jpg"
            if not dest.exists():
                run_ffmpeg(
                    [
                        "-y",
                        "-ss",
                        f"{t:.3f}",
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={width}:-2",
                        "-q:v",
                        "5",
                        str(dest),
                    ],
                    settings=self.settings,
                )
            out.append((t, dest))
        return out

    def _video_for(self, source_id: int | None, clip_id: int | None) -> tuple[Path, str]:
        if clip_id is not None:
            with self.db.read() as s:
                clip = s.get(Clip, clip_id)
                if clip is None:
                    raise ServiceError(f"clip {clip_id} not found")
                path = clip.path or clip.preview_path
            if not path:
                raise ServiceError(f"clip {clip_id} has no render yet")
            return Path(path), f"clip{clip_id}"
        if source_id is not None:
            src = self.source(source_id)
            if not src.path:
                raise ServiceError(f"source {source_id} is not downloaded yet")
            return Path(src.path), f"src{source_id}"
        raise ServiceError("give a source_id or a clip_id")

    def contact_sheet(self, clip_id: int, n: int = 9) -> Path:
        video, label = self._video_for(None, clip_id)
        info = probe(video, self.settings)
        cols = 3
        rows = max(1, (n + cols - 1) // cols)
        fps = n / max(info.duration, 0.1)
        dest = self._work(f"sheet_{label}") / "contact.jpg"
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(video),
                "-vf",
                f"fps={fps:.4f},scale=240:-2,tile={cols}x{rows}",
                "-frames:v",
                "1",
                "-q:v",
                "5",
                str(dest),
            ],
            settings=self.settings,
        )
        return dest

    def ocr_frames(
        self, *, source_id: int | None = None, clip_id: int | None = None, times: list[float]
    ) -> list[dict[str, Any]]:
        frames = self.frames(source_id=source_id, clip_id=clip_id, times=times, width=960)
        return [{"t": t, "text": self.core.adapters.ocr.read(p)[:300]} for t, p in frames]

    # ------------------------------------------------------------ moments and clips

    def save_moments(self, campaign_id: int, source_id: int, moments: list[dict[str, Any]]) -> list[int]:
        src = self.source(source_id)
        if src.campaign_id != campaign_id:
            raise ServiceError(f"source {source_id} belongs to campaign {src.campaign_id}")
        duration = src.duration or 0.0

        def job(tx: WriteTx) -> list[int]:
            ids: list[int] = []
            for m in moments:
                start, end = float(m["start"]), float(m["end"])
                if end - start < 3 or (duration and end > duration + 0.5):
                    raise ServiceError(f"moment {start}-{end} is invalid for a {duration:.0f}s source")
                row = Moment(
                    source_id=source_id,
                    campaign_id=campaign_id,
                    start=start,
                    end=end,
                    hook=str(m.get("hook", ""))[:300],
                    payoff=str(m.get("payoff", ""))[:300],
                    scores_json=dict(m.get("scores", {})),
                    final_score=float(m.get("final_score", 0.0)),
                    reason=str(m.get("reason", ""))[:600],
                )
                tx.add(row)
                tx.flush()
                assert row.id is not None
                ids.append(row.id)
            return ids

        return self.db.write(job)

    def render_moment(
        self,
        moment_id: int,
        *,
        layout: str | None = None,
        caption_style: str | None = None,
        platform: str | None = None,
    ) -> dict[str, Any]:
        with self.db.read() as s:
            moment = s.get(Moment, moment_id)
            if moment is None:
                raise ServiceError(f"moment {moment_id} not found")
            src = s.get(Source, moment.source_id)
            analysis = s.get(Analysis, moment.source_id)
            campaign = s.get(Campaign, moment.campaign_id) if moment.campaign_id else None
        if src is None or not src.path:
            raise ServiceError("the moment's source is not downloaded")
        spec = ClipSpec.model_validate(campaign.spec_json or {}) if campaign else ClipSpec()
        info = probe(Path(src.path), self.settings)
        words = [
            CaptionWord(t=w["start"], end=w["end"], text=w["text"], speaker=w.get("speaker"))
            for w in load_words(analysis.transcript_path if analysis else None)
        ]
        faces = load_faces(analysis.faces_path if analysis else None)
        keys = auto_camera_keys(faces, moment.start, moment.end)
        target = platform or (spec.platforms[0] if spec.platforms else "tiktok")
        style = caption_style or spec.caption_style or self.settings.media.default_caption_style
        edl = new_edl(
            SourceInfo(
                source_id=src.id,
                path=src.path,
                duration=info.duration,
                width=info.width,
                height=info.height,
                fps=info.fps or 30,
                has_audio=info.has_audio,
            ),
            moment.start,
            min(moment.end, info.duration),
            words=words,
            caption_style=style,
            safe_zone=SAFE_ZONE_FOR.get(target, "tiktok"),  # type: ignore[arg-type]
        )
        if layout in ("crop", "split", "fit"):
            keys = [k.model_copy(update={"layout": layout}) for k in keys]
        edl = edl.model_copy(update={"camera": keys or edl.camera})
        if moment.hook:
            edl = edl.model_copy(update={"hook": edl.hook.model_copy(update={"text": moment.hook})})

        def job(tx: WriteTx) -> int:
            clip = Clip(
                moment_id=moment_id,
                campaign_id=moment.campaign_id,
                layout=edl.camera[0].layout,
                caption_style=style,
                status=ClipStatus.RENDERING,
            )
            tx.add(clip)
            tx.flush()
            assert clip.id is not None
            tx.publish(
                ClipUpdated(clip_id=clip.id, status=clip.status, campaign_id=clip.campaign_id, version=1)
            )
            return clip.id

        clip_id = self.db.write(job)
        self.core.edl.init(clip_id, edl, actor="system", reason=f"first cut of moment {moment_id}")
        job_id = self.core.jobs.enqueue(
            "render_preview", {"clip_id": clip_id}, campaign_id=moment.campaign_id
        )
        return {"clip_id": clip_id, "job_id": job_id, "duration": round(edl.duration, 2)}

    def request_preview(self, clip_id: int) -> int:
        with self.db.read() as s:
            clip = s.get(Clip, clip_id)
            if clip is None:
                raise ServiceError(f"clip {clip_id} not found")
            cid = clip.campaign_id
        self._set_clip_status(clip_id, ClipStatus.RENDERING)
        return self.core.jobs.enqueue("render_preview", {"clip_id": clip_id}, campaign_id=cid)

    def request_final(self, clip_id: int) -> int:
        with self.db.read() as s:
            clip = s.get(Clip, clip_id)
            if clip is None:
                raise ServiceError(f"clip {clip_id} not found")
            cid = clip.campaign_id
        return self.core.jobs.enqueue("render_final", {"clip_id": clip_id}, campaign_id=cid)

    def _set_clip_status(self, clip_id: int, status: str) -> None:
        def job(tx: WriteTx) -> None:
            clip = tx.session.get(Clip, clip_id)
            if clip is not None and clip.status not in (
                ClipStatus.APPROVED,
                ClipStatus.FINAL,
                ClipStatus.POSTED,
            ):
                clip.status = status
                tx.add(clip)
                tx.publish(
                    ClipUpdated(
                        clip_id=clip_id, status=status, campaign_id=clip.campaign_id, version=clip.version
                    )
                )

        self.db.write(job)

    def job_status(self, job_id: int) -> dict[str, Any]:
        with self.db.read() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise ServiceError(f"job {job_id} not found")
            return {
                "id": job.id,
                "kind": job.kind,
                "status": job.status,
                "progress": round(job.progress, 2),
                "error": job.error,
                "result": job.result_json,
            }

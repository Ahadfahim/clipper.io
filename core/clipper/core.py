"""``Core``: one object that wires settings, DB, event bus, guard, adapters and domain services.

``Core.create(settings)`` wires the real adapters (Windows machine); ``Core.create(settings, fakes=True)``
wires fakes for tests, CI and fixture mode. Everything else (tools, API, supervisor) takes a Core.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from clipper.agents.guard_context import DbGuardContext, make_block_logger
from clipper.agents.hooks import Guard
from clipper.browser.bridge import BrowserBridge, CompanionBridge, FakeBrowserBridge
from clipper.browser.manager import ChromeManager
from clipper.browser.windows import FakeWindowOps, Win32WindowOps, WindowOps
from clipper.clock import Clock, SystemClock
from clipper.db.engine import Database
from clipper.db.seed import seed_base
from clipper.events.bus import EventBus
from clipper.marketplaces.base import MarketplaceAdapter
from clipper.marketplaces.browser import RecipeMarketplace
from clipper.marketplaces.fake import FakeMarketplace
from clipper.media.download import Downloader, FakeDownloader, YtDlpDownloader
from clipper.media.edl.service import EdlService
from clipper.media.encode import Encoder, X264Encoder, make_encoder
from clipper.media.faces import FaceDetector, FakeFaceDetector, MediaPipeFaceDetector
from clipper.media.ocr import FakeOcr, OcrEngine, TesseractOcr
from clipper.media.transcribe import FakeTranscriber, Transcriber, WhisperXTranscriber
from clipper.publishing.base import PublishAdapter
from clipper.publishing.browser import BrowserPublisher
from clipper.publishing.fake import FakePublisher
from clipper.secrets import get_secret, set_secret
from clipper.settings import REPO_ROOT, Settings
from clipper.trends.source import FakeTrends, TrendsSource, YtDlpTrends

FIXTURE_VIDEO = REPO_ROOT / "tests" / "fixtures" / "media" / "talk_16x9.mp4"


@dataclass
class Adapters:
    marketplaces: dict[str, MarketplaceAdapter]
    publisher: PublishAdapter
    browser: BrowserBridge
    transcriber: Transcriber
    downloader: Downloader
    faces: FaceDetector
    ocr: OcrEngine
    trends: TrendsSource
    encoder: Encoder
    windows: WindowOps = field(default_factory=FakeWindowOps)
    extra: dict[str, object] = field(default_factory=lambda: {})

    @classmethod
    def fakes(cls, fixture: Path = FIXTURE_VIDEO) -> Adapters:
        return cls(
            marketplaces={
                "vyro": FakeMarketplace.with_samples("vyro"),
                "whop": FakeMarketplace.with_samples("whop"),
            },
            publisher=FakePublisher(),
            browser=FakeBrowserBridge(),
            transcriber=FakeTranscriber(),
            downloader=FakeDownloader(fixture),
            faces=FakeFaceDetector(),
            ocr=FakeOcr("SAMPLE WATERMARK"),
            trends=FakeTrends(),
            encoder=X264Encoder(),
        )

    @classmethod
    def real(cls, settings: Settings) -> Adapters:  # LOCAL-VERIFY: wiring of the Windows adapters
        token = get_secret("extension_pairing_token")
        if token is None:
            token = CompanionBridge.new_token()
            set_secret("extension_pairing_token", token)
        bridge = CompanionBridge(
            token, settings.browser.ws_host, settings.browser.ws_port, settings.browser.action_timeout_s
        )
        api = f"http://{settings.api.host}:{settings.api.port}"
        return cls(
            marketplaces={
                "vyro": RecipeMarketplace("vyro", bridge),
                "whop": RecipeMarketplace("whop", bridge),
            },
            publisher=BrowserPublisher(bridge, settings, file_url=f"{api}/api/files/upload/{{post_id}}"),
            browser=bridge,
            transcriber=WhisperXTranscriber(settings, hf_token=get_secret("hf_token")),
            downloader=YtDlpDownloader(settings),
            faces=MediaPipeFaceDetector(settings),
            ocr=TesseractOcr(ffmpeg=settings.paths.ffmpeg("ffmpeg")),
            trends=YtDlpTrends(settings),
            encoder=make_encoder(settings.media),
            windows=Win32WindowOps() if sys.platform == "win32" else FakeWindowOps(),
        )


class Core:
    def __init__(
        self, settings: Settings, db: Database, adapters: Adapters, clock: Clock | None = None
    ) -> None:
        # Local imports keep the import graph one-directional (services import Core only for typing).
        from clipper.services.agenda import AgendaService
        from clipper.services.campaigns import CampaignService
        from clipper.services.insights import InsightsService
        from clipper.services.market import MarketplaceService
        from clipper.services.media import MediaService
        from clipper.services.memory import MemoryService
        from clipper.services.notify import NotifyService
        from clipper.services.publishing import PublishingService
        from clipper.services.review import ReviewService
        from clipper.services.toggles import ToggleService
        from clipper.services.trends import TrendsService
        from clipper.services.usage import UsageTracker
        from clipper.services.wakeups import WakeupService
        from clipper.worker.jobs import JobQueue

        self.settings = settings
        self.db = db
        self.adapters = adapters
        self.clock: Clock = clock or SystemClock()
        self.bus = EventBus(db)
        self.guard_context = DbGuardContext(
            db, settings, self.clock, browser_url=adapters.browser.current_url
        )
        self.guard = Guard(self.guard_context, on_block=make_block_logger(db))
        self.edl = EdlService(db)
        self.jobs = JobQueue(self)
        self.campaigns = CampaignService(self)
        self.media = MediaService(self)
        self.review = ReviewService(self)
        self.publishing = PublishingService(self)
        self.market = MarketplaceService(self)
        self.toggles = ToggleService(self)
        self.notify = NotifyService(self)
        self.memory = MemoryService(self)
        self.agenda = AgendaService(self)
        self.wakeups = WakeupService(self)
        self.insights = InsightsService(self)
        self.trends = TrendsService(self)
        self.usage = UsageTracker(self)
        self.chrome = ChromeManager(settings, adapters.windows)
        from clipper.worker.handlers import register_handlers

        register_handlers(self.jobs)

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        fakes: bool = False,
        clock: Clock | None = None,
        db_path: Path | None = None,
    ) -> Core:
        path = db_path or settings.paths.database
        db = Database(path, create=True)
        seed_base(db, settings)
        adapters = Adapters.fakes() if fakes else Adapters.real(settings)
        return cls(settings, db, adapters, clock)

    def dir(self, name: str) -> Path:
        path = self.settings.paths.sub(name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def close(self) -> None:
        self.db.close()

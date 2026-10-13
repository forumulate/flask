"""
Flask extension: Forumulate embeds and cached public content as Jinja globals.

    from flask_forumulate import Forumulate
    forumulate = Forumulate(app)          # or forumulate.init_app(app)

Config keys are FORUMULATE_ORG, FORUMULATE_SPACE, FORUMULATE_BASE_URL, ... (the
same names as the dict keys in core.DEFAULTS, prefixed).
"""
import threading
import time
from typing import Any, Dict, Optional, Tuple

from markupsafe import Markup

from .core import DEFAULTS, ContentClient, embed_html, markdown_to_html, resolve

__version__ = "0.1.0"
__all__ = ["Forumulate"]


class _TTLCache:
    """In-process fallback when Flask-Caching is not installed."""

    def __init__(self) -> None:
        self._data: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            if hit[0] < time.monotonic():
                del self._data[key]
                return None
            return hit[1]

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            if len(self._data) > 2000:
                self._data.clear()
            self._data[key] = (time.monotonic() + ttl, value)


class Forumulate:
    def __init__(self, app: Optional[Any] = None) -> None:
        self._fallback = _TTLCache()
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        for key, value in DEFAULTS.items():
            app.config.setdefault("FORUMULATE_" + key, value)
        app.extensions["forumulate"] = self
        app.jinja_env.globals.update(
            forumulate_comments=lambda **o: self._embed(app, "comments", o),
            forumulate_widget=lambda **o: self._embed(app, "widget", o),
            forumulate_changelog=lambda **o: self._embed(app, "changelog", o),
            forumulate_feed=lambda **o: self._embed(app, "feed", o),
            forumulate_search=lambda **o: self._embed(app, "search", o),
            forumulate_items=lambda kind, limit=10, space=None: self.client(app).items(
                kind, space=space, limit=limit
            ),
            forumulate_item=lambda kind, slug, space=None: self.client(app).item(
                kind, slug, space=space
            ),
            forumulate_markdown=lambda kind, slug, space=None: self.client(app).markdown(
                kind, slug, space=space
            ),
        )
        app.jinja_env.filters["forumulate_html"] = lambda text: Markup(
            markdown_to_html(str(text or ""))
        )

    @staticmethod
    def config(app: Any) -> Dict[str, Any]:
        return resolve(
            {k[len("FORUMULATE_"):]: v for k, v in app.config.items() if k.startswith("FORUMULATE_")}
        )

    def client(self, app: Any) -> ContentClient:
        cache = app.extensions.get("cache")
        # Flask-Caching registers {Cache: backend}; use the first if present.
        backend = next(iter(cache.values())) if isinstance(cache, dict) and cache else None
        if backend is None:
            backend = self._fallback
            setter = backend.set
        else:
            setter = lambda key, value, ttl: backend.set(key, value, timeout=ttl)  # noqa: E731
        return ContentClient(self.config(app), cache_get=backend.get, cache_set=setter)

    def _embed(self, app: Any, kind: str, options: Dict[str, Any]) -> Markup:
        # embed_html escapes every value; Markup tells Jinja not to escape again.
        return Markup(embed_html(kind, self.config(app), **options))

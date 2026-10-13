"""
Framework-free core: embed markup and the cached public-content client.

Nothing here imports the web framework, so the Django app and the Flask
extension share one copy of the rules (escaping, URL shapes, cache keys) and
only the glue around it differs.

Everything is read from Forumulate's PUBLIC read API — no token is ever needed
or sent. A private space simply answers 404, which the client turns into an
empty result so a page that lists posts still renders when Forumulate is
unreachable or a space is made private.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from typing import Any, Callable, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "BASE_URL": "https://forumulate.com",
    # Defaults to BASE_URL + "/api"; set it only for a custom API origin.
    "API_URL": None,
    "ORG": None,
    "SPACE": None,
    # "script": the widget.js / comments.js / changelog.js scripts the API serves.
    # "elements": <forumulate-*> custom elements from the @forumulate/embed package.
    "MODE": "script",
    "ELEMENTS_SRC": "https://cdn.jsdelivr.net/npm/@forumulate/embed@1",
    "CACHE_TTL": 300,
    "TIMEOUT": 5,
}

# kind -> (list path, list key, item path, reader prefix)
KINDS = {
    "blog": ("/blog", "articles", "/blog/t/{slug}", "b"),
    "forum": ("/forum", "topics", "/forum/t/{slug}", "f"),
    "changelog": ("/changelog", "releases", "/changelog/t/{slug}", "c"),
    "docs": ("", None, "/pages/{slug}", "p"),
}

EMBEDS = {
    "comments": ("comments.js", "forumulate-comments"),
    "widget": ("widget.js", "forumulate-widget"),
    "changelog": ("changelog.js", "forumulate-changelog"),
    "feed": (None, "forumulate-feed"),
    "search": (None, "forumulate-search"),
}

_ATTR_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def resolve(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    for key, value in (settings or {}).items():
        cfg[key.upper()] = value
    cfg["BASE_URL"] = str(cfg["BASE_URL"]).rstrip("/")
    cfg["API_URL"] = str(cfg["API_URL"] or cfg["BASE_URL"] + "/api").rstrip("/")
    return cfg


def _attrs(pairs: Dict[str, Any], prefix: str) -> str:
    out = []
    for name, value in pairs.items():
        if value is None or value is False:
            continue
        attr = name.replace("_", "-").lower()
        # Option names come from template authors; refuse anything that is not
        # a plain attribute name rather than escape it into something odd.
        if not _ATTR_NAME.match(attr):
            raise ValueError("forumulate: invalid option name %r" % name)
        if value is True:
            value = "true"
        out.append(' %s%s="%s"' % (prefix, attr, escape(str(value), quote=True)))
    return "".join(out)


def embed_html(kind: str, cfg: Dict[str, Any], **options: Any) -> str:
    """Markup for one embed. Every value is HTML-attribute escaped."""
    if kind not in EMBEDS:
        raise ValueError("forumulate: unknown embed %r" % kind)
    script, element = EMBEDS[kind]
    org = options.pop("org", None) or cfg["ORG"]
    space = options.pop("space", None) or cfg["SPACE"]
    if not org or not space:
        raise ValueError("forumulate: set ORG and SPACE (or pass org= and space=)")
    use_elements = options.pop("use_elements", None)
    if use_elements is None:
        use_elements = cfg["MODE"] == "elements"
    base = {"org": org, "space": space, "api": cfg["API_URL"]}
    if use_elements or script is None:
        return '<%s%s></%s><script type="module" src="%s" async></script>' % (
            element,
            _attrs({**base, **options}, ""),
            element,
            escape(cfg["ELEMENTS_SRC"], quote=True),
        )
    # The scripts mount into their parent node, so give each its own box.
    return (
        '<div class="forumulate-%s"><script src="%s"%s async></script></div>'
        % (
            kind,
            escape("%s/embed/%s" % (cfg["API_URL"], script), quote=True),
            _attrs({**base, **options}, "data-"),
        )
    )


class ContentClient:
    """Cached reads from /public/orgs/:org/spaces/:space/... ."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        cache_get: Callable[[str], Any],
        cache_set: Callable[[str, Any, int], None],
    ) -> None:
        self.cfg = cfg
        self._get = cache_get
        self._set = cache_set

    # --- transport ---------------------------------------------------------
    def _space_url(self, space: Optional[str]) -> str:
        org = self.cfg["ORG"]
        space = space or self.cfg["SPACE"]
        if not org or not space:
            raise ValueError("forumulate: set ORG and SPACE (or pass space=)")
        return "%s/public/orgs/%s/spaces/%s" % (
            self.cfg["API_URL"],
            urllib.parse.quote(str(org), safe=""),
            urllib.parse.quote(str(space), safe=""),
        )

    def _fetch(self, url: str, as_json: bool = True) -> Any:
        key = "forumulate:" + url
        hit = self._get(key)
        if hit is not None:
            return hit
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json" if as_json else "text/markdown",
                "User-Agent": "forumulate-python",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg["TIMEOUT"]) as res:
                body = res.read().decode("utf-8")
            value = json.loads(body) if as_json else body
            ttl = int(self.cfg["CACHE_TTL"])
        except (urllib.error.URLError, ValueError, OSError):
            # Cache the miss briefly so an outage does not cost every request
            # a full timeout.
            value, ttl = (False, 30)
        self._set(key, value, ttl)
        return value

    def _reader_url(self, kind: str, space: Optional[str], slug: str) -> str:
        prefix = KINDS[kind][3]
        return "%s/%s/%s/%s/%s" % (
            self.cfg["BASE_URL"],
            prefix,
            urllib.parse.quote(str(self.cfg["ORG"]), safe=""),
            urllib.parse.quote(str(space or self.cfg["SPACE"]), safe=""),
            urllib.parse.quote(str(slug), safe=""),
        )

    # --- public helpers ----------------------------------------------------
    def items(self, kind: str, space: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Blog posts, forum topics, changelog releases or docs pages, newest first."""
        if kind not in KINDS:
            raise ValueError("forumulate: unknown kind %r" % kind)
        path, key, _, _ = KINDS[kind]
        if kind == "docs":
            data = self._fetch(self._space_url(space))
            rows = []
            for col in (data or {}).get("collections", []) if data else []:
                rows.extend(p for p in col.get("pages", []) if not p.get("hideFromNav"))
        else:
            data = self._fetch("%s%s?limit=%d" % (self._space_url(space), path, int(limit)))
            rows = list((data or {}).get(key, [])) if data else []
        out = []
        for row in rows[: int(limit)] if kind == "docs" else rows:
            row = dict(row)
            row["url"] = row.get("externalUrl") or self._reader_url(kind, space, row.get("slug") or row.get("id"))
            out.append(row)
        return out

    def item(self, kind: str, slug: str, space: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """One piece as JSON (docs: the page; others: the `article`/`topic` object)."""
        data = self._fetch(self._space_url(space) + KINDS[kind][2].format(slug=urllib.parse.quote(str(slug), safe="")))
        if not data:
            return None
        piece = data.get("article") or data.get("topic") or data.get("release") or data
        piece = dict(piece)
        piece["url"] = self._reader_url(kind, space, piece.get("slug") or slug)
        return piece

    def markdown(self, kind: str, slug: str, space: Optional[str] = None) -> str:
        """The piece as Markdown, the same text the reader's "copy as Markdown" gives."""
        url = self._space_url(space) + KINDS[kind][2].format(slug=urllib.parse.quote(str(slug), safe="")) + ".md"
        body = self._fetch(url, as_json=False)
        return body if isinstance(body, str) else ""


def markdown_to_html(text: str) -> str:
    """
    Markdown -> HTML with raw HTML in the source disabled.

    Forum posts are written by visitors, so raw HTML in them must never reach
    the page. With python-markdown installed its HTML passthrough is removed;
    without it the text is escaped and split into paragraphs.
    """
    try:
        import markdown as md  # type: ignore
    except ImportError:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        return "".join("<p>%s</p>" % escape(p).replace("\n", "<br>") for p in paras)
    from markdown.treeprocessors import Treeprocessor  # type: ignore

    class _SafeLinks(Treeprocessor):
        def run(self, root):  # type: ignore[override]
            for el in root.iter():
                for attr in ("href", "src"):
                    value = el.get(attr)
                    if value is not None and not _SAFE_URL.match(value.strip()):
                        el.set(attr, "#")

    conv = md.Markdown(extensions=["fenced_code", "tables"])
    conv.preprocessors.deregister("html_block")
    conv.inlinePatterns.deregister("html")
    conv.treeprocessors.register(_SafeLinks(conv), "forumulate_safe_links", 0)
    return conv.convert(text or "")


# http(s), mailto, in-page and relative links only: no javascript:/data: URLs.
_SAFE_URL = re.compile(r"^(https?:|mailto:|#|/|\.{0,2}/|[^:/?#]+(?:[/?#]|$))", re.I)

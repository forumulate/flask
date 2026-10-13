# flask-forumulate

Forumulate for Flask: comments, the docs search / ask-AI box and the changelog
bell as Jinja globals, plus cached server-side reads of your public blog posts,
forum topics, changelog releases and docs pages for SEO-rendered pages.

## Install

```sh
pip install flask-forumulate            # add [markdown] to render Markdown bodies
```

```python
from flask import Flask
from flask_forumulate import Forumulate

app = Flask(__name__)
app.config.update(
    FORUMULATE_ORG="acme",            # organization slug or id
    FORUMULATE_SPACE="community",     # default space; every helper takes space=
    # FORUMULATE_BASE_URL="https://forumulate.com",  # or your custom domain
    # FORUMULATE_MODE="elements",     # emit <forumulate-*> custom elements
    # FORUMULATE_CACHE_TTL=300,
)
Forumulate(app)
```

Content is cached with [Flask-Caching](https://flask-caching.readthedocs.io/)
when it is set up, otherwise in a small in-process TTL cache.

## Embeds

```jinja
{{ forumulate_comments() }}
{{ forumulate_comments(space="blog-comments", theme="dark") }}
{{ forumulate_widget(mode="ask", placeholder="Ask the docs") }}
{{ forumulate_changelog(space="changelog") }}
```

Keywords become HTML-escaped `data-*` attributes (or element attributes in
`elements` mode; `use_elements=True` switches one call).

## Server-rendered content

```jinja
{% for post in forumulate_items("blog", limit=5) %}
  <a href="{{ post.url }}">{{ post.title }}</a>
{% endfor %}

{{ forumulate_markdown("blog", slug) | forumulate_html }}
```

Kinds: `blog`, `forum`, `changelog`, `docs`. Public read API only, no token;
an unreachable API or private space yields an empty list, never an error page.

## License

MIT

---

## About this repository

This repository is a public mirror, refreshed on each Forumulate release
(one commit per release). Pull requests are welcome; accepted changes are
applied upstream and arrive here with the next release.

- API reference: https://forumulate.com/reference
- Guides: https://forumulate.com/guides
- Community and support: https://forumulate.com/community
- Source: https://github.com/forumulate/flask

from __future__ import annotations

from html import escape


def render_unavailable_app_page(
    *,
    title: str = '应用已下架',
    message: str = '该应用当前不可访问。',
    app_name: str | None = None,
    home_url: str = '/community',
) -> str:
    app_line = f'<p class="app-name">{escape(app_name)}</p>' if app_name else ''
    return _page(
        title=title,
        description=message,
        body=f'''
          <main class="page-card page-card--compact">
            <div class="status-pill">Campus AI Community</div>
            <h1>{escape(title)}</h1>
            {app_line}
            <p>{escape(message)}</p>
            <a class="primary-link" href="{escape(home_url, quote=True)}">返回应用市场</a>
          </main>
        ''',
        robots='noindex,nofollow',
    )


def render_share_page(
    *,
    app_name: str,
    description: str,
    publisher: str,
    app_url: str,
    share_url: str,
    cover_url: str | None = None,
) -> str:
    image_meta = f'<meta property="og:image" content="{escape(cover_url, quote=True)}">' if cover_url else ''
    cover = (
        f'<img class="cover" src="{escape(cover_url, quote=True)}" alt="{escape(app_name, quote=True)} 封面">'
        if cover_url else
        '<div class="cover cover--placeholder">Campus AI Community</div>'
    )
    return _page(
        title=f'{app_name} - Campus AI Community',
        description=description,
        extra_head=f'''
          <link rel="canonical" href="{escape(share_url, quote=True)}">
          <meta property="og:type" content="website">
          <meta property="og:title" content="{escape(app_name, quote=True)}">
          <meta property="og:description" content="{escape(description, quote=True)}">
          <meta property="og:url" content="{escape(share_url, quote=True)}">
          {image_meta}
        ''',
        body=f'''
          <main class="page-card">
            <div class="status-pill">Campus AI Community</div>
            {cover}
            <section class="content">
              <h1>{escape(app_name)}</h1>
              <p class="description">{escape(description)}</p>
              <p class="publisher">发布者：{escape(publisher)}</p>
              <a class="primary-link" href="{escape(app_url, quote=True)}">访问应用</a>
            </section>
          </main>
        ''',
    )


def _page(
    *,
    title: str,
    description: str,
    body: str,
    extra_head: str = '',
    robots: str = 'index,follow',
) -> str:
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="{escape(robots, quote=True)}">
  <meta name="description" content="{escape(description, quote=True)}">
  <title>{escape(title)}</title>
  {extra_head}
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
      color: #17202f;
      background: #f3f7fb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px 16px;
      background:
        linear-gradient(135deg, rgba(71, 127, 255, 0.14), rgba(45, 189, 144, 0.12)),
        #f3f7fb;
    }}
    .page-card {{
      width: min(680px, 100%);
      border: 1px solid rgba(23, 32, 47, 0.1);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 18px 54px rgba(23, 32, 47, 0.12);
      overflow: hidden;
    }}
    .page-card--compact {{
      padding: 36px;
      text-align: center;
    }}
    .status-pill {{
      display: inline-flex;
      width: fit-content;
      align-items: center;
      height: 28px;
      padding: 0 10px;
      margin: 20px 20px 0;
      border: 1px solid rgba(45, 189, 144, 0.3);
      border-radius: 6px;
      color: #18745d;
      background: #eaf8f2;
      font-size: 13px;
      font-weight: 700;
    }}
    .page-card--compact .status-pill {{
      margin: 0 0 18px;
    }}
    .cover {{
      display: block;
      width: calc(100% - 40px);
      aspect-ratio: 16 / 9;
      margin: 20px;
      object-fit: cover;
      border-radius: 8px;
      background: #e9eef5;
    }}
    .cover--placeholder {{
      display: grid;
      place-items: center;
      color: #4c5f76;
      font-weight: 800;
    }}
    .content {{
      padding: 0 28px 30px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(28px, 5vw, 44px);
      line-height: 1.12;
      letter-spacing: 0;
    }}
    .description,
    main > p {{
      margin: 0 0 18px;
      color: #4d5f73;
      font-size: 16px;
      line-height: 1.7;
    }}
    .app-name {{
      margin-top: -4px;
      font-weight: 700;
      color: #2c3a4e;
    }}
    .publisher {{
      margin: 0 0 24px;
      color: #66768a;
      font-size: 14px;
    }}
    .primary-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 0 18px;
      border-radius: 6px;
      background: #276ef1;
      color: #fff;
      font-weight: 700;
      text-decoration: none;
    }}
    .primary-link:focus-visible {{
      outline: 3px solid rgba(39, 110, 241, 0.3);
      outline-offset: 3px;
    }}
    @media (max-width: 520px) {{
      body {{ padding: 18px 12px; }}
      .page-card--compact {{ padding: 28px 20px; }}
      .status-pill {{ margin: 16px 16px 0; }}
      .cover {{ width: calc(100% - 32px); margin: 16px; }}
      .content {{ padding: 0 20px 24px; }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  {body}
</body>
</html>'''

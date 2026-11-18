"""Styling for the Datasheet Analyzer — R&S / SYSTRAN-style look, light + dark.

How dark mode works (and why there are no contrast bugs any more):
  * Streamlit itself switches light/dark. Both palettes live in .streamlit/config.toml
    ([theme.light] / [theme.dark]), so Streamlit's own widgets (inputs, dropdowns,
    uploader, tables, hovers) always get matching colours. No dark CSS overrides.
  * Our own CSS uses colour tokens written as light-dark(light, dark). Streamlit sets
    `color-scheme` on .stApp, so the browser flips the tokens at the same instant
    Streamlit flips its widgets, with no rerun and no lost results.
  * theme_toggle() is a small moon/sun button for the header. It presses Streamlit's
    own Light/Dark switch (also in the ⋮ menu); the choice is remembered per browser.
  * Rule for future edits: never hard-code a colour; use var(--ds-...). Every custom
    state (normal / hover / active) sets BOTH text and background.

Needs Streamlit >= 1.67 (tested on 1.67.0).
"""
import html
import re
from contextlib import contextmanager

# ── colour tokens: (light, dark) — keep in sync with .streamlit/config.toml ──
TOKENS = {
    "bg":          ("#F7F8FA", "#121418"),
    "card":        ("#FFFFFF", "#1A1D24"),
    "sidebar":     ("#F1F2F4", "#171A20"),
    "text":        ("#2B2F38", "#E6E8EE"),
    "muted":       ("#5F6673", "#9AA0AC"),
    "border":      ("#E3E5EA", "#2C313B"),
    "border-soft": ("#EDEEF1", "#252A33"),
    "accent":      ("#3D4DA0", "#8E9CF0"),
    "accent-text": ("#FFFFFF", "#121418"),   # text ON an accent-filled surface
    "accent-soft": ("#E6EAF7", "#262C45"),   # selected / hover tint
    "hover":       ("#E9EBF0", "#252A33"),
    "hover-text":  ("#1E2129", "#F3F4F7"),
    "shadow":      ("rgba(16,24,40,.07)", "rgba(0,0,0,0)"),
    # danger (Reset button)
    "danger":       ("#DC2626", "#DC2626"),
    "danger-hover": ("#B91C1C", "#EF4444"),
    # ASI colours (text on page / card) — all >= 4.5:1 in both modes
    "asi-T": ("#15803D", "#86EFAC"),
    "asi-O": ("#B45309", "#FCD34D"),
    "asi-B": ("#C2410C", "#FDBA74"),
    "asi-U": ("#B91C1C", "#FCA5A5"),
    # callout accents (border + tag background; tag text is white in both modes)
    "c-error":   ("#DC2626", "#DC2626"),
    "c-warning": ("#B45309", "#B45309"),
    "c-info":    ("#2563EB", "#2563EB"),
    "c-success": ("#15803D", "#15803D"),
}


def _token_css():
    return "\n    ".join(f"--ds-{k}: light-dark({lt}, {dk});" for k, (lt, dk) in TOKENS.items())


CSS = """
<style>
/* ---------- colour tokens (switch live with Streamlit's theme) ---------- */
.stApp {
    __TOKENS__
}

/* ---------- chrome: hide footer and Deploy button (keep sidebar toggle + ⋮ menu) ---------- */
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}
[data-testid="stAppDeployButton"], .stDeployButton {display: none;}
[data-testid="stDecoration"] {display: none;}

/* ---------- shell: centred content with a max width (R&S style) ---------- */
.block-container, [data-testid="stMainBlockContainer"] {
    padding: 3rem 2rem 3rem 2rem; max-width: 1320px; margin: 0 auto;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top: .5rem;}

/* ---------- typography ---------- */
h1 {font-size: 1.6rem !important; font-weight: 600 !important; letter-spacing: -0.01em; padding: 0 0 0.2rem 0 !important;}
h2, h3 {font-size: 1.0rem !important; font-weight: 600 !important; margin: 0.6rem 0 0.2rem 0 !important; padding: 0 !important;}
div[data-testid="stCaptionContainer"] {color: var(--ds-muted);}
hr {margin: 0.8rem 0 !important; border-color: var(--ds-border) !important;}

/* ---------- top bar: brand left, theme button + last update right ---------- */
.ds-brand {display: flex; align-items: center; gap: .65rem; white-space: nowrap;}
.ds-logo {width: 28px; height: 28px; border-radius: 7px; display: grid; place-items: center;
    border: 1.5px solid var(--ds-accent); color: var(--ds-accent); font-weight: 700; font-size: .72rem;
    transform: rotate(45deg); flex: none;}
.ds-logo span {transform: rotate(-45deg);}
.ds-brand-name {font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: .8rem; color: var(--ds-text);}
div[class*="st-key-ds_topbar"] {border-bottom: 1px solid var(--ds-border); padding-bottom: .75rem; margin-bottom: .5rem;}
div[class*="st-key-ds_topbar"] [data-testid="stMarkdownContainer"] p {margin: 0 !important;}
/* the theme button lives in a tiny iframe: no frame, no extra gap */
div[class*="st-key-ds_topbar"] iframe {border: 0; display: block; color-scheme: normal;}
div[class*="st-key-ds_topbar"] [data-testid="stElementContainer"]:has(iframe) {width: 38px !important; flex: none;}

/* ---------- page title block ---------- */
.ds-crumb {font-size: .8rem; color: var(--ds-muted); margin: .5rem 0 .1rem;}
.ds-crumb b {color: var(--ds-accent); font-weight: 500;}
.ds-title {font-size: 1.55rem; font-weight: 600; color: var(--ds-text); margin: 0 0 .15rem; letter-spacing: -.01em;}
.ds-notice {color: var(--ds-muted); font-size: .92rem; line-height: 1.6; margin: 0 0 .9rem;}

/* ---------- cards ---------- */
div[class*="st-key-dscard"] {
    background: var(--ds-card); border: 1px solid var(--ds-border); border-radius: 10px;
    box-shadow: 0 1px 2px var(--ds-shadow), 0 1px 3px var(--ds-shadow);
    padding: 1.1rem 1.5rem 1.25rem; margin-bottom: 1rem;
}

/* ---------- split panes: two columns with a divider (top level only), stack on mobile ---------- */
div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] {gap: 0;}
div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {padding: 0 1.25rem;}
div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {padding-left: 0;}
div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {padding-right: 0;}
div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] + [data-testid="stColumn"] {
    border-left: 1px solid var(--ds-border);}

/* ---------- commodity selector: segmented control drawn as underline tabs ---------- */
div[class*="st-key-dsseg"] [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]),
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] {width: 100% !important;}
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] [role="radiogroup"] {
    display: flex; gap: 1.5rem; width: 100%; border-bottom: 1px solid var(--ds-border); flex-wrap: wrap;}
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] button {
    background: transparent !important; border: none !important; border-radius: 0 !important;
    border-bottom: 2px solid transparent !important; box-shadow: none !important;
    padding: .55rem .15rem !important; margin: 0 0 -1px 0 !important; min-height: 0;
    color: var(--ds-muted) !important;}
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] button p {color: inherit !important; font-weight: 500; font-size: .95rem;}
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] button:hover {
    color: var(--ds-hover-text) !important; background: transparent !important;}
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] button:is([aria-checked="true"], [kind$="Active"]),
div[class*="st-key-dsseg"] [data-testid="stButtonGroup"] button:is([aria-checked="true"], [kind$="Active"]):hover {
    color: var(--ds-accent) !important; border-bottom-color: var(--ds-accent) !important;}

/* ---------- native tabs → underline tabs (old baseweb + new react-aria markup) ---------- */
.stTabs, div[data-testid="stTabs"] {margin-top: 0.8rem;}
.stTabs [role="tablist"] {gap: 1.25rem; border-bottom: 1px solid var(--ds-border);}
.stTabs [role="tab"] {height: 44px; padding: 0 .2rem; background: transparent !important;
    color: var(--ds-muted) !important; font-weight: 500; font-size: .92rem;}
.stTabs [role="tab"] p {color: inherit !important;}
.stTabs [role="tab"]:hover {color: var(--ds-hover-text) !important; background: transparent !important;}
.stTabs [role="tab"][aria-selected="true"],
.stTabs [role="tab"][aria-selected="true"]:hover {color: var(--ds-accent) !important;}
.stTabs [data-baseweb="tab-highlight"], .stTabs .react-aria-SelectionIndicator {background: var(--ds-accent) !important;}
.stTabs [data-baseweb="tab-border"] {display: none;}

/* ---------- buttons: every state sets text AND background ---------- */
.stButton > button, .stDownloadButton > button {border-radius: 8px; font-weight: 600; padding: 0.3rem 1rem;
    transition: background .15s, border-color .15s, color .15s;}
.stButton > button p, .stDownloadButton > button p {color: inherit !important;}
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {
    background: var(--ds-card); color: var(--ds-text); border: 1px solid var(--ds-border);}
.stButton > button[kind="secondary"]:hover, .stDownloadButton > button[kind="secondary"]:hover,
.stButton > button[kind="secondary"]:focus-visible, .stDownloadButton > button[kind="secondary"]:focus-visible {
    background: var(--ds-accent-soft); color: var(--ds-accent); border-color: var(--ds-accent);}
.stButton > button[kind="primary"] {background: var(--ds-accent); color: var(--ds-accent-text); border: 1px solid var(--ds-accent);}
.stButton > button[kind="primary"]:hover, .stButton > button[kind="primary"]:focus-visible {
    background: var(--ds-text); color: var(--ds-bg); border-color: var(--ds-text);}
/* Reset button in red (Extract keeps the accent colour) */
.st-key-reset_btn button {background: var(--ds-danger) !important; border-color: var(--ds-danger) !important; color: #FFFFFF !important;}
.st-key-reset_btn button:hover, .st-key-reset_btn button:focus-visible {
    background: var(--ds-danger-hover) !important; border-color: var(--ds-danger-hover) !important; color: #FFFFFF !important;}
.st-key-reset_btn button p {color: #FFFFFF !important;}

/* ---------- file uploader: centred content, dashed box, accent on hover ---------- */
[data-testid="stFileUploaderDropzone"] {display: flex; align-items: center !important;
    padding: 0.9rem 1rem !important; min-height: 4.2rem;
    border: 1.5px dashed var(--ds-border); border-radius: 10px; transition: border-color .15s;}
[data-testid="stFileUploaderDropzone"] > * {margin-top: 0 !important; margin-bottom: 0 !important; align-self: center;}
[data-testid="stFileUploaderDropzone"]:hover, [data-testid="stFileUploaderDropzone"]:focus-within {border-color: var(--ds-accent);}

/* ---------- alerts ---------- */
div[data-testid="stAlert"] {border-radius: 8px; padding: 0.55rem 0.9rem; font-size: 0.9rem;}

/* ---------- tables: light, compact, scroll sideways when too wide ---------- */
div[data-testid="stTable"] {overflow-x: auto;}
div[data-testid="stTable"] table {font-size: 0.82rem; border-collapse: collapse; width: 100%;}
div[data-testid="stTable"] th {font-weight: 600; color: var(--ds-muted); background: transparent;
    border: none; border-bottom: 1px solid var(--ds-border); padding: 0.4rem 0.6rem;}
div[data-testid="stTable"] td {border: none; border-bottom: 1px solid var(--ds-border-soft);
    padding: 0.35rem 0.6rem; white-space: normal; word-break: break-word;}

/* ---------- small labels / status / pills ---------- */
div[data-testid="stMarkdownContainer"] p.field-label {font-size: 0.875rem; line-height: 1.6; font-weight: 400; margin: 0 0 0.25rem 0 !important;}
div[data-testid="stMarkdownContainer"] p.status-line {display: flex; align-items: center; height: 2.5rem; font-size: 0.875rem; color: var(--ds-muted);}
.hdr-label {font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ds-muted);}
div[data-testid="stMarkdownContainer"]:has(.hdr-label), div[data-testid="stMarkdownContainer"]:has(.update-pill) {margin-bottom: 0 !important;}
div[data-testid="stMarkdownContainer"]:has(.hdr-label) p, div[data-testid="stMarkdownContainer"]:has(.update-pill) p {margin: 0 !important;}
div[data-testid="stMarkdownContainer"] p.update-wrap {text-align: right;}
.update-pill {display: inline-block; padding: 0.25rem 0.75rem; border: 1px solid var(--ds-border);
    border-radius: 999px; font-size: 0.75rem; color: var(--ds-muted); white-space: nowrap;}

/* ---------- compact callouts (replace the big coloured Streamlit boxes) ---------- */
div[data-testid="stMarkdownContainer"] p.callout {display: flex; align-items: baseline; gap: 0.6rem;
    margin: 0 0 0.75rem 0 !important; padding: 0.4rem 0.75rem; border-radius: 6px; font-size: 0.85rem;
    line-height: 1.45; color: var(--ds-text); border: 1px solid var(--ds-border); border-left-width: 4px;}
div[data-testid="stMarkdownContainer"] p.callout-error {border-left-color: var(--ds-c-error); background: color-mix(in srgb, var(--ds-c-error) 9%, transparent);}
div[data-testid="stMarkdownContainer"] p.callout-warning {border-left-color: var(--ds-c-warning); background: color-mix(in srgb, var(--ds-c-warning) 10%, transparent);}
div[data-testid="stMarkdownContainer"] p.callout-info {border-left-color: var(--ds-c-info); background: color-mix(in srgb, var(--ds-c-info) 9%, transparent);}
div[data-testid="stMarkdownContainer"] p.callout-success {border-left-color: var(--ds-c-success); background: color-mix(in srgb, var(--ds-c-success) 10%, transparent);}
.callout-tag {flex: none; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
    padding: 0.05rem 0.5rem; border-radius: 999px; color: #FFFFFF; white-space: nowrap;}
.callout-error .callout-tag {background: var(--ds-c-error);}
.callout-warning .callout-tag {background: var(--ds-c-warning);}
.callout-info .callout-tag {background: var(--ds-c-info);}
.callout-success .callout-tag {background: var(--ds-c-success);}

/* ---------- result summary ---------- */
.kv span {display: block; font-size: 0.7rem; color: var(--ds-muted); text-transform: uppercase; letter-spacing: 0.05em;}
.kv b {font-size: 1.05rem; font-weight: 600; display: block; overflow-wrap: anywhere; color: var(--ds-text);}
.kv b.asi-T {color: var(--ds-asi-T);} .kv b.asi-O {color: var(--ds-asi-O);}
.kv b.asi-B {color: var(--ds-asi-B);} .kv b.asi-U {color: var(--ds-asi-U);}
.kv-grid {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 0.1rem;}
.kv-grid .kv {padding: 0 1rem; border-left: 1px solid var(--ds-border);}
.kv-grid .kv:first-child {padding-left: 0; border-left: none;}

/* ---------- small screens ---------- */
@media (max-width: 900px) {
    div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {padding: 0;}
    div[class*="st-key-dssplit"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] + [data-testid="stColumn"] {
        border-left: none; border-top: 1px solid var(--ds-border); padding-top: .9rem; margin-top: .4rem;}
}
@media (max-width: 640px) {
    .block-container, [data-testid="stMainBlockContainer"] {padding: 3.25rem 0.75rem 2rem 0.75rem;}
    div[class*="st-key-dscard"] {padding: .9rem 1rem 1rem;}
    .kv-grid {grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 0.8rem;}
    .kv-grid .kv:nth-child(3) {padding-left: 0; border-left: none;}
    .update-pill {font-size: .7rem; padding: .2rem .55rem;}
}
</style>
""".replace("__TOKENS__", _token_css())

DARK_CSS = ""   # no longer used: Streamlit's own dark theme (config.toml) + light-dark() tokens

# letter, meaning, colour (hex kept for any other module that reads it), CSS class used by render_summary
ASI_TEXT = {0: ("T", "Recommended", "#16a34a"), 1: ("O", "Approved", "#d97706"), 1.5: ("B", "Conditional use", "#ea580c"),
            2: ("U/V", "Avoid for new designs", "#dc2626")}
_ASI_CLASS = {0: "asi-T", 1: "asi-O", 1.5: "asi-B", 2: "asi-U"}


def _inline(text):
    """Escape HTML and turn **bold** into <b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(str(text)))


def callout(kind, text, tag=None):
    """Compact, theme-friendly replacement for st.success / st.warning / st.error / st.info.
    kind: 'error' | 'warning' | 'info' | 'success'; tag: optional small pill in front of the text."""
    import streamlit as st
    pill = f'<span class="callout-tag">{html.escape(str(tag))}</span>' if tag else ""
    st.markdown(f'<p class="callout callout-{kind}">{pill}<span>{_inline(text)}</span></p>', unsafe_allow_html=True)


def _md_cell(v):
    s = str(v).replace("*", "\\*")
    return "\\" + s if s[:1] in ("-", "+", "#", ">") else s   # '-' alone would become a bullet


def md_safe(table):
    """st.table renders Markdown: escape it so DMS codes like *RADIAL*, EIA0402* or '-' show as written."""
    return {k: [_md_cell(v) for v in vals] for k, vals in table.items()}


def apply_style(dark=None):
    """Inject the CSS. `dark` is ignored (kept so old calls still work): light/dark now
    comes from Streamlit's theme switch — see theme_toggle()."""
    import streamlit as st
    st.markdown(CSS, unsafe_allow_html=True)


# ── header pieces ────────────────────────────────────────────────────────────
def brand(name="Component Engineering", logo="DA"):
    """Small logo + uppercase brand name for the top bar."""
    import streamlit as st
    st.markdown(f'<div class="ds-brand"><div class="ds-logo"><span>{html.escape(logo)}</span></div>'
                f'<span class="ds-brand-name">{html.escape(name)}</span></div>',
                unsafe_allow_html=True, width="content")


def page_title(title, crumbs=None, notice=None):
    """Breadcrumb + page title + muted one-line description."""
    import streamlit as st
    out = ""
    if crumbs:
        parts = [html.escape(c) for c in crumbs]
        out += '<div class="ds-crumb">⌂ / ' + " / ".join(parts[:-1] + [f"<b>{parts[-1]}</b>"]) + "</div>"
    out += f'<div class="ds-title">{html.escape(title)}</div>'
    if notice:
        out += f'<div class="ds-notice">{_inline(notice)}</div>'
    st.markdown(out, unsafe_allow_html=True)


_TOGGLE_HTML = """
<style>
html, body {margin:0; padding:0; background:transparent; overflow:hidden;}
button {width:36px; height:36px; margin:1px; border-radius:50%; padding:0; cursor:pointer;
  display:grid; place-items:center; background:transparent; color:var(--f); border:1px solid var(--b);
  transition:background .15s, color .15s, border-color .15s;}
button:hover, button:focus-visible {background:var(--h); color:var(--a); border-color:var(--a); outline:none;}
svg {width:17px; height:17px;}
</style>
<button id="t" type="button" aria-label="Switch light / dark mode"></button>
<script>
(function () {
  const P = window.parent.document, btn = document.getElementById('t');
  const COL = {light: {f:'#2B2F38', b:'#E3E5EA', h:'#E6EAF7', a:'#3D4DA0'},
               dark:  {f:'#E6E8EE', b:'#2C313B', h:'#262C45', a:'#8E9CF0'}};
  const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  const scheme = () => { const a = P.querySelector('.stApp');
    return a && getComputedStyle(a).colorScheme.indexOf('dark') > -1 ? 'dark' : 'light'; };
  function paint() {
    const s = scheme(), c = COL[s];
    for (const k in c) document.documentElement.style.setProperty('--' + k, c[k]);
    btn.innerHTML = s === 'dark' ? SUN : MOON;
    btn.title = s === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function waitFor(sel) { for (let i = 0; i < 40; i++) { const e = P.querySelector(sel); if (e) return e; await sleep(25); } return null; }
  btn.addEventListener('click', async () => {
    const target = scheme() === 'dark' ? 'Light' : 'Dark';
    const menu = P.querySelector('[data-testid="stMainMenuButton"]');
    if (!menu) { btn.title = 'Use the ⋮ menu (top right) to switch theme'; return; }
    const hide = P.createElement('style');   // keep the ⋮ menu invisible while we press it
    hide.textContent = '[data-testid="stMainMenuPopover"]{opacity:0!important;pointer-events:none!important}';
    P.head.appendChild(hide);
    try {
      menu.click();
      const item = await waitFor('[data-testid="stMainMenuItem-theme-' + target + '"]');
      if (item) item.click();
      await sleep(30);
      if (P.querySelector('[data-testid="stMainMenuPopover"]')) {
        P.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
        await sleep(30);
        if (P.querySelector('[data-testid="stMainMenuPopover"]')) menu.click();
      }
    } finally { setTimeout(() => hide.remove(), 250); }
  });
  paint();
  const app = P.querySelector('.stApp');
  if (app) new MutationObserver(paint).observe(app, {attributes: true, attributeFilter: ['class', 'style']});
})();
</script>
"""


def theme_toggle():
    """Moon/sun button that switches Streamlit's own Light/Dark theme (same as ⋮ menu)."""
    import streamlit.components.v1 as components
    components.html(_TOGGLE_HTML, height=38, width=38)


# ── scoped containers: the CSS only touches what is inside these ─────────────
@contextmanager
def card(name):
    import streamlit as st
    with st.container(key=f"dscard_{name}") as c:
        yield c


@contextmanager
def split(name):
    import streamlit as st
    with st.container(key=f"dssplit_{name}") as c:
        yield c


@contextmanager
def segmented(name):
    import streamlit as st
    with st.container(key=f"dsseg_{name}") as c:
        yield c


# ── result summary ───────────────────────────────────────────────────────────
def _kv(label, value, css_class=None):
    cls = f' class="{css_class}"' if css_class else ""
    return f'<div class="kv"><span>{html.escape(label)}</span><b{cls}>{html.escape(str(value))}</b></div>'


def render_summary(designation_text, manufacturer_text, cg_text, asi_result, mpn="", rule_applies=True, na_text="No rule loaded"):
    """Compact result header: copyable designation + four evenly spaced fields."""
    import streamlit as st
    st.markdown('<p class="field-label">Designation</p>', unsafe_allow_html=True)
    st.code(str(designation_text), language=None)  # has a copy button
    css_class = None
    if rule_applies:
        letter, meaning, _ = ASI_TEXT.get(asi_result["overall"], ("-", "Undetermined", None))
        css_class = _ASI_CLASS.get(asi_result["overall"])
    else:
        letter, meaning = "N/A", na_text
    cells = [
        _kv("ASI (rule)", f"{letter} · {meaning}", css_class),
        _kv("Commodity group", cg_text),
        _kv("Manufacturer", manufacturer_text),
        _kv("MPN", str(mpn).strip().upper() or "-"),
    ]
    st.markdown('<div class="kv-grid">' + "".join(cells) + "</div>", unsafe_allow_html=True)

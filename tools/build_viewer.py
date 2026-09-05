#!/usr/bin/env python3
"""Build the copy-and-paste viewer for cc_tools.py.

The plug-in is installed by pasting its whole source into the Vectorworks
Plug-in Manager, so the source itself is the deliverable. This renders it as a
page with one job: copy all of it, correctly, including the final call.

Run after any change to cc_tools.py, then publish the output as an Artifact.
"""
import html
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'cc_tools.py')
OUT = os.environ.get('CC_VIEWER_OUT', '/tmp/cc_tools_viewer.html')


def git(*args):
    try:
        return subprocess.check_output(('git',) + args, cwd=ROOT,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ''


def main():
    with open(SOURCE, encoding='utf-8') as f:
        source = f.read()

    lines = source.count('\n') + 1
    kb = len(source.encode('utf-8')) / 1024.0
    commit = git('rev-parse', '--short', 'HEAD')
    subject = git('log', '-1', '--pretty=%s')
    when = git('log', '-1', '--date=format:%d %b %Y', '--pretty=%ad')
    tools = source.count('\ndef tool_')

    # Title-block fields, in the shape a drawing sheet uses: short label above
    # a value, hairline rules between.
    fields = [
        ('File', 'cc_tools.py'),
        ('Lines', '{:,}'.format(lines)),
        ('Size', '{:.0f} KB'.format(kb)),
        ('Tools', str(tools)),
        ('Revision', commit or '—'),
        ('Date', when or '—'),
    ]
    block = '\n'.join(
        '      <div class="field"><span class="k">{}</span>'
        '<span class="v">{}</span></div>'.format(html.escape(k), html.escape(v))
        for k, v in fields)

    page = TEMPLATE.replace('%%TITLEBLOCK%%', block)
    page = page.replace('%%SUBJECT%%', html.escape(subject or 'Working copy'))
    page = page.replace('%%SOURCE%%', html.escape(source))
    page = page.replace('%%LINES%%', '{:,}'.format(lines))

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(page)
    print('wrote {} ({:.0f} KB, {:,} lines of source)'.format(OUT, kb, lines))


TEMPLATE = r'''<title>CC Tools Source</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root {
    --paper:      #f6f7f5;
    --sheet:      #ffffff;
    --ink:        #172029;
    --ink-soft:   #5c6873;
    --rule:       #d5dad6;
    --rule-soft:  #e7eae7;
    --accent:     #1b6fa8;
    --accent-ink: #ffffff;
    --ok:         #2f7d4f;
    --code-bg:    #fbfcfa;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper:     #12171c;
      --sheet:     #171d23;
      --ink:       #e4e9ec;
      --ink-soft:  #94a2ad;
      --rule:      #2c353d;
      --rule-soft: #222a31;
      --accent:    #55a8dd;
      --accent-ink:#0d1216;
      --ok:        #63c58c;
      --code-bg:   #131920;
    }
  }
  :root[data-theme="dark"] {
    --paper:     #12171c;
    --sheet:     #171d23;
    --ink:       #e4e9ec;
    --ink-soft:  #94a2ad;
    --rule:      #2c353d;
    --rule-soft: #222a31;
    --accent:    #55a8dd;
    --accent-ink:#0d1216;
    --ok:        #63c58c;
    --code-bg:   #131920;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    line-height: 1.5;
  }
  .sheet {
    max-width: 1080px;
    margin: 0 auto;
    padding: 28px 20px 64px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  header { display: flex; flex-direction: column; gap: 6px; }
  h1 {
    margin: 0;
    font-size: 25px;
    font-weight: 600;
    letter-spacing: -0.015em;
    text-wrap: balance;
  }
  .sub { margin: 0; color: var(--ink-soft); font-size: 14px; }

  /* Title block: the label/value strip a drawing sheet carries. */
  .titleblock {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
    border: 1px solid var(--rule);
    background: var(--sheet);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 9px 12px;
    border-right: 1px solid var(--rule-soft);
  }
  .field:last-child { border-right: 0; }
  .k {
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--ink-soft);
  }
  .v {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }

  .actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  button {
    font: 500 14px/1 'IBM Plex Sans', sans-serif;
    padding: 10px 18px;
    border: 1px solid var(--accent);
    border-radius: 3px;
    background: var(--accent);
    color: var(--accent-ink);
    cursor: pointer;
  }
  button:hover { filter: brightness(1.08); }
  button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  button.done { background: var(--ok); border-color: var(--ok); }
  .hint { color: var(--ink-soft); font-size: 13px; }

  .warn {
    border-left: 3px solid var(--accent);
    padding: 9px 0 9px 13px;
    font-size: 14px;
  }
  .warn code {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 13px;
  }

  .codewrap {
    border: 1px solid var(--rule);
    background: var(--code-bg);
    max-height: 62vh;
    overflow: auto;
  }
  pre {
    margin: 0;
    padding: 16px 18px;
    font-family: 'IBM Plex Mono', ui-monospace, 'SFMono-Regular', monospace;
    font-size: 12.5px;
    line-height: 1.65;
    tab-size: 4;
    white-space: pre;
  }
  ol { margin: 0; padding-left: 20px; font-size: 14px; }
  ol li { margin-bottom: 5px; }
  ol li::marker { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
  h2 {
    margin: 0;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--ink-soft);
    font-weight: 600;
  }
  section { display: flex; flex-direction: column; gap: 9px; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>

<div class="sheet">
  <header>
    <h1>CC Tools</h1>
    <p class="sub">ConnectCAD plug-in for Vectorworks 2026. Copy the whole
      script, paste it into one Plug-in Manager command.</p>
  </header>

  <div class="titleblock">
%%TITLEBLOCK%%
  </div>

  <div class="actions">
    <button id="copy" type="button">Copy the whole script</button>
    <span class="hint" id="hint">%%LINES%% lines, including the final call</span>
  </div>

  <p class="warn">Paste <strong>everything</strong>, down to the last line
    <code>run_cc_tools()</code>. That call is what runs the command &mdash;
    without it the script defines its functions and silently does nothing.</p>

  <section>
    <h2>Latest change</h2>
    <p class="sub">%%SUBJECT%%</p>
  </section>

  <section>
    <h2>Install</h2>
    <ol>
      <li>Vectorworks &rsaquo; Tools &rsaquo; Plug-ins &rsaquo; Plug-in Manager</li>
      <li>New &rsaquo; Command, name it <strong>CC Tools</strong>, language Python</li>
      <li>Edit Script, select all, paste, save</li>
      <li>Tools &rsaquo; Workspaces &rsaquo; Edit Current Workspace &rsaquo; Menus,
          then drag <strong>CC Tools</strong> into a menu</li>
    </ol>
  </section>

  <section>
    <h2>Source</h2>
    <div class="codewrap"><pre id="src">%%SOURCE%%</pre></div>
  </section>
</div>

<script>
  (function () {
    var button = document.getElementById('copy');
    var hint = document.getElementById('hint');
    var source = document.getElementById('src');

    function fallbackCopy(text) {
      var box = document.createElement('textarea');
      box.value = text;
      box.setAttribute('readonly', '');
      box.style.position = 'fixed';
      box.style.top = '-1000px';
      document.body.appendChild(box);
      box.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(box);
      return ok;
    }

    function done(ok) {
      button.textContent = ok ? 'Copied' : 'Select the code and copy';
      button.classList.toggle('done', ok);
      hint.textContent = ok
        ? 'Now paste it over everything in the CC Tools command'
        : 'Clipboard access was blocked, so copy it by hand';
      setTimeout(function () {
        button.textContent = 'Copy the whole script';
        button.classList.remove('done');
        hint.textContent = '%%LINES%% lines, including the final call';
      }, 4000);
    }

    button.addEventListener('click', function () {
      var text = source.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); },
                                                 function () { done(fallbackCopy(text)); });
      } else {
        done(fallbackCopy(text));
      }
    });
  })();
</script>
'''

if __name__ == '__main__':
    main()

# Chasing the Perfect Poem: Medium package

Medium does not import Markdown files, so this folder gives you three ways in.

| File | Use it for |
|---|---|
| `post.html` | **Easiest.** Open it in a browser, copy everything below the grey box, paste into a new Medium story. Headings, bold, italics, quotes and lists come through. |
| `post.md` | The same post as Markdown, for your records, for other platforms (Substack, Ghost, dev.to, GitHub) or for a Markdown-to-Medium tool. |
| `images/` | Every figure as a 2× PNG on white, numbered in the order it appears. |

## Posting steps

1. Open `post.html` in Chrome or Safari.
2. On Medium, click **Write** to start a new story.
3. In `post.html`, click just above the title, Shift-click after the last line, and copy.
4. Paste into the Medium editor.
5. Check each image. Medium can't fetch pictures from your computer, so any image that shows up broken or missing needs to be dragged in from `images/`. The file names match the order of the post, and each caption is the italic line under it in `post.md`.
6. Medium formatting touches:
   - Make the first line the title and the second line the subtitle (Medium usually does this automatically).
   - Select each of the four bold one-line quotes ("Weather and climate…", "The noise floor…", "The critic stops…" and "Offered the exit…") and click the quote button twice to turn it into a **pull quote**.
   - Use `00-cover.png` as the story's preview image (Story settings → Preview).
7. Suggested tags (Medium allows 5): `Artificial Intelligence`, `Poetry`, `Physics`, `Large Language Models`, `Chaos Theory`.

## Rebuilding

Everything is generated from the experiment logs, so numbers stay in sync:

```bash
cd ~/poem-loop
.venv/bin/python blog_data.py /tmp/blog.json /tmp/blog.html
.venv/bin/python medium/export_figures.py /tmp/blog.html
.venv/bin/python medium/build_medium.py /tmp/blog.json
```

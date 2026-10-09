import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

/**
 * Single shared markdown renderer: GFM-ish defaults, highlight.js for fenced
 * code, no raw HTML passthrough (assistant output is untrusted).
 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code: string, language: string): string {
    if (language && hljs.getLanguage(language)) {
      try {
        const html = hljs.highlight(code, { language, ignoreIllegals: true }).value
        return `<pre class="code-block"><code class="hljs language-${language}">${html}</code></pre>`
      } catch {
        /* fall through to auto-detect */
      }
    }
    const html = hljs.highlightAuto(code).value
    return `<pre class="code-block"><code class="hljs">${html}</code></pre>`
  },
})

export function renderMarkdown(text: string): string {
  return md.render(text)
}

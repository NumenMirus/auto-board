import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './render';

describe('renderMarkdown', () => {
  it('renders headings, paragraphs, and emphasis', () => {
    const html = renderMarkdown('# Title\n\nHello **world** and *now*.');
    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>world</strong>');
    expect(html).toContain('<em>now</em>');
  });

  it('escapes raw HTML', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('renders inline code without interpreting contents', () => {
    const html = renderMarkdown('Use `npm run build` to build.');
    expect(html).toContain('<code>npm run build</code>');
  });

  it('renders fenced code blocks', () => {
    const html = renderMarkdown('```json\n{"a": 1}\n```');
    expect(html).toContain('<pre class="lang-json"><code>');
    expect(html).toContain('{&quot;a&quot;: 1}');
  });

  it('renders GFM tables', () => {
    const html = renderMarkdown('| A | B |\n| - | - |\n| 1 | 2 |');
    expect(html).toContain('<table>');
    expect(html).toContain('<th>A</th>');
    expect(html).toContain('<td>1</td>');
  });

  it('renders unordered and ordered lists', () => {
    const ul = renderMarkdown('- one\n- two');
    expect(ul).toContain('<ul>');
    expect(ul).toContain('<li>one</li>');

    const ol = renderMarkdown('1. one\n2. two');
    expect(ol).toContain('<ol>');
    expect(ol).toContain('<li>one</li>');
  });

  it('renders horizontal rules and blockquotes', () => {
    const html = renderMarkdown('---\n\n> quoted');
    expect(html).toContain('<hr />');
    expect(html).toContain('<blockquote>');
    expect(html).toContain('quoted');
  });
});
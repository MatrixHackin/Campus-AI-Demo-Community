import { useMemo } from 'react'

export function slugify(text) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, '-')
    .replace(/[^\w\u4e00-\u9fa5-]/g, '')
}

function plainText(text) {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim()
}

function createSlugger() {
  const counts = new Map()

  return (text) => {
    const base = slugify(plainText(text)) || 'section'
    const count = counts.get(base) || 0
    counts.set(base, count + 1)
    return count === 0 ? base : `${base}-${count + 1}`
  }
}

function InlineMarkdown({ text }) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g
  const parts = text.split(pattern).filter(Boolean)

  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={index}>{part.slice(1, -1)}</code>
    }

    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }

    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (linkMatch) {
      return (
        <a key={index} href={linkMatch[2]} target={linkMatch[2].startsWith('#') ? undefined : '_blank'} rel={linkMatch[2].startsWith('#') ? undefined : 'noreferrer'}>
          {linkMatch[1]}
        </a>
      )
    }

    return part
  })
}

function flushParagraph(blocks, paragraph) {
  if (paragraph.length === 0) return
  blocks.push({ type: 'paragraph', text: paragraph.join(' ') })
  paragraph.length = 0
}

function parseTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableDivider(line) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim())
}

function parseMarkdown(markdown) {
  const blocks = []
  const paragraph = []
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const makeSlug = createSlugger()
  let codeFence = null
  let list = null
  let table = null

  const flushList = () => {
    if (list?.items.length) blocks.push(list)
    list = null
  }

  const flushTable = () => {
    if (table?.headers.length && table.rows.length) blocks.push(table)
    table = null
  }

  lines.forEach((line, lineIndex) => {
    if (line.startsWith('```')) {
      flushTable()
      if (codeFence) {
        blocks.push({ type: 'code', language: codeFence.language, text: codeFence.lines.join('\n') })
        codeFence = null
      } else {
        flushParagraph(blocks, paragraph)
        flushList()
        codeFence = { language: line.slice(3).trim(), lines: [] }
      }
      return
    }

    if (codeFence) {
      codeFence.lines.push(line)
      return
    }

    if (!line.trim()) {
      flushParagraph(blocks, paragraph)
      flushList()
      flushTable()
      return
    }

    if (/^---+$/.test(line.trim())) {
      flushParagraph(blocks, paragraph)
      flushList()
      flushTable()
      blocks.push({ type: 'divider' })
      return
    }

    if (line.includes('|') && lines[lineIndex + 1] && isTableDivider(lines[lineIndex + 1])) {
      flushParagraph(blocks, paragraph)
      flushList()
      table = { type: 'table', headers: parseTableRow(line), rows: [] }
      return
    }

    if (table) {
      if (isTableDivider(line)) return
      if (line.includes('|')) {
        table.rows.push(parseTableRow(line))
        return
      }
      flushTable()
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)
    if (headingMatch) {
      flushParagraph(blocks, paragraph)
      flushList()
      flushTable()
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        text: headingMatch[2],
        id: makeSlug(headingMatch[2])
      })
      return
    }

    const quoteMatch = line.match(/^>\s?(.+)$/)
    if (quoteMatch) {
      flushParagraph(blocks, paragraph)
      flushList()
      flushTable()
      blocks.push({ type: 'quote', text: quoteMatch[1] })
      return
    }

    const listMatch = line.match(/^(\d+\.|-)\s+(.+)$/)
    if (listMatch) {
      flushParagraph(blocks, paragraph)
      flushTable()
      const ordered = listMatch[1] !== '-'
      if (!list || list.ordered !== ordered) {
        flushList()
        list = { type: 'list', ordered, items: [] }
      }
      list.items.push(listMatch[2])
      return
    }

    flushList()
    flushTable()
    paragraph.push(line.trim())
  })

  flushParagraph(blocks, paragraph)
  flushList()
  flushTable()

  if (codeFence) {
    blocks.push({ type: 'code', language: codeFence.language, text: codeFence.lines.join('\n') })
  }

  return blocks
}

export function extractMarkdownHeadings(markdown) {
  const makeSlug = createSlugger()
  const headings = []
  let inCodeFence = false

  markdown.replace(/\r\n/g, '\n').split('\n').forEach((line) => {
    if (line.startsWith('```')) {
      inCodeFence = !inCodeFence
      return
    }

    if (inCodeFence) return

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)
    if (!headingMatch) return

    const text = plainText(headingMatch[2])
    headings.push({
      id: makeSlug(headingMatch[2]),
      level: headingMatch[1].length,
      text
    })
  })

  return headings
}

export default function MarkdownRenderer({ markdown }) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown])

  return (
    <article className="markdown-body">
      {blocks.map((block, index) => {
        if (block.type === 'heading') {
          const HeadingTag = `h${block.level}`
          return (
            <HeadingTag id={block.id} key={index}>
              <InlineMarkdown text={block.text} />
            </HeadingTag>
          )
        }

        if (block.type === 'paragraph') {
          return (
            <p key={index}>
              <InlineMarkdown text={block.text} />
            </p>
          )
        }

        if (block.type === 'quote') {
          return (
            <blockquote key={index}>
              <InlineMarkdown text={block.text} />
            </blockquote>
          )
        }

        if (block.type === 'code') {
          return (
            <pre key={index}>
              <code>{block.text}</code>
            </pre>
          )
        }

        if (block.type === 'list') {
          const ListTag = block.ordered ? 'ol' : 'ul'
          return (
            <ListTag key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <InlineMarkdown text={item} />
                </li>
              ))}
            </ListTag>
          )
        }

        if (block.type === 'table') {
          return (
            <div className="markdown-table-wrap" key={index}>
              <table>
                <thead>
                  <tr>
                    {block.headers.map((header, headerIndex) => (
                      <th key={headerIndex}>
                        <InlineMarkdown text={header} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {block.headers.map((_, cellIndex) => (
                        <td key={cellIndex}>
                          <InlineMarkdown text={row[cellIndex] || ''} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }

        if (block.type === 'divider') {
          return <hr key={index} />
        }

        return null
      })}
    </article>
  )
}

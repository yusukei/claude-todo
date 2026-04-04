import { useEffect, useRef, useMemo } from 'react'
import DOMPurify from 'dompurify'
import { api } from '../../api/client'
import MarkdownRenderer from '../common/MarkdownRenderer'
import AuthImage from '../common/AuthImage'

interface Props {
  content: string
}

/**
 * Renders clipped bookmark content.
 * Auto-detects HTML vs Markdown:
 *   - If content starts with '<' or contains common HTML tags → render as sanitized HTML
 *   - Otherwise → render as Markdown
 *
 * For HTML content, images pointing to /api/v1/bookmark-assets/ are fetched
 * with JWT authentication and replaced with blob URLs.
 */
export default function ClipContentRenderer({ content }: Props) {
  const isHtml = useMemo(() => {
    const trimmed = content.trimStart()
    return trimmed.startsWith('<') || /<(?:div|p|h[1-6]|article|section|img|ul|ol|table|blockquote)\b/i.test(trimmed)
  }, [content])

  if (!isHtml) {
    return (
      <MarkdownRenderer
        componentOverrides={{
          img: ({ src, alt }) => (
            <AuthImage src={src} alt={alt ?? ''} className="max-w-full rounded my-2" />
          ),
        }}
      >
        {content}
      </MarkdownRenderer>
    )
  }

  return <HtmlRenderer html={content} />
}


function HtmlRenderer({ html }: { html: string }) {
  const containerRef = useRef<HTMLDivElement>(null)

  const sanitized = useMemo(() => {
    return DOMPurify.sanitize(html, {
      ADD_TAGS: ['iframe'],
      ADD_ATTR: ['target', 'allowfullscreen', 'frameborder', 'loading'],
      ALLOW_DATA_ATTR: false,
      FORBID_TAGS: ['script', 'style', 'form', 'input', 'textarea', 'select'],
    })
  }, [html])

  useEffect(() => {
    if (!containerRef.current) return

    // Find all internal images and replace with authenticated fetches
    const imgs = containerRef.current.querySelectorAll('img')
    const controllers: AbortController[] = []

    imgs.forEach((img) => {
      const src = img.getAttribute('src')
      if (!src || !src.startsWith('/api/')) return

      const controller = new AbortController()
      controllers.push(controller)

      // Add loading placeholder style
      img.style.minHeight = '100px'
      img.style.background = 'var(--tw-gradient-from, #e5e7eb)'
      img.style.borderRadius = '0.375rem'

      api
        .get(src.replace('/api/v1', ''), {
          responseType: 'blob',
          signal: controller.signal,
        })
        .then((res) => {
          const blobUrl = URL.createObjectURL(res.data)
          img.src = blobUrl
          img.style.minHeight = ''
          img.style.background = ''
          // Cleanup on unmount handled by effect return
          img.dataset.blobUrl = blobUrl
        })
        .catch(() => {
          img.alt = img.alt || '[画像を読み込めません]'
          img.style.minHeight = '2rem'
          img.style.background = ''
        })
    })

    // Make all links open in new tab
    containerRef.current.querySelectorAll('a').forEach((a) => {
      if (a.href && !a.href.startsWith('#')) {
        a.target = '_blank'
        a.rel = 'noopener noreferrer'
      }
    })

    return () => {
      controllers.forEach((c) => c.abort())
      // Revoke blob URLs
      if (containerRef.current) {
        containerRef.current.querySelectorAll('img[data-blob-url]').forEach((img) => {
          const blobUrl = (img as HTMLImageElement).dataset.blobUrl
          if (blobUrl) URL.revokeObjectURL(blobUrl)
        })
      }
    }
  }, [sanitized])

  return (
    <div
      ref={containerRef}
      className="clip-html-content prose prose-sm prose-gray dark:prose-invert max-w-none"
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  )
}

import { useEffect, useState } from 'react'
import { api } from '../../api/client'

interface Props extends React.ImgHTMLAttributes<HTMLImageElement> {
  src?: string
  onLoadError?: () => void
}

const _blobCache = new Map<string, string>()

export default function AuthImage({ src, alt, onLoadError, ...rest }: Props) {
  const isInternal = src && src.startsWith('/api/')

  const [blobUrl, setBlobUrl] = useState<string | null>(() =>
    isInternal && src ? (_blobCache.get(src) ?? null) : null,
  )
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!src || !isInternal) return

    const cached = _blobCache.get(src)
    if (cached) {
      setBlobUrl(cached)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    let retryTimer: ReturnType<typeof setTimeout>

    const fetchImage = (attempt: number) => {
      api
        .get(src.replace('/api/v1', ''), {
          responseType: 'blob',
          signal: controller.signal,
        })
        .then((res) => {
          if (!cancelled) {
            const url = URL.createObjectURL(res.data)
            _blobCache.set(src, url)
            setBlobUrl(url)
          }
        })
        .catch(() => {
          if (cancelled) return
          if (attempt < 2) {
            retryTimer = setTimeout(() => fetchImage(attempt + 1), 1000 * (attempt + 1))
          } else {
            setError(true)
            onLoadError?.()
          }
        })
    }

    fetchImage(0)

    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(retryTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src])

  if (!src) return null

  if (!isInternal) return <img src={src} alt={alt} {...rest} />

  if (error) return <span className="inline-block w-full max-w-xs h-24 bg-gray-100 dark:bg-gray-800 rounded flex items-center justify-center text-xs text-gray-400">[画像を読み込めません]</span>
  if (!blobUrl) return <span className="inline-block w-full max-w-xs h-32 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />

  return <img src={blobUrl} alt={alt} {...rest} />
}

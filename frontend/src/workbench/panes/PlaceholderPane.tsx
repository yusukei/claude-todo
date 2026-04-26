import { Hammer } from 'lucide-react'

interface Props {
  name: string
  pr: string
}

/** Render a "Coming soon" message for pane types whose component
 *  hasn't shipped yet. Used by the registry so the layout system can
 *  be exercised end-to-end before every pane type is implemented. */
export default function PlaceholderPane({ name, pr }: Props) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center">
      <Hammer className="w-8 h-8 text-gray-300" />
      <div>
        <p className="text-sm font-medium text-gray-50 font-serif">
          {name} pane
        </p>
        <p className="text-xs text-gray-200 mt-1 font-mono">
          Implementation lands in {pr}.
        </p>
      </div>
    </div>
  )
}

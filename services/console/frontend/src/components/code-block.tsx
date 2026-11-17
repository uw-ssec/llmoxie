import { useState } from 'react'
import { Button } from '@/components/ui/button'

/** The design system's code block: for a key, an address, anything to be copied exactly. */
export function CodeBlock({ value, copy = false, label }: { value: string; copy?: boolean; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-center gap-4 rounded-md bg-terminal px-4 py-3">
      <code aria-label={label} className="flex-1 font-normal break-all text-terminal-foreground">
        {value}
      </code>
      {copy && (
        <Button
          type="button"
          variant="inverse"
          size="sm"
          onClick={async () => {
            await navigator.clipboard.writeText(value)
            setCopied(true)
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      )}
    </div>
  )
}

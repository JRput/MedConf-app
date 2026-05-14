// src/components/ui/SaveButton.tsx
'use client'

import { useSaved } from '@/hooks/useSaved'
import { Heart } from 'lucide-react'

interface SaveButtonProps { 
  conferenceId: number
  size?: 'sm' | 'md'
}

export function SaveButton({ conferenceId, size = 'md' }: SaveButtonProps) {
  const { isSaved, toggleSave } = useSaved()
  const saved = isSaved(conferenceId)

  const sizeClasses = size === 'sm' 
    ? 'text-xs px-2.5 py-1.5 gap-1'
    : 'text-sm px-3 py-2 gap-1.5'

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'

  return (
    <button 
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggleSave(conferenceId)
      }}
      className={`flex items-center rounded-lg font-medium transition-all duration-200 ${sizeClasses} ${
        saved 
          ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500/30' 
          : 'bg-slate-800/50 text-slate-300 border border-slate-700 hover:border-cyan-500/50 hover:text-cyan-400'
      }`}
    >
      <Heart className={`${iconSize} ${saved ? 'fill-current' : ''}`} />
      {saved ? 'Saved' : 'Save'}
    </button>
  )
}



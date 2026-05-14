// src/components/conferences/SearchBar.tsx
'use client'

import { useState, useEffect } from 'react'
import { Search, X } from 'lucide-react'

interface SearchBarProps { 
  value: string
  onChange: (v: string) => void 
}

export function SearchBar({ value, onChange }: SearchBarProps) {
  const [local, setLocal] = useState(value)

  // Debounce: only trigger onChange 400ms after the user stops typing
  useEffect(() => {
    const timer = setTimeout(() => onChange(local), 400)
    return () => clearTimeout(timer)
  }, [local, onChange])

  // Sync external value changes
  useEffect(() => {
    setLocal(value)
  }, [value])

  return (
    <div className="relative">
      <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
      <input 
        type="text" 
        value={local} 
        onChange={e => setLocal(e.target.value)}
        placeholder="Search by name, specialty, or location..."
        className="w-full pl-12 pr-12 py-3.5 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all"
      />
      {local && (
        <button 
          onClick={() => { setLocal(''); onChange(''); }}
          className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      )}
    </div>
  )
}



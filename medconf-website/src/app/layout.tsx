// src/app/layout.tsx
import type { Metadata } from 'next'
import { Figtree, Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Navbar } from '@/components/layout/Navbar'
import { Footer } from '@/components/layout/Footer'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { AccentProvider, accentNoFlashScript } from '@/components/theme/AccentProvider'
import { SiteChrome } from '@/components/layout/SiteChrome'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

// Display: Figtree. Geometric-humanist, tightens well at large sizes and has a
// genuinely distinct 600/700 — it carries headings without needing colour.
const figtree = Figtree({
  subsets: ['latin'],
  weight: ['500', '600', '700'],
  variable: '--font-figtree',
  display: 'swap',
})

// Body: Inter over Noto Sans. Both are excellent, but Inter ships the OpenType
// features this product leans on — `tnum` for the price/points columns and
// `cv05`/`ss01` for an unambiguous l/I/1 in venue and society acronyms — and
// its tall x-height stays legible at the 13–14px used in dense desktop rows.
// Noto Sans' advantage is script coverage, which a UK/EU/US directory does not
// need.
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

// Mono: JetBrains Mono for dates, prices, CPD points and tags. Tabular by
// construction, so numeric columns align without extra CSS.
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono-jb',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'MedConf — Medical Conference Directory',
  description: 'Find and book medical conferences and CPD opportunities across the UK. Filter by specialty, location, and price.',
  keywords: ['medical conferences', 'CPD', 'healthcare', 'UK', 'professional development'],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${figtree.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        {/* Applies the saved accent before first paint. Theme itself is handled
            by next-themes' own inline script. */}
        <script dangerouslySetInnerHTML={{ __html: accentNoFlashScript }} />
      </head>
      {/*
        W2b: flipped to the token system in the same commit that migrates the
        directory (see /conferences, /societies). Pages not yet redesigned
        (home, auth, dashboard, saved) paint their own full-bleed dark
        background over this, so they're unaffected — only the Navbar/Footer
        chrome and any route without its own background now follow the
        light/dark token system from globals.css.
      */}
      <body className="min-h-screen flex flex-col bg-bg text-fg font-body antialiased">
        <ThemeProvider>
          <AccentProvider>
            <TooltipProvider delayDuration={200}>
              <SiteChrome>
                <Navbar />
              </SiteChrome>
              <main className="flex-1">{children}</main>
              <SiteChrome>
                <Footer />
              </SiteChrome>
              <Toaster />
            </TooltipProvider>
          </AccentProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}

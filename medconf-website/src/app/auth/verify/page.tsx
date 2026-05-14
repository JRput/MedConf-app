// src/app/auth/verify/page.tsx
import Link from 'next/link'
import { Mail, ArrowRight } from 'lucide-react'

export default function VerifyPage() {
  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4 py-12 bg-grid-pattern">
      {/* Background gradient */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl -z-10" />

      <div className="w-full max-w-md text-center">
        <div className="glass-card rounded-2xl p-10">
          {/* Animated envelope icon */}
          <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 flex items-center justify-center animate-pulse">
            <Mail className="w-10 h-10 text-cyan-400" />
          </div>

          <h1 className="text-2xl font-bold text-white font-display mb-3">Check your email</h1>
          
          <p className="text-slate-400 mb-6 leading-relaxed">
            We&apos;ve sent a verification link to your email address. 
            Click the link to verify your account and get started exploring medical conferences.
          </p>

          <div className="space-y-4">
            <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700">
              <p className="text-sm text-slate-300">
                <span className="font-medium text-cyan-400">Tip:</span> Check your spam folder if you don&apos;t see the email within a few minutes.
              </p>
            </div>

            <Link 
              href="/auth/login"
              className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 font-medium text-sm"
            >
              Back to sign in
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}



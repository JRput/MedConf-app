// src/app/page.tsx
import Link from 'next/link'
import { Search, Calendar, Bell, Award, ArrowRight, Check, Stethoscope, MapPin, PoundSterling } from 'lucide-react'

export default function HomePage() {
  return (
    <div className="bg-slate-950">
      {/* Hero Section */}
      <section className="relative min-h-[calc(100vh-4rem)] flex items-center overflow-hidden">
        {/* Background effects */}
        <div className="absolute inset-0 bg-grid-pattern opacity-50" />
        <div className="absolute top-0 right-0 w-[800px] h-[800px] bg-gradient-to-br from-cyan-500/20 via-teal-500/10 to-transparent rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-0 w-[600px] h-[600px] bg-gradient-to-tr from-violet-500/10 via-purple-500/5 to-transparent rounded-full blur-3xl" />
        
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-3xl">
            {/* Badge */}
            <div className="inline-flex items-center gap-2 bg-slate-800/50 border border-slate-700 rounded-full px-4 py-2 mb-8">
              <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
              <span className="text-sm text-slate-300">UK&apos;s #1 Medical Conference Directory</span>
            </div>

            {/* Headline */}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold font-display text-white leading-tight mb-6">
              Find the right medical
              <br />
              <span className="gradient-text">conferences for your career</span>
          </h1>

            {/* Subheadline */}
            <p className="text-lg sm:text-xl text-slate-400 mb-10 max-w-2xl leading-relaxed">
              MedConf is the UK&apos;s comprehensive directory for medical conferences, talks, and CPD opportunities. 
              Search, filter, and save — all in one place.
            </p>

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row gap-4">
              <Link 
                href="/auth/signup" 
                className="inline-flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-8 py-4 rounded-xl font-semibold text-lg hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40"
              >
                Get Started Free
                <ArrowRight className="w-5 h-5" />
              </Link>
              <Link 
                href="/auth/login" 
                className="inline-flex items-center justify-center gap-2 border border-slate-700 text-white px-8 py-4 rounded-xl font-semibold text-lg hover:bg-slate-800/50 hover:border-slate-600 transition-all"
              >
                Sign In
              </Link>
            </div>

            {/* Trust indicators */}
            <div className="flex flex-wrap gap-6 mt-12 text-sm text-slate-400">
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-emerald-400" />
                <span>Free to use</span>
              </div>
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-emerald-400" />
                <span>200+ conferences</span>
              </div>
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-emerald-400" />
                <span>Updated weekly</span>
              </div>
            </div>
          </div>
        </div>

        {/* Decorative illustration - floating cards */}
        <div className="hidden lg:block absolute right-10 top-1/2 -translate-y-1/2 w-[400px]">
          <div className="relative">
            {/* Card 1 */}
            <div className="glass-card rounded-xl p-4 absolute top-0 right-0 w-72 transform rotate-3 animate-fade-in-up">
              <div className="flex justify-between items-start mb-3">
                <span className="text-xs font-semibold text-cyan-400 uppercase">Cardiology</span>
                <span className="inline-flex items-center gap-1 bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-2 py-0.5 rounded-full">
                  <Award className="w-3 h-3" />
                  12 CPD
                </span>
              </div>
              <h3 className="font-bold text-white text-sm mb-2">British Cardiovascular Society Conference 2026</h3>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Calendar className="w-3 h-3" />
                <span>3-5 June 2026</span>
              </div>
            </div>

            {/* Card 2 */}
            <div className="glass-card rounded-xl p-4 absolute top-32 left-10 w-64 transform -rotate-2 animate-fade-in-up delay-200">
              <div className="flex justify-between items-start mb-3">
                <span className="text-xs font-semibold text-violet-400 uppercase">Surgery</span>
                <span className="inline-flex items-center gap-1 bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-2 py-0.5 rounded-full">
                  <Award className="w-3 h-3" />
                  8 CPD
                </span>
              </div>
              <h3 className="font-bold text-white text-sm mb-2">Royal College of Surgeons Annual Meeting</h3>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <MapPin className="w-3 h-3" />
                <span>London</span>
              </div>
            </div>

            {/* Card 3 */}
            <div className="glass-card rounded-xl p-4 absolute top-64 right-8 w-60 transform rotate-1 animate-fade-in-up delay-400">
              <div className="flex justify-between items-start mb-3">
                <span className="text-xs font-semibold text-amber-400 uppercase">GP</span>
                <span className="text-xs text-slate-400">From £150</span>
              </div>
              <h3 className="font-bold text-white text-sm mb-2">Primary Care Conference UK</h3>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Calendar className="w-3 h-3" />
                <span>15-16 March 2026</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-24 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold font-display text-white mb-4">
              Everything you need to find the right event
            </h2>
            <p className="text-slate-400 text-lg max-w-2xl mx-auto">
              Stop wasting time searching across dozens of websites. MedConf brings it all together.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              { 
                icon: <Search className="w-6 h-6" />,
                iconBg: 'from-cyan-500/20 to-teal-500/20',
                iconColor: 'text-cyan-400',
                title: 'Browse & Filter', 
                desc: 'Filter conferences by specialty, location, price range, and CPD status. Find what matters to you in seconds.' 
              },
              { 
                icon: <Calendar className="w-6 h-6" />,
                iconBg: 'from-violet-500/20 to-purple-500/20',
                iconColor: 'text-violet-400',
                title: 'Full Details', 
                desc: 'See complete pricing breakdowns, CPD points, abstract submission status, and venue information.' 
              },
              { 
                icon: <Bell className="w-6 h-6" />,
                iconBg: 'from-amber-500/20 to-orange-500/20',
                iconColor: 'text-amber-400',
                title: 'Stay Informed', 
                desc: 'Get notified when new conferences in your specialty are added, and never miss a deadline.' 
              },
            ].map(f => (
              <div 
                key={f.title} 
                className="glass-card rounded-xl p-6 hover:border-cyan-500/30 transition-all duration-300 group"
              >
                <div className={`w-12 h-12 rounded-lg bg-gradient-to-br ${f.iconBg} flex items-center justify-center mb-4 group-hover:scale-110 transition-transform`}>
                  <div className={f.iconColor}>{f.icon}</div>
                </div>
                <h3 className="font-bold text-white text-lg mb-2">{f.title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Filter Preview Section */}
      <section className="py-24 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-slate-950 via-slate-900/50 to-slate-950" />
        
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div>
              <h2 className="text-3xl sm:text-4xl font-bold font-display text-white mb-6">
                Find exactly what you&apos;re looking for
              </h2>
              <p className="text-slate-400 text-lg mb-8 leading-relaxed">
                Our powerful filtering system helps you narrow down conferences by what matters most to you — 
                whether that&apos;s specialty, budget, or location.
              </p>

              <div className="space-y-4">
                {[
                  { icon: <Stethoscope className="w-5 h-5" />, label: 'Filter by 15+ medical specialties' },
                  { icon: <MapPin className="w-5 h-5" />, label: 'Find events near you across the UK' },
                  { icon: <PoundSterling className="w-5 h-5" />, label: 'See prices for your professional level' },
                  { icon: <Award className="w-5 h-5" />, label: 'Only show CPD-accredited events' },
                ].map((item, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
                      {item.icon}
                    </div>
                    <span className="text-slate-300">{item.label}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Filter preview UI */}
            <div className="glass-card rounded-xl p-6">
              <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                <Search className="w-4 h-4 text-cyan-400" />
                Filters
              </h3>
              
              <div className="space-y-6">
                <div>
                  <label className="text-sm text-slate-400 mb-2 block">Specialty</label>
                  <div className="flex flex-wrap gap-2">
                    {['All', 'Cardiology', 'Surgery', 'GP', 'Emergency'].map((s, i) => (
                      <span 
                        key={s} 
                        className={`text-xs px-3 py-1.5 rounded-full border ${
                          i === 1 
                            ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40' 
                            : 'bg-slate-800/50 text-slate-400 border-slate-700'
                        }`}
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="text-sm text-slate-400 mb-2 block">Location</label>
                  <div className="bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-300 text-sm">
                    London
                  </div>
                </div>

                <div>
                  <label className="text-sm text-slate-400 mb-2 block">Price Range</label>
                  <div className="flex flex-wrap gap-2">
                    {['Any', 'Free', 'Under £100', 'Under £300'].map((p, i) => (
                      <span 
                        key={p} 
                        className={`text-xs px-3 py-1.5 rounded-full border ${
                          i === 2 
                            ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40' 
                            : 'bg-slate-800/50 text-slate-400 border-slate-700'
                        }`}
                      >
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 relative">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="glass-card rounded-2xl p-8 sm:p-12 relative overflow-hidden">
            {/* Gradient bg */}
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/10 via-transparent to-teal-500/10" />
            
            <div className="relative">
              <h2 className="text-3xl sm:text-4xl font-bold font-display text-white mb-4">
                Ready to find your next conference?
              </h2>
              <p className="text-slate-400 text-lg mb-8 max-w-xl mx-auto">
                Join thousands of healthcare professionals already using MedConf to discover CPD opportunities.
              </p>
              
              <Link 
                href="/auth/signup" 
                className="inline-flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-10 py-4 rounded-xl font-semibold text-lg hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40"
              >
                Get Started Free
                <ArrowRight className="w-5 h-5" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

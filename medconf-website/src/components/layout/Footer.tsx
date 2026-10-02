// src/components/layout/Footer.tsx
import Link from 'next/link'

export function Footer() {
  return (
    <footer className="border-t border-border bg-bg">
      <div className="mx-auto max-w-[1320px] px-4 py-10 sm:px-6">
        <div className="grid grid-cols-1 gap-8 md:grid-cols-4">
          <div className="col-span-1 md:col-span-2">
            <div className="flex items-center gap-2">
              <div className="flex size-7 items-center justify-center rounded-md bg-brand">
                <span className="text-xs font-bold text-fg-onbrand">M</span>
              </div>
              <span className="type-h3 text-fg-strong">MedConf</span>
            </div>
            <p className="mt-3 max-w-md text-[0.8125rem] leading-relaxed text-fg-muted">
              A directory of medical conferences, courses and CPD opportunities, pulled daily from royal colleges,
              faculties, specialist societies and international congresses. We don&apos;t take bookings — every
              listing links through to the organiser&apos;s own registration page.
            </p>
          </div>

          <div>
            <h3 className="type-mono-label mb-3 text-fg-subtle">Platform</h3>
            <ul className="space-y-2.5">
              <FooterLink href="/conferences">Directory</FooterLink>
              <FooterLink href="/societies">Societies</FooterLink>
              <FooterLink href="/saved">Saved events</FooterLink>
              <FooterLink href="/settings">Notifications</FooterLink>
            </ul>
          </div>

          <div>
            <h3 className="type-mono-label mb-3 text-fg-subtle">Legal</h3>
            <ul className="space-y-2.5">
              <FooterLink href="#">Privacy policy</FooterLink>
              <FooterLink href="#">Terms of service</FooterLink>
              <FooterLink href="#">Contact</FooterLink>
            </ul>
          </div>
        </div>

        <div className="mt-10 flex flex-col items-center justify-between gap-3 border-t border-border-subtle pt-6 sm:flex-row">
          <p className="text-[0.8125rem] text-fg-subtle">© {new Date().getFullYear()} MedConf.</p>
          <p className="text-[0.8125rem] text-fg-subtle">Data refreshed daily · not affiliated with any listed society</p>
        </div>
      </div>
    </footer>
  )
}

function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <li>
      <Link href={href} className="text-[0.8125rem] text-fg-muted transition-colors duration-150 hover:text-fg">
        {children}
      </Link>
    </li>
  )
}

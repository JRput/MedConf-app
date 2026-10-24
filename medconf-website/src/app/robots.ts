import type { MetadataRoute } from 'next'

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://medconf.vercel.app'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/dashboard', '/saved', '/settings', '/admin', '/api', '/design', '/onboarding'],
    },
    sitemap: `${BASE}/sitemap.xml`,
  }
}

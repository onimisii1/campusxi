import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Installable, offline-capable app shell: scorers can open the app at a pitch with no signal.
    VitePWA({
      registerType: 'autoUpdate',
      manifest: false, // public/manifest.webmanifest is the source of truth
      includeAssets: ['icon.svg', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png', 'manifest.webmanifest'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,webmanifest}'],
        navigateFallback: 'index.html',
        runtimeCaching: [
          {
            // Purely public match data: network first, last known copy when offline. Anything that
            // can carry the signed-in user's own data (summary, contests, leaderboards, /me...) is
            // deliberately not cached here.
            urlPattern: ({ url }) =>
              /^\/(sports|schools|matches(\/[^/]+(\/live)?)?|tournaments(\/[^/]+)?)$/.test(url.pathname),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'campusxi-public-api',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 3600 },
            },
          },
        ],
      },
    }),
  ],
})

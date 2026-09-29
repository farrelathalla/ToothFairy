import withPWAInit from "@ducanh2912/next-pwa";

const withPWA = withPWAInit({
  dest: "public",
  // Disabled in dev so `next dev` is unaffected (and the one-shot 3D setup isn't disturbed).
  disable: process.env.NODE_ENV === "development",
  register: true,
  reloadOnOnline: true,
  cacheOnFrontEndNav: true,
  workboxOptions: {
    disableDevLogs: true,
    // Offline app shell + tuned runtime caching:
    //  • static results (detections/overlays/thumbs/glb) → cache-first (immutable per case)
    //  • API calls → network-first (fresh data, fall back to cache offline)
    runtimeCaching: [
      {
        urlPattern: /\/results\/.*\.(?:json|jpg|jpeg|png|webp|glb)$/i,
        handler: "CacheFirst",
        options: {
          cacheName: "toothfairy-results",
          expiration: { maxEntries: 300, maxAgeSeconds: 30 * 24 * 60 * 60 },
        },
      },
      {
        urlPattern: /\.(?:glb|gltf)$/i,
        handler: "CacheFirst",
        options: {
          cacheName: "toothfairy-models",
          expiration: { maxEntries: 40, maxAgeSeconds: 30 * 24 * 60 * 60 },
        },
      },
      {
        urlPattern: ({ url }) => url.pathname.startsWith("/cases") || url.pathname.startsWith("/auth"),
        handler: "NetworkFirst",
        options: { cacheName: "toothfairy-api", networkTimeoutSeconds: 10 },
      },
      {
        // Patient photos are never written to the offline cache: an installed PWA on a
        // shared clinic device must not retain identifiable images after logout.
        urlPattern: ({ url }) => url.pathname.startsWith("/media/"),
        handler: "NetworkOnly",
      },
    ],
  },
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // avoid double-mount re-running one-shot geometry setup in dev
};

export default withPWA(nextConfig);

# 15 — Dashboard: Traces List Page

## What changed

- Scaffolded Next.js 16 (App Router) + Tailwind v4 inside `dashboard/`
- Created `dashboard/lib/api.ts` — typed server-side API client (no NEXT_PUBLIC, server components only)
- Created `dashboard/app/page.tsx` — traces list: Server Component, async, reads `searchParams` as Promise
- Created `dashboard/app/layout.tsx` — dark background, Geist fonts, "Loupe" title
- Created `dashboard/app/globals.css` — Tailwind v4 theme (dark)
- Added `.env.local` (local key, gitignored), `.env.local.example` (committed), `.gitignore`

## Sub-step learnings

### Next.js 16 App Router — `searchParams` is a Promise

In Next.js 15+, page props (`params`, `searchParams`) are Promises that must be `await`ed. The old pattern:

```typescript
// Next.js 14 — DON'T do this in 15+
export default async function Page({ searchParams }: { searchParams: { offset?: string } }) {
  const offset = searchParams.offset  // ❌ — searchParams is now a Promise
```

Correct pattern:
```typescript
export default async function Page({ searchParams }: {
  searchParams: Promise<{ offset?: string }>
}) {
  const { offset } = await searchParams  // ✅
```

This was introduced so Next.js can optimise when to resolve dynamic data. Forgetting the `await` gives you `[object Promise]` at runtime.

### Server Components for data fetching — no `useEffect`, no `useState`

Server Components can be `async` and `await` data directly — no `useEffect` or client-side fetch needed. The component runs on the server, fetches data, returns HTML. The browser receives rendered HTML with no JavaScript for the data fetching.

This is ideal for a dashboard:
- No loading spinners needed (server waits for data)
- No client-side API key exposure (env vars without `NEXT_PUBLIC_` stay on the server)
- Zero JS bundle overhead for read-only views

The tradeoff: each navigation is a full server round-trip. For this use case (an observability tool, not a real-time app) that's fine. Polling every 2s would be the next step if realtime is needed.

### Tailwind v4 — no config file

Tailwind v4 removes `tailwind.config.ts`. Configuration lives in CSS via `@import "tailwindcss"` and `@theme {}` blocks. The PostCSS plugin (`@tailwindcss/postcss`) handles compilation.

Old (v3):
```javascript
// tailwind.config.ts
export default { content: [...], theme: { extend: {} } }
```

New (v4):
```css
@import "tailwindcss";
@theme inline {
  --color-primary: #6366f1;
}
```

Utility classes still work the same (`bg-gray-950`, `text-sm`, etc.).

### URL-based pagination — no client state

Pagination uses `?offset=20` in the URL instead of `useState`. Advantages:
- Shareable URLs ("send me page 3 of the error traces")
- Works with browser back/forward
- No React state synchronisation
- Server Component can read it directly from `searchParams`

Each page link is a `<Link href="/?offset=40">` — a full server navigation, not a client-side state change.

### API key security in Next.js

`LOUPE_API_KEY` (no `NEXT_PUBLIC_` prefix) is available only in Server Components and server-side code. It is never sent to the browser — Next.js tree-shakes server-only variables from the client bundle. If you use it in a Client Component, Next.js will throw a build error.

`NEXT_PUBLIC_*` variables are embedded in the JS bundle and visible to anyone who inspects the network. Never put API keys there.

## Interview questions this covers

**Q: Why Server Components instead of client-side fetch with useEffect?**  
A: Server Components eliminate the "fetch waterfall" (render → mount → fetch → re-render cycle). The user gets a fully rendered page on the first HTTP response. Also: the API key stays on the server, and there's no JavaScript needed for read-only views.

**Q: How does pagination work without React state?**  
A: URL search params (`?offset=20`) — the server reads `searchParams` from the page props. Browser back/forward work for free, and URLs are shareable. The tradeoff is a full server round-trip per page instead of a client-side state update, which is fine for a dashboard used by one developer.

**Q: What's different about Tailwind v4?**  
A: CSS-first configuration via `@theme {}` blocks instead of a `tailwind.config.ts`. The PostCSS plugin handles compilation. Utility classes are unchanged; the main difference is how you customise the design system.

**Q: What would you add for realtime updates?**  
A: The simplest approach is polling: `router.refresh()` on a `setInterval` in a Client Component shell wrapping the Server Component. This re-fetches server data every N seconds without a full page reload. WebSockets (e.g. via Next.js Route Handlers + Server-Sent Events) would be the production upgrade — but polling every 2s is fine for a dev tool.

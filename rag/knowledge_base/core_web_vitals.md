# Core Web Vitals (web.dev summary)

Core Web Vitals measure real-user experience: LCP, CLS, and INP.

## Thresholds (good)
- LCP ≤ 2.5 seconds
- CLS ≤ 0.1
- INP ≤ 200 milliseconds

## Common LCP fixes
- Optimize and preload the hero/LCP image (correct dimensions, modern formats).
- Reduce render-blocking CSS/JS.
- Use a fast server / CDN TTFB.

## Common CLS fixes
- Set width/height (or aspect-ratio) on images and embeds.
- Avoid inserting content above existing content.
- Use font-display: swap with size-adjusted fallbacks.

## Common INP fixes
- Break up long tasks on the main thread.
- Defer non-critical third-party scripts.

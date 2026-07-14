# web/

The `agentmem.xyz` landing page. Static, single file, no build step: the page, its
favicons, and the OG image. The benchmark numbers on it come from
`evals/longrun_sim/README.md`; update both together.

## Preview locally

```
python3 -m http.server 8871 --directory web
```

## Deploy (Cloudflare Pages)

1. Cloudflare dashboard: Workers & Pages, create a Pages project, connect this repo.
2. Build settings: no framework, no build command, output directory `web`.
3. Custom domain: `agentmem.xyz` (the zone already lives on Cloudflare).

Pushes to `main` redeploy automatically after that.

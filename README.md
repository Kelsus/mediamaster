# MediaMaster

A TV show and Movie "To Watch" list with smarts. Made by Jon Christensen at 
Kelsus.

I hear about TV shows and movies all the time. On X on TikTok from friends 
and even from other TV shows and movies. I like to keep a list of the ones
that sound interesting. 

I used to do this with a Kanban board in Notion, and it worked fine. But 
there were a few things I didn't like:

1. You have to open Notion and navigate to the project to add a new show
2. Notion has a 'load more' button for long columns. So to see something
at the end of a column you have to load and load and load. And then,
especially on their mobile app, if you drill into something and then come
back to the list, your list only contains the initially loaded elements.
You have to load them all over again! What the actual fuck, Notion? Are
you not professional software developers?
3. Once your To Watch list becomes really long, the stuff you added long
ago sinks to the bottom and gets forgotten. So you really only end up
watching things you've recently added to the list (new things are at the
top -- per Kanban).

This product addresses each of these problems. The coolest part is that it
uses LLMs to understand your taste and sorts the To Watch column by
movies and TV shows you're most likely to love. And you have control
over your taste profile in case you want to tweak it.

This is really designed to be a one user app. You can install your own 
on your own AWS account. The authentication is just there for security,
not for multi-user features.

Below here is the AI's description. It's mainly helpful for your AI to get its
'head' around how it works:

---

A self-hosted watchlist kanban that **learns your taste with Claude**. Four
columns — **To Watch · Watching · Done · La Poubelle** — where finished shows
get a 1–3★ rating, La Poubelle counts as a strong dislike, and the To Watch
column continuously re-ranks itself so the things you're most likely to love
sit on top.

Two ranking engines, layered:

1. **The taste engine (Claude Opus 5).** A scorer Lambda distills your entire
   rating history (plus freeform notes you write about your own taste) into a
   written taste profile, then scores every queued show 0–100 with a one-line
   reason — using the model's actual knowledge of each title: plot, tone,
   pacing, reception, and the track record of whoever recommended it to you.
   Re-scoring is manual (a button, or an MCP tool), costs roughly $1–2 per
   ~450-show run, and newly added shows are scored individually within seconds
   for about two cents.
2. **A statistical fallback.** Bayesian-smoothed affinities over recommender /
   streaming service / format, computed at read time — covers anything the LLM
   hasn't scored yet and explains itself in a tooltip.

Other things it does:

- **Passkey login** (Cognito WebAuthn) with password fallback — one-tap Touch ID.
- **One-fetch board**: the entire list loads in a single gzipped request; no
  pagination at any size that matters.
- **MCP server** so Claude (Code or Desktop) can add, move, rate, and discuss
  your shows conversationally — "move Severance to done, 3 stars".
- **Edit-in-place everything**, drag-and-drop between columns, an inline star
  picker when a card lands in Done, two-click card deletion.
- **Notion import**: bring an existing board over from a CSV export.

Everything runs serverless in your own AWS account: CloudFront + S3 in front,
one FastAPI Lambda for the API, one scorer Lambda for the taste engine,
DynamoDB single-table storage, Cognito for auth. Infrastructure is AWS CDK
(Python). There is no vendor, no telemetry, and no data leaves your account
except the show titles sent to the Claude API for scoring.

## Deploy your own

Prerequisites: an AWS account with credentials configured, Node 20+, Python
3.12+, [uv](https://docs.astral.sh/uv/), and an
[Anthropic API key](https://console.anthropic.com/) for the taste engine.

```
git clone https://github.com/kelsus/mediamaster && cd mediamaster
echo "AWS_PROFILE=your-profile" > .env          # optional; defaults to 'default'
npx cdk bootstrap                               # once per AWS account/region
make deploy
```

The first deploy runs CDK twice — the passkey relying-party ID must equal the
CloudFront domain, which doesn't exist until the first pass. When it finishes
it prints your app URL. Then:

```
./scripts/create_user.sh you@example.com        # prints a generated password — save it
```

Store your Anthropic key (prompted silently; zsh syntax — bash users: `read -s -p "key: " KEY`):

```
read -s "KEY?Anthropic API key: " && aws ssm put-parameter --name /mediamaster/anthropic-api-key --type SecureString --value "$KEY" --region us-east-1 && unset KEY
```

Sign in with the password, enroll a passkey when the banner offers, add some
shows, rate a few, and hit **Settings → Re-score now**. A full run takes about
ten minutes; the board reorders itself with Claude's reasoning on every card.

### Custom domain (optional)

Request an ACM certificate for your domain **in us-east-1**, validate it via
DNS, then add to `.env`:

```
CUSTOM_DOMAIN=media.example.com
CERT_ARN=arn:aws:acm:us-east-1:...:certificate/...
```

Re-run `make deploy` and point DNS (ALIAS/CNAME) at the CloudFront domain the
deploy prints. The custom domain becomes the passkey relying-party ID, so
enrolled passkeys must be re-enrolled once after the switch (password login is
unaffected); the raw CloudFront URL 301-redirects to the custom domain.

### Claude / MCP integration

Mint an API token in **Settings → API tokens**, then:

```
claude mcp add mediamaster \
  -e MEDIAMASTER_API_URL=https://<your-cloudfront-domain> \
  -e MEDIAMASTER_API_TOKEN=mm_... \
  -- uv run --directory /path/to/mediamaster/mcp mediamaster-mcp
```

Tools: `list_shows`, `search_shows`, `add_show`, `move_show`, `rate_show`,
`update_show`, `delete_show`, `rescore_board`, `get_taste_profile`.

### Import from Notion

Export your board (··· → Export → CSV, include all content), then:

```
uv run --directory backend python ../scripts/import_notion.py export.csv \
  --api-url https://<your-cloudfront-domain> --token mm_... --dry-run
```

Column/status mappings are constants at the top of the script; check the
dry-run output, adjust, re-run without `--dry-run`. Idempotent.

## Development

```
make test        # backend pytest suite
make dev         # uvicorn :8000 against your deployed table + vite :5173
```

UI-only hacking with zero AWS: `cd backend && uv run python ../scripts/local_mock.py`
(moto-mocked API with seeded sample data), run `npm run dev` in `frontend/`,
and set `localStorage.setItem('mm.devBypass', '1')` in the browser console.

## Repository layout

```
backend/   FastAPI app + taste engine (scoring.py = stats, taste.py + scorer.py = LLM)
frontend/  Vite + React SPA (dnd-kit, TanStack Query)
infra/     AWS CDK stack (Python)
mcp/       MCP server (FastMCP, stdio)
scripts/   deploy, user creation, Lambda bundling, Notion import, local mock
```

## Costs

Idle cost is effectively zero (on-demand DynamoDB, Lambda, CloudFront free
tier, Cognito Essentials at 1 MAU). The taste engine bills your Anthropic API
key: ~$1–2 per full re-score, ~$0.02 per newly added show. You choose when to
re-score.

## License

MIT — see [LICENSE](LICENSE).

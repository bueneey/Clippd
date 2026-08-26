(function () {
  const root = document.getElementById("app");
  const PLATFORMS = ["tiktok", "instagram", "youtube", "x"];
  const vaultCache = {};
  const launchDraft = {
    step: 1,
    ticker: "",
    name: "",
    contract: "",
    hashtag: "",
    image: "",
    brief: "",
    budget_usd: 100,
    rate_per_1k_usd: 1.5,
    ugc_rate_per_1k_usd: 3.5,
    viral_bonus_usd: 500,
    min_views: 5000,
    duration_days: 14,
    platforms: ["tiktok", "instagram", "youtube", "x"],
  };

  function h(html) {
    return html;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }
  function path() {
    return location.pathname.replace(/\/+$/, "") || "/";
  }
  function go(href, ev) {
    if (ev) ev.preventDefault();
    history.pushState({}, "", href);
    render();
  }
  function usd(n) {
    return "$" + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function sol(n) {
    const x = Number(n || 0);
    return x.toLocaleString(undefined, { maximumFractionDigits: 6 }) + " SOL";
  }
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString();
  }

  function nav(active) {
    return `
      <header class="mk-nav">
        <div class="mk-nav-inner">
          <a class="mk-brand" href="/"><img src="/assets/clippdpfp.png" alt="clippd" width="36" height="36"/>clippd</a>
          <div class="mk-sep"></div>
          <nav class="mk-links">
            <a href="/">Home</a>
            <a class="${active === "campaigns" ? "on" : ""}" href="/campaigns" data-nav>Campaigns</a>
            <a class="${active === "launch" ? "on" : ""}" href="/launch" data-nav>Launch</a>
          </nav>
          <div class="mk-nav-right">
            <a class="mk-x" href="https://x.com/clippdpump" target="_blank" rel="noopener" aria-label="clippd on X">
              <img src="/assets/platforms/x.svg" alt="" width="14" height="14"/>
            </a>
            <span data-wallet-slot></span>
            <a class="mk-cta" href="/launch" data-nav>Launch</a>
          </div>
        </div>
      </header>`;
  }

  function wrap(active, inner) {
    return `<div class="mk-wrap">${nav(active)}<main class="mk-main">${inner}</main>
      <footer class="mk-foot">
        <a href="https://x.com/clippdpump" target="_blank" rel="noopener">X · @clippdpump</a>
      </footer></div>`;
  }
  function paint(active, inner) {
    root.innerHTML = wrap(active, inner);
    if (window.ClippdWallet && window.ClippdWallet.refresh) window.ClippdWallet.refresh();
  }
  function walletOrThrow() {
    const w = window.ClippdWallet && window.ClippdWallet.get && window.ClippdWallet.get();
    if (w && w.address) return w;
    if (window.ClippdWallet) window.ClippdWallet.openModal();
    throw new Error("Connect Phantom, Solflare, or MetaMask first.");
  }

  function statusBadge(c) {
    if (c.demo) return `<span class="badge badge-live"><span class="pulse"></span> Demo · Live</span>`;
    if (c.status === "live") return `<span class="badge badge-live"><span class="pulse"></span> Live</span>`;
    return `<span class="badge badge-wait">Awaiting SOL</span>`;
  }

  function platIcon(p, size) {
    const n = size || 16;
    return `<img class="plat-ico" src="/assets/platforms/${esc(p)}.svg" alt="${esc(p)}" width="${n}" height="${n}">`;
  }

  function daysLeft(c) {
    const days = Number(c.duration_days || 14);
    if (!c.created_at) return days;
    const end = new Date(c.created_at).getTime() + days * 86400000;
    return Math.max(0, Math.ceil((end - Date.now()) / 86400000));
  }

  function shortCa(addr) {
    if (!addr) return "";
    return addr.slice(0, 4) + "…" + addr.slice(-6);
  }

  function tokenMark(c, size) {
    const n = size || 44;
    if (c.image) {
      return `<img src="${esc(c.image)}" alt="${esc(c.ticker)}" style="width:${n}px;height:${n}px;border-radius:12px;object-fit:cover;flex-shrink:0;box-shadow:inset 0 0 0 1px ${esc(c.color || "#40bd85")}55">`;
    }
    const letters = String(c.ticker || "$").replace("$", "").slice(0, 3).toUpperCase() || "TKR";
    const color = c.color || "#40bd85";
    return `<div style="width:${n}px;height:${n}px;flex-shrink:0;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;background:${esc(color)}18;color:${esc(color)};box-shadow:inset 0 0 0 1px ${esc(color)}55">${esc(letters)}</div>`;
  }

  function campaignCard(c) {
    const spent = Number(c.spent_usd || 0);
    const budget = Number(c.budget_usd || 0);
    const pct = budget > 0 ? Math.min(100, Math.round((spent / budget) * 100)) : 0;
    const plats = c.platforms && c.platforms.length ? c.platforms : PLATFORMS;
    const live = c.status === "live" || c.demo;
    return `
      <a class="glass-card glass-card-hover camp-card p-5" href="/campaigns/${esc(c.id)}" data-nav>
        <div style="display:flex;align-items:flex-start;gap:.75rem">
          ${tokenMark(c, 44)}
          <div style="min-width:0;flex:1">
            <div style="font-size:15px;font-weight:700;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.ticker)} · ${esc(c.name)}</div>
            <div style="margin-top:.35rem;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
              ${live ? `<span class="badge badge-live"><span class="pulse"></span> Active</span>` : statusBadge(c)}
              <span class="meta" style="margin:0">${daysLeft(c)} days left</span>
            </div>
          </div>
        </div>
        ${
          c.contract
            ? `<button type="button" class="camp-ca" data-ca="${esc(c.contract)}"><span><span style="font-size:9px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;opacity:.7">CA</span> <span class="mono">${esc(shortCa(c.contract))}</span></span><span>Copy</span></button>`
            : ""
        }
        <div style="margin-top:1.15rem">
          <div class="label">Campaign vault</div>
          <div class="stat" style="margin-top:.2rem;font-size:1.85rem">${usd(budget)}</div>
        </div>
        <div style="margin-top:1rem">
          <div class="label">Platforms</div>
          <div class="plat-row" style="margin-top:.5rem">${plats.map((p) => platIcon(p, 16)).join("")}</div>
        </div>
        <div style="margin-top:1rem;padding-top:.75rem;border-top:1px solid var(--hairline)">
          <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--muted)">
            <span><b style="color:var(--foreground)">${usd(spent)}</b> paid out</span>
            <span>of <b style="color:var(--foreground)">${usd(budget)}</b></span>
          </div>
          <div style="margin-top:.4rem;height:6px;border-radius:99px;background:var(--surface);overflow:hidden">
            <div style="height:100%;width:${pct}%;background:var(--primary);border-radius:99px"></div>
          </div>
          <div style="margin-top:.4rem;display:flex;justify-content:space-between;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)">
            <span>${pct}% used</span>
            <span>Min ${(c.min_views || 0).toLocaleString()} views to qualify</span>
          </div>
        </div>
      </a>`;
  }

  async function pageCampaigns() {
    let campaigns = [];
    let err = "";
    try {
      campaigns = (await api("/api/campaigns")).campaigns || [];
    } catch (e) {
      err = e.message;
    }
    const live = campaigns.filter((c) => c.status === "live" || c.demo);
    const wait = campaigns.filter((c) => c.status !== "live" && !c.demo);
    const all = live.concat(wait);
    const pool = all.reduce((s, c) => s + Number(c.budget_usd || 0), 0);
    const paid = all.reduce((s, c) => s + Number(c.spent_usd || 0), 0);
    const clips = all.reduce((s, c) => s + ((c.submissions && c.submissions.length) || 0), 0);
    paint(
      "campaigns",
      `
      <div class="page-badge"><span class="pulse"></span> Open marketplace · Paid in SOL from campaign vaults</div>
      <div class="page-head">
        <div>
          <h1 class="page-title">Active Campaigns</h1>
          <p class="page-sub">Every campaign, every dollar. Vaults update as SOL lands and clips get verified.</p>
        </div>
        <a class="btn-pill go primary" href="/launch" data-nav>Launch a campaign</a>
      </div>
      <div class="stat-strip">
        <div class="stat-cell"><div class="label">Total vault</div><div class="stat accent">${usd(pool)}</div></div>
        <div class="stat-cell"><div class="label">Paid out</div><div class="stat">${usd(paid)}</div></div>
        <div class="stat-cell"><div class="label">Clips submitted</div><div class="stat">${clips}</div></div>
        <div class="stat-cell"><div class="label">Campaigns live</div><div class="stat">${live.length}</div></div>
      </div>
      ${err ? `<p class="err">${esc(err)}</p>` : ""}
      ${
        !all.length
          ? `<div class="empty card" style="margin-top:2rem">No campaigns yet. Fund a vault to go live.</div>`
          : `<div class="camp-grid">${all.map(campaignCard).join("")}</div>`
      }`
    );
    document.querySelectorAll("[data-ca]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(btn.getAttribute("data-ca"));
        btn.querySelector("span:last-child").textContent = "Copied";
        setTimeout(() => {
          btn.querySelector("span:last-child").textContent = "Copy";
        }, 1200);
      });
    });
  }

  function embedBlock(clip) {
    const iframe = clip.embed && clip.embed.iframe;
    if (iframe) {
      return `<iframe class="embed" src="${esc(iframe)}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" allowfullscreen loading="lazy"></iframe>`;
    }
    return `<div class="empty">Open the ${esc(clip.platform)} post →</div>`;
  }

  async function pageCampaign(id) {
    paint("campaigns", `<p class="mk-lead">Loading campaign…</p>`);
    let c, err;
    try {
      c = (await api("/api/campaigns/" + id)).campaign;
    } catch (e) {
      err = e.message;
    }
    if (!c) {
      paint("campaigns", `<h1 class="mk-h1">Not found.</h1><p class="err">${esc(err || "")}</p><p><a href="/campaigns" data-nav>Back to campaigns</a></p>`);
      return;
    }
    const clips = c.submissions || [];
    paint(
      "campaigns",
      `
      <a href="/campaigns" data-nav class="mk-kicker">← All campaigns</a>
      <div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:1rem;align-items:flex-end;margin-top:.5rem">
        <div>
          <h1 class="mk-h1">${esc(c.ticker)}</h1>
          <p class="mk-lead" style="margin-top:.6rem">${esc(c.name)} ${statusBadge(c)}</p>
        </div>
        <div style="text-align:right">
          <div class="label">Budget · vault</div>
          <div class="stat">${usd(c.budget_usd)}</div>
          <div class="meta" style="justify-content:flex-end">${esc(sol(c.received_sol || 0))} received</div>
        </div>
      </div>
      <div class="grid grid-2" style="margin-top:1.5rem">
        <div class="card">
          <div class="label">Rate per 1K views</div>
          <div class="stat">${usd(c.rate_per_1k_usd)} <span style="font-size:13px;font-weight:600;color:var(--muted)">paid in SOL</span></div>
          ${c.ugc_rate_per_1k_usd ? `<p class="meta">UGC / face-cam ${usd(c.ugc_rate_per_1k_usd)} / 1K</p>` : ""}
          ${c.viral_bonus_usd ? `<p class="meta">Viral bonus ${usd(c.viral_bonus_usd)}</p>` : ""}
          <p class="meta">Min ${esc(String(c.min_views))} views · ${esc(String(c.duration_days))} days</p>
          <div class="plat-row" style="margin-top:.75rem">${(c.platforms || []).map((p) => platIcon(p, 18)).join("")}</div>
          ${c.hashtag ? `<p class="meta">${esc(c.hashtag)}</p>` : ""}
          ${c.contract ? `<p class="mono meta">CA ${esc(c.contract)}</p>` : ""}
          ${c.brief ? `<p style="margin-top:1rem;line-height:1.6">${esc(c.brief)}</p>` : ""}
        </div>
        <div class="card">
          <div class="label">Campaign vault</div>
          <div class="addr" style="margin-top:.6rem">${esc(c.vault_address)}</div>
          <p class="meta">Expected ${esc(sol(c.expected_sol))} · quoted at ${usd(c.sol_price_usd)} / SOL</p>
          ${c.status !== "live" ? `<p class="err" style="margin-top:1rem">This campaign is not live until the vault receives the SOL.</p>` : `<p class="ok" style="margin-top:1rem">Vault funded. Submit a clip below.</p>`}
        </div>
      </div>
      <div class="grid grid-2" style="margin-top:1.5rem">
        <form id="clip-form" class="card">
          <div class="label">Submit a clip</div>
          <p class="meta" style="margin-bottom:1rem">Paste a TikTok, Instagram, YouTube, or X link. Connect a wallet first.</p>
          <div class="field"><label>Clip URL</label><input name="url" placeholder="https://www.tiktok.com/@you/video/…" required></div>
          <div class="field"><label>Handle (optional)</label><input name="handle" placeholder="@yourhandle"></div>
          <button class="btn btn-primary" ${c.status !== "live" ? "disabled" : ""}>Submit clip</button>
          <div class="err" id="clip-err"></div>
        </form>
        <div class="card">
          <div class="label">Submitted</div>
          <div class="stat">${clips.length}</div>
          <p class="meta">TikTok, Instagram, YouTube, and X posts show here as they come in.</p>
        </div>
      </div>
      <h2 style="margin:2.5rem 0 1rem;font-size:1.6rem;letter-spacing:-.04em">Clips</h2>
      ${
        !clips.length
          ? `<div class="empty card">Nothing submitted yet.</div>`
          : `<div class="clips">${clips
              .map(
                (clip) => `
            <article class="card">
              <div class="clip-top">
                <div>
                  <div class="badge badge-live">${esc(clip.platform)}</div>
                  <div class="meta">${esc(clip.handle || "")} · ${esc(when(clip.created_at))}</div>
                </div>
                <a class="btn btn-ghost btn-sm" href="${esc(clip.url)}" target="_blank" rel="noopener">Open post</a>
              </div>
              ${embedBlock(clip)}
            </article>`
              )
              .join("")}</div>`
      }`
    );

    const form = document.getElementById("clip-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errEl = document.getElementById("clip-err");
        errEl.textContent = "";
        const fd = new FormData(form);
        try {
          const w = walletOrThrow();
          await api("/api/campaigns/" + id + "/clips", {
            method: "POST",
            body: JSON.stringify({ url: fd.get("url"), handle: fd.get("handle"), clipper_wallet: w.address, clipper_wallet_name: w.wallet }),
          });
          pageCampaign(id);
        } catch (err) {
          errEl.textContent = err.message;
        }
      });
    }

    if (c.status !== "live") {
      setTimeout(() => {
        if (path() === "/campaigns/" + id) pageCampaign(id);
      }, 5000);
    }
  }

  function readLaunchFields() {
    const d = launchDraft;
    const val = (name) => {
      const el = document.querySelector("[name='" + name + "']");
      return el ? el.value : d[name];
    };
    d.ticker = val("ticker");
    d.name = val("name");
    d.contract = val("contract");
    d.hashtag = val("hashtag");
    d.brief = val("brief");
    ["budget_usd", "rate_per_1k_usd", "ugc_rate_per_1k_usd", "viral_bonus_usd", "min_views", "duration_days"].forEach((k) => {
      const el = document.querySelector("[name='" + k + "']");
      if (el && el.value !== "") d[k] = Number(el.value);
    });
  }

  function stepper(step) {
    const names = ["Project", "Rates & platforms", "Rules & vault"];
    return `<div class="stepper">${names
      .map((n, i) => {
        const s = i + 1;
        const cls = step > s ? "done" : step === s ? "on" : "";
        return `<div class="stepper-item">
          <div class="step-num ${cls}">${step > s ? "✓" : s}</div>
          <div class="step-lab ${step === s ? "on" : ""}">${n}</div>
          ${i < names.length - 1 ? `<div class="step-line"></div>` : ""}
        </div>`;
      })
      .join("")}</div>`;
  }

  async function pageLaunch(payId) {
    if (payId) return pageFund(payId);
    const d = launchDraft;
    let quote = { usd: d.budget_usd, sol: 0, sol_price_usd: 0 };
    try {
      quote = await api("/api/quote?usd=" + Math.max(10, Number(d.budget_usd) || 10));
    } catch (e) {
      quote = { usd: d.budget_usd, sol: 0, sol_price_usd: 0, error: e.message || "Could not fetch SOL price" };
    }

    const step1 = `
      <div class="field"><label>Token image</label>
        <div style="display:flex;align-items:center;gap:1rem">
          <label class="token-up">${d.image ? `<img src="${esc(d.image)}" alt="">` : `<span class="label" style="text-align:center;padding:.5rem">Upload</span>`}<input id="token-file" type="file" accept="image/*"></label>
          <div class="meta" style="margin:0">Square PNG or JPG. This shows on your campaign cards.${d.image ? ` <button type="button" id="token-remove" class="btn-pill" style="padding:.2rem .6rem">Remove</button>` : ""}</div>
        </div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>Ticker *</label><input class="input" name="ticker" placeholder="$ANSEM" value="${esc(d.ticker)}"></div>
        <div class="field"><label>Project name *</label><input class="input" name="name" placeholder="Ansem" value="${esc(d.name)}"></div>
      </div>
      <div class="field"><label>Contract address</label><input class="input mono" name="contract" placeholder="9cRC…pump" value="${esc(d.contract)}"></div>
      <div class="field"><label>Campaign hashtag</label><input class="input" name="hashtag" placeholder="#ansem" value="${esc(d.hashtag)}"></div>`;

    const step2 = `
      <div class="grid grid-2">
        <div class="field"><label>Total budget (USD)</label><input class="input" name="budget_usd" type="number" min="10" step="1" value="${esc(d.budget_usd)}"></div>
        <div class="field"><label>Min views to qualify</label><input class="input" name="min_views" type="number" min="0" step="100" value="${esc(d.min_views)}"></div>
        <div class="field"><label>Standard rate / 1K views</label><input class="input" name="rate_per_1k_usd" type="number" min="0.01" step="0.05" value="${esc(d.rate_per_1k_usd)}"></div>
        <div class="field"><label>UGC rate / 1K views</label><input class="input" name="ugc_rate_per_1k_usd" type="number" min="0" step="0.05" value="${esc(d.ugc_rate_per_1k_usd)}"></div>
        <div class="field"><label>Viral bonus (USD)</label><input class="input" name="viral_bonus_usd" type="number" min="0" step="1" value="${esc(d.viral_bonus_usd)}"></div>
        <div class="field"><label>Duration (days)</label><input class="input" name="duration_days" type="number" min="1" value="${esc(d.duration_days)}"></div>
      </div>
      <div class="field"><label>Allowed platforms</label>
        <div class="plat-row" style="flex-wrap:wrap;gap:.5rem">
          ${PLATFORMS.map((p) => {
            const on = d.platforms.includes(p) ? "on" : "";
            return `<button type="button" class="plat-chip ${on}" data-plat="${p}">${platIcon(p, 16)}${p}</button>`;
          }).join("")}
        </div>
      </div>`;

    const step3 = `
      <div class="field"><label>Rules &amp; requirements</label>
        <textarea class="input" name="brief" rows="8" placeholder="• Post must include ${esc(d.hashtag || "#hashtag")}\n• Original edits only\n• No AI voice-over\n• Payout after ${esc(String(d.min_views))} views">${esc(d.brief)}</textarea>
      </div>
      <div class="warn">On launch we generate a fresh campaign vault. You get the deposit address and the private key — shown once. Store it somewhere safe.</div>`;

    const previewTick = d.ticker ? (d.ticker.startsWith("$") ? d.ticker.toUpperCase() : "$" + d.ticker.toUpperCase()) : "$TICKER";

    paint(
      "launch",
      `
      <div class="page-head">
        <div>
          <div class="mk-kicker">Campaigns</div>
          <h1 class="page-title" style="margin-top:.5rem">Launch a campaign</h1>
          <p class="page-sub">Set your rates, generate a vault wallet, and go live.</p>
        </div>
      </div>
      <div class="launch-grid">
        <form id="launch-form" class="launch-form">
          ${stepper(d.step)}
          <div style="margin-top:1.5rem">${d.step === 1 ? step1 : d.step === 2 ? step2 : step3}</div>
          <div class="launch-nav">
            <button type="button" class="btn-pill" id="launch-back">${d.step === 1 ? "Cancel" : "← Back"}</button>
            ${
              d.step < 3
                ? `<button type="button" class="btn-pill go" id="launch-next">Continue →</button>`
                : `<button type="submit" class="btn-pill go primary" id="launch-submit">Generate vault &amp; launch</button>`
            }
          </div>
          <div class="err" id="launch-err"></div>
        </form>
        <aside>
          <div class="preview-card">
            <div class="label">Preview</div>
            <div style="margin-top:1rem;display:flex;align-items:flex-start;gap:.75rem">
              ${tokenMark({ ticker: previewTick, name: d.name, image: d.image, color: "#40bd85" }, 44)}
              <div>
                <div style="font-weight:800;font-size:14px">${esc(previewTick)}</div>
                <div class="meta" style="margin:.2rem 0 0">${esc(d.name || "Project name")}</div>
              </div>
            </div>
            <div class="grid grid-2" style="margin-top:1rem;gap:.5rem">
              <div class="mini-stat"><div class="label">Budget</div><div style="font-weight:800;margin-top:.2rem">${usd(d.budget_usd)}</div></div>
              <div class="mini-stat"><div class="label">Std rate</div><div style="font-weight:800;margin-top:.2rem">$${esc(d.rate_per_1k_usd)}/1K</div></div>
            </div>
            <div class="plat-row" style="margin-top:1rem">${d.platforms.map((p) => platIcon(p, 16)).join("")}</div>
          </div>
          <div class="preview-card" style="margin-top:1rem;background:linear-gradient(180deg, color-mix(in oklab, var(--primary) 10%, #fff), #fff)">
            <div class="label" style="color:var(--primary)">Campaign vault</div>
            <div class="stat" id="quote-sol" style="margin-top:.5rem">${quote.sol ? sol(quote.sol) : "…"}</div>
            <p class="meta" id="quote-meta">${quote.error ? esc(quote.error) : quote.sol_price_usd ? usd(quote.sol_price_usd) + " / SOL · " + usd(quote.usd) + " budget" : "Fetching price…"}</p>
            <p class="meta">Each campaign gets its own wallet. Send the quoted SOL and the campaign goes live when it lands.</p>
          </div>
        </aside>
      </div>`
    );

    const file = document.getElementById("token-file");
    if (file) {
      file.addEventListener("change", () => {
        const f = file.files && file.files[0];
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
          launchDraft.image = String(reader.result || "");
          readLaunchFields();
          pageLaunch();
        };
        reader.readAsDataURL(f);
      });
    }
    const remove = document.getElementById("token-remove");
    if (remove) {
      remove.onclick = () => {
        launchDraft.image = "";
        readLaunchFields();
        pageLaunch();
      };
    }
    document.querySelectorAll("[data-plat]").forEach((btn) => {
      btn.addEventListener("click", () => {
        readLaunchFields();
        const p = btn.getAttribute("data-plat");
        if (d.platforms.includes(p)) d.platforms = d.platforms.filter((x) => x !== p);
        else d.platforms = d.platforms.concat(p);
        if (!d.platforms.length) d.platforms = [p];
        pageLaunch();
      });
    });
    const budget = document.querySelector("[name='budget_usd']");
    if (budget) {
      budget.addEventListener("input", () => {
        clearTimeout(budget._t);
        budget._t = setTimeout(async () => {
          const usdVal = Math.max(10, Number(budget.value) || 0);
          try {
            const q = await api("/api/quote?usd=" + usdVal);
            const solEl = document.getElementById("quote-sol");
            const metaEl = document.getElementById("quote-meta");
            if (solEl) solEl.textContent = sol(q.sol);
            if (metaEl) metaEl.textContent = usd(q.sol_price_usd) + " / SOL · " + usd(q.usd) + " budget";
          } catch (e) {}
        }, 250);
      });
    }
    const back = document.getElementById("launch-back");
    if (back) {
      back.onclick = () => {
        readLaunchFields();
        if (d.step === 1) return go("/campaigns");
        d.step -= 1;
        pageLaunch();
      };
    }
    const next = document.getElementById("launch-next");
    if (next) {
      next.onclick = () => {
        readLaunchFields();
        if (d.step === 1 && (!String(d.ticker).trim() || !String(d.name).trim())) {
          const err = document.getElementById("launch-err");
          if (err) err.textContent = "Ticker and project name are required.";
          return;
        }
        d.step += 1;
        pageLaunch();
      };
    }
    const form = document.getElementById("launch-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      readLaunchFields();
      const errEl = document.getElementById("launch-err");
      errEl.textContent = "";
      try {
        const w = walletOrThrow();
        const created = await api("/api/campaigns", {
          method: "POST",
          body: JSON.stringify({
            ticker: d.ticker,
            name: d.name,
            contract: d.contract,
            brief: d.brief,
            hashtag: d.hashtag,
            image: d.image,
            budget_usd: Number(d.budget_usd),
            rate_per_1k_usd: Number(d.rate_per_1k_usd),
            ugc_rate_per_1k_usd: d.ugc_rate_per_1k_usd || null,
            viral_bonus_usd: d.viral_bonus_usd || null,
            min_views: Number(d.min_views),
            duration_days: Number(d.duration_days),
            platforms: d.platforms,
            creator_wallet: w.address,
            creator_wallet_name: w.wallet,
          }),
        });
        vaultCache[created.campaign.id] = created.vault;
        launchDraft.step = 1;
        go("/launch/" + created.campaign.id);
      } catch (err) {
        errEl.textContent = err.message;
      }
    });
  }

  async function pageFund(id) {
    paint("launch", `<p class="mk-lead">Creating vault…</p>`);
    let c;
    try {
      c = (await api("/api/campaigns/" + id)).campaign;
    } catch (e) {
      paint("launch", `<h1 class="mk-h1">Campaign not found.</h1><p class="err">${esc(e.message)}</p>`);
      return;
    }
    const vault = vaultCache[id];
    const funded = c.status === "live";
    paint(
      "launch",
      `
      <div class="mk-kicker">${funded ? "Live" : "Fund the vault"}</div>
      <h1 class="mk-h1">${esc(c.ticker)}</h1>
      <p class="mk-lead">Send exactly this SOL to the campaign wallet. We check the chain until it lands, then the campaign goes live.</p>
      <div class="grid grid-2" style="margin-top:1.5rem">
        <div class="card">
          <div class="label">Send</div>
          <div class="stat">${esc(sol(c.expected_sol))}</div>
          <p class="meta">${usd(c.budget_usd)} at ${usd(c.sol_price_usd)} / SOL</p>
          <div class="label" style="margin-top:1.25rem">To</div>
          <div class="addr" id="vault-addr">${esc(c.vault_address)}</div>
          <div class="mk-row">
            <button class="btn btn-ghost btn-sm" id="copy-addr" type="button">Copy address</button>
            ${c.funding_signature ? `<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="https://solscan.io/account/${esc(c.vault_address)}">Solscan</a>` : ""}
          </div>
          <p class="meta" style="margin-top:1rem">Received ${esc(sol(c.received_sol || 0))} ${funded ? "· funded" : "· waiting on-chain"}</p>
        </div>
        <div class="card">
          ${
            funded
              ? `<div class="ok">Vault funded. Campaign is live on the board.</div>
                 <div class="mk-row"><a class="btn btn-primary" href="/campaigns/${esc(c.id)}" data-nav>Open campaign</a></div>`
              : `<div class="warn">Waiting for SOL. Keep this page open — we poll Solana every few seconds.</div>`
          }
          ${
            vault
              ? `<div class="warn" style="margin-top:1rem"><b>Your keys were also saved to data/VAULT_KEYS.txt.</b> Copy them now if you want them on this machine’s clipboard. Do not share this box.</div>
                 <div class="keys" style="margin-top:.75rem">address: ${esc(vault.address)}
secret_base58: ${esc(vault.secret_base58)}
secret_json: ${esc(JSON.stringify(vault.secret_json))}</div>
                 <button class="btn btn-ghost btn-sm" style="margin-top:.75rem" id="copy-keys" type="button">Copy keys</button>`
              : `<p class="meta" style="margin-top:1rem">Keys for this vault are in <b>data/VAULT_KEYS.txt</b> on this computer. They are not shown again in the browser after you leave this page.</p>`
          }
        </div>
      </div>`
    );

    const copyAddr = document.getElementById("copy-addr");
    if (copyAddr) copyAddr.onclick = () => navigator.clipboard.writeText(c.vault_address);
    const copyKeys = document.getElementById("copy-keys");
    if (copyKeys && vault) {
      copyKeys.onclick = () =>
        navigator.clipboard.writeText(
          JSON.stringify({ address: vault.address, secret_base58: vault.secret_base58, secret_json: vault.secret_json }, null, 2)
        );
    }
    if (!funded) {
      setTimeout(() => {
        if (path() === "/launch/" + id) pageFund(id);
      }, 4000);
    }
  }

  async function render() {
    const p = path();
    document.title = "clippd";
    if (p === "/campaigns") return pageCampaigns();
    let m = p.match(/^\/campaigns\/([^/]+)$/);
    if (m) return pageCampaign(m[1]);
    if (p === "/launch") return pageLaunch();
    m = p.match(/^\/launch\/([^/]+)$/);
    if (m) return pageLaunch(m[1]);
    location.replace("/");
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-nav]");
    if (!a) return;
    go(a.getAttribute("href"), e);
  });
  window.addEventListener("popstate", render);
  render();
})();

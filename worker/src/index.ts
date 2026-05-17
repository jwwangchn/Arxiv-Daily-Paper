import { Hono } from "hono";
import { cors } from "hono/cors";

export interface Env {
  DB: D1Database;
  API_TOKEN?: string;
}

const app = new Hono<{ Bindings: Env }>();

// Map legacy priority values to frontend-friendly labels
const PRIORITY_MAP: Record<string, string> = {
  must_read: "high", recommended: "medium", skim: "low",
  low_priority: "low", skip: "low",
};

const DATA_CACHE_SECONDS = 900;
const BROWSER_CACHE_SECONDS = 300;
const MAX_PAGE_SIZE = 100;

function cacheableJson(c: any, data: unknown): Response {
  const response = c.json(data);
  response.headers.set(
    "Cache-Control",
    `public, max-age=${BROWSER_CACHE_SECONDS}, s-maxage=${DATA_CACHE_SECONDS}, stale-while-revalidate=86400`,
  );
  return response;
}

async function cachedGet(c: any, key: string, loader: () => Promise<Response>): Promise<Response> {
  const cache = (caches as any).default;
  const request = new Request(key, c.req.raw);
  const cached = await cache.match(request);
  if (cached) return cached;

  const response = await loader();
  c.executionCtx.waitUntil(cache.put(request, response.clone()));
  return response;
}

// CORS for Pages frontend
app.use("/*", cors({
  origin: "*",
  allowMethods: ["GET", "POST", "OPTIONS"],
  allowHeaders: ["Content-Type", "Authorization"],
}));

// Health check
app.get("/health", (c) => c.json({ status: "ok", timestamp: new Date().toISOString() }));

// GET /api/dates - List all available dates with paper counts
app.get("/api/dates", async (c) => {
  return cachedGet(c, c.req.url, async () => {
  const { results } = await c.env.DB.prepare(`
    SELECT
      p.source_date as date,
      substr(p.source_date, 1, 7) as month,
      COUNT(*) as count,
      COUNT(a.arxiv_id) as analyzed_count
    FROM papers p
    LEFT JOIN analyses a ON p.id = a.arxiv_id
    WHERE p.source_date != ''
    GROUP BY p.source_date
    ORDER BY p.source_date DESC
  `).all<{ date: string; month: string; count: number; analyzed_count: number }>();

  const latest = results.length > 0 ? results[0].date : "";
  return cacheableJson(c, { latest, dates: results });
  });
});

// GET /api/papers?date=YYYY-MM-DD - Papers for a specific date
app.get("/api/papers", async (c) => {
  const date = c.req.query("date");
  const month = c.req.query("month");
  const id = c.req.query("id");
  const source = c.req.query("source") || "arxiv";

  if ((date || month) && !id && source === "arxiv") {
    return cachedGet(c, c.req.url, async () => loadPapers(c, date, month, source));
  }

  return loadPapers(c, date, month, source, id);
});

async function loadPapers(c: any, date?: string, month?: string, source = "arxiv", id?: string): Promise<Response> {

  if (id) {
    // Single paper lookup
    const paper = await c.env.DB.prepare("SELECT id as arxiv_id, source, title, authors, abstract, categories, primary_category, published, updated, entry_url, pdf_url, source_date, venue, year FROM papers WHERE id = ?").bind(id).first();
    if (!paper) return c.json({ error: "Paper not found" }, 404);
    const analysis = await c.env.DB.prepare("SELECT * FROM analyses WHERE arxiv_id = ?").bind(id).first();
    return c.json(normalizePaperRow({ ...paper, ...analysis, analysis_id: (analysis as any)?.arxiv_id || "" }));
  }

  const limitParam = c.req.query("limit");
  const offsetParam = c.req.query("offset");
  const paginated = limitParam !== undefined || offsetParam !== undefined;
  const limit = Math.min(Math.max(parseInt(limitParam || "50", 10) || 50, 1), MAX_PAGE_SIZE);
  const offset = Math.max(parseInt(offsetParam || "0", 10) || 0, 0);
  const priority = c.req.query("priority") || "";
  const tag = c.req.query("tag") || "";
  const area = c.req.query("area") || "";
  const subarea = c.req.query("subarea") || "";
  const q = c.req.query("q") || "";

  let whereClause = source === "all" ? "WHERE 1=1" : "WHERE p.source = ?";
  let bindings: (string | number)[] = source === "all" ? [] : [source];

  if (date) {
    whereClause += " AND p.source_date = ?";
    bindings.push(date);
  } else if (month) {
    whereClause += " AND p.source_date LIKE ?";
    bindings.push(`${month}-%`);
  }

  if (priority) {
    whereClause += ` AND (CASE a.reading_priority
      WHEN 'must_read' THEN 'high'
      WHEN 'recommended' THEN 'medium'
      WHEN 'skim' THEN 'low'
      WHEN 'low_priority' THEN 'low'
      WHEN 'skip' THEN 'low'
      ELSE a.reading_priority
    END) = ?`;
    bindings.push(priority);
  }

  if (tag) {
    whereClause += " AND a.tags LIKE ?";
    bindings.push(`%"${tag}"%`);
  }

  if (area) {
    if (area === "未分析") {
      whereClause += " AND a.arxiv_id IS NULL";
    } else {
      whereClause += " AND a.primary_area = ?";
      bindings.push(area);
    }
  }

  if (subarea) {
    if (subarea === "未分析") {
      whereClause += " AND a.arxiv_id IS NULL";
    } else {
      whereClause += " AND (a.category = ? OR a.sub_area = ?)";
      bindings.push(subarea, subarea);
    }
  }

  if (q) {
    const like = `%${q}%`;
    whereClause += ` AND (
      p.title LIKE ? OR p.abstract LIKE ? OR p.authors LIKE ?
      OR a.tldr LIKE ? OR a.problem LIKE ? OR a.method LIKE ?
    )`;
    bindings.push(like, like, like, like, like, like);
  }

  let total = 0;
  if (paginated) {
    const totalRow = await c.env.DB.prepare(`
      SELECT COUNT(*) as total
      FROM papers p
      LEFT JOIN analyses a ON p.id = a.arxiv_id
      ${whereClause}
    `).bind(...bindings).first<{ total: number }>();
    total = totalRow?.total || 0;
  }

  const { results } = await c.env.DB.prepare(`
    SELECT p.id as arxiv_id, p.source, p.title, p.authors, p.abstract,
           p.categories, p.primary_category, p.published, p.updated,
           p.entry_url, p.pdf_url, p.source_date, p.venue, p.year,
           a.tldr, a.research_motivation, a.problem, a.phenomenon_analysis,
           a.method, a.contributions, a.experiments, a.limitations,
           a.primary_area_en, a.primary_area, a.category, a.sub_area,
           a.arxiv_id as analysis_id,
           a.tags, a.reading_priority, a.recommended_action,
           a.analysis_version, a.analyzed_at
    FROM papers p
    LEFT JOIN analyses a ON p.id = a.arxiv_id
    ${whereClause}
    ORDER BY
      CASE a.reading_priority
        WHEN 'high' THEN 0
        WHEN 'medium' THEN 1
        WHEN 'low' THEN 2
        ELSE 3
      END,
      p.source_date DESC,
      p.id DESC
    ${paginated ? "LIMIT ? OFFSET ?" : ""}
  `).bind(...(paginated ? [...bindings, limit, offset] : bindings)).all();

  // Parse JSON fields and normalize priority values
  const parsed = results.map(normalizePaperRow);

  if (!paginated) return cacheableJson(c, parsed);
  return cacheableJson(c, { papers: parsed, total, limit, offset });
}

// GET /api/facets?date=YYYY-MM-DD - Lightweight facet counts for a date
app.get("/api/facets", async (c) => {
  return cachedGet(c, c.req.url, async () => {
    const date = c.req.query("date");
    const month = c.req.query("month");
    const source = c.req.query("source") || "arxiv";
    let whereClause = source === "all" ? "WHERE 1=1" : "WHERE p.source = ?";
    const bindings: string[] = source === "all" ? [] : [source];
    if (date) {
      whereClause += " AND p.source_date = ?";
      bindings.push(date);
    } else if (month) {
      whereClause += " AND p.source_date LIKE ?";
      bindings.push(`${month}-%`);
    }

    const { results } = await c.env.DB.prepare(`
      SELECT a.arxiv_id as analysis_id, a.primary_area, a.category, a.sub_area,
             a.tags, a.reading_priority
      FROM papers p
      LEFT JOIN analyses a ON p.id = a.arxiv_id
      ${whereClause}
    `).bind(...bindings).all();

    const priorities: Record<string, number> = { high: 0, medium: 0, low: 0 };
    const tags = new Map<string, number>();
    const areas = new Map<string, Map<string, number>>();

    for (const row of results as any[]) {
      const priority = PRIORITY_MAP[row.reading_priority] || row.reading_priority || "unknown";
      if (priority in priorities) priorities[priority] += 1;
      const area = row.analysis_id ? (row.primary_area || "其他 ML 主题") : "未分析";
      const sub = row.analysis_id ? (row.category || row.sub_area || "其他") : "未分析";
      if (!areas.has(area)) areas.set(area, new Map());
      const subMap = areas.get(area)!;
      subMap.set(sub, (subMap.get(sub) || 0) + 1);
      if (row.analysis_id) {
        for (const tag of safeJsonParse(row.tags)) {
          tags.set(tag, (tags.get(tag) || 0) + 1);
        }
      }
    }

    return cacheableJson(c, {
      priorities,
      tags: [...tags.entries()],
      areas: [...areas.entries()].map(([areaName, subMap]) => [areaName, [...subMap.entries()]]),
    });
  });
});

// GET /api/stats - Overall statistics
app.get("/api/stats", async (c) => {
  const paperCount = await c.env.DB.prepare("SELECT COUNT(*) as count FROM papers").first();
  const analysisCount = await c.env.DB.prepare("SELECT COUNT(*) as count FROM analyses").first();
  const dateCount = await c.env.DB.prepare("SELECT COUNT(DISTINCT source_date) as count FROM papers WHERE source_date != ''").first();

  const { results: areaCounts } = await c.env.DB.prepare(`
    SELECT primary_area, COUNT(*) as count FROM analyses
    WHERE primary_area != ''
    GROUP BY primary_area
    ORDER BY count DESC
  `).all<{ primary_area: string; count: number }>();

  return c.json({
    total_papers: (paperCount as any)?.count || 0,
    total_analyses: (analysisCount as any)?.count || 0,
    total_dates: (dateCount as any)?.count || 0,
    areas: areaCounts || [],
  });
});

// GET /api/search?q=query - Full-text search
app.get("/api/search", async (c) => {
  const q = c.req.query("q") || "";
  if (q.length < 2) return c.json({ error: "Query too short" }, 400);

  const limit = Math.min(parseInt(c.req.query("limit") || "50"), 200);
  const offset = parseInt(c.req.query("offset") || "0");

  const { results } = await c.env.DB.prepare(`
    SELECT p.id as arxiv_id, p.source, p.title, p.authors, p.abstract,
           p.categories, p.primary_category, p.published, p.updated,
           p.entry_url, p.pdf_url, p.source_date,
           a.tldr, a.research_motivation, a.problem, a.method,
           a.primary_area, a.category, a.tags, a.reading_priority
    FROM papers p
    LEFT JOIN analyses a ON p.id = a.arxiv_id
    WHERE p.title LIKE ? OR p.abstract LIKE ?
       OR a.tldr LIKE ? OR a.research_motivation LIKE ? OR a.method LIKE ?
    ORDER BY p.source_date DESC
    LIMIT ? OFFSET ?
  `).bind(`%${q}%`, `%${q}%`, `%${q}%`, `%${q}%`, `%${q}%`, limit, offset).all();

  const parsed = results.map((r: any) => ({
    ...r,
    authors: safeJsonParse(r.authors),
    tags: safeJsonParse(r.tags),
    reading_priority: PRIORITY_MAP[r.reading_priority] || r.reading_priority || "unknown",
  }));

  return c.json({ query: q, results: parsed, limit, offset });
});

// POST /api/papers - Bulk upsert papers (protected by API token)
app.post("/api/papers", async (c) => {
  if (c.env.API_TOKEN) {
    const auth = c.req.header("Authorization");
    if (auth !== `Bearer ${c.env.API_TOKEN}`) {
      return c.json({ error: "Unauthorized" }, 401);
    }
  }

  const body = await c.req.json<{ papers: any[]; source_date: string }>();
  const { papers, source_date } = body;

  if (!papers || !Array.isArray(papers)) {
    return c.json({ error: "Invalid request: papers array required" }, 400);
  }

  let inserted = 0;
  const stmt = c.env.DB.prepare(`
    INSERT INTO papers
    (id, source, title, authors, abstract, categories, primary_category,
     published, updated, entry_url, pdf_url, source_date, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      source = excluded.source,
      title = excluded.title,
      authors = excluded.authors,
      abstract = excluded.abstract,
      categories = excluded.categories,
      primary_category = excluded.primary_category,
      published = excluded.published,
      updated = excluded.updated,
      entry_url = excluded.entry_url,
      pdf_url = excluded.pdf_url,
      source_date = excluded.source_date,
      fetched_at = excluded.fetched_at
  `);

  const batch = papers.slice(0, 100); // D1 batch limit
  for (const paper of batch) {
    const arxivId = paper.arxiv_id || paper.id || "";
    if (!arxivId) continue;
    const paperSourceDate = String(paper.source_date || paper.published || source_date || "").slice(0, 10);

    await stmt.bind(
      arxivId,
      paper.source || "arxiv",
      paper.title || "",
      JSON.stringify(paper.authors || []),
      paper.abstract || "",
      JSON.stringify(paper.categories || []),
      paper.primary_category || "",
      paper.published || "",
      paper.updated || "",
      paper.entry_url || "",
      paper.pdf_url || "",
      paperSourceDate,
      paper.fetched_at || new Date().toISOString(),
    ).run();
    inserted++;
  }

  return c.json({ inserted, total: papers.length });
});

// POST /api/analyses - Bulk upsert analyses (protected by API token)
app.post("/api/analyses", async (c) => {
  if (c.env.API_TOKEN) {
    const auth = c.req.header("Authorization");
    if (auth !== `Bearer ${c.env.API_TOKEN}`) {
      return c.json({ error: "Unauthorized" }, 401);
    }
  }

  const body = await c.req.json<{ analyses: any[] }>();
  const { analyses } = body;

  if (!analyses || !Array.isArray(analyses)) {
    return c.json({ error: "Invalid request: analyses array required" }, 400);
  }

  let inserted = 0;
  const stmt = c.env.DB.prepare(`
    INSERT OR IGNORE INTO analyses
    (arxiv_id, analysis_version, model, analyzed_at,
     tldr, research_motivation, problem, phenomenon_analysis, method,
     contributions, experiments, limitations,
     primary_area_en, primary_area, category, sub_area,
     tags, reading_priority, recommended_action, raw_response)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const batch = analyses.slice(0, 100);
  for (const analysis of batch) {
    const arxivId = analysis.arxiv_id || "";
    if (!arxivId) continue;

    const data = analysis.analysis || {};
    await stmt.bind(
      arxivId,
      analysis.analysis_version || "",
      analysis.model || "",
      analysis.analyzed_at || new Date().toISOString(),
      data.tldr || "",
      data.research_motivation || "",
      data.problem || "",
      data.phenomenon_analysis || "",
      data.method || "",
      JSON.stringify(data.contributions || []),
      data.experiments || "",
      JSON.stringify(data.limitations || []),
      data.primary_area_en || "",
      data.primary_area || "",
      data.category || "",
      data.sub_area || "",
      JSON.stringify(data.tags || []),
      data.reading_priority || "",
      data.recommended_action || "",
      analysis.raw_response || "",
    ).run();
    inserted++;
  }

  return c.json({ inserted, total: analyses.length });
});

function safeJsonParse(value: string | null | undefined): any {
  if (!value) return [];
  try {
    return JSON.parse(value);
  } catch {
    return [value];
  }
}

const SUBSCRIBED_CATEGORIES = ["cs.CV", "cs.AI", "cs.CL", "cs.LG"];

function pickDisplayCategory(categories: string[], primary: string): string {
  for (const cat of SUBSCRIBED_CATEGORIES) {
    if (categories.includes(cat)) return cat;
  }
  return primary;
}

function normalizePaperRow(r: any): any {
  const hasAnalysis = Boolean(r.analysis_id);
  const readingPriority = PRIORITY_MAP[r.reading_priority] || r.reading_priority || "unknown";
  const categories = safeJsonParse(r.categories);
  const displayCategory = pickDisplayCategory(categories, r.primary_category);
  return {
    arxiv_id: r.arxiv_id,
    source: r.source,
    title: r.title,
    authors: safeJsonParse(r.authors),
    abstract: r.abstract,
    categories,
    primary_category: r.primary_category,
    display_category: displayCategory,
    published: r.published,
    updated: r.updated,
    entry_url: r.entry_url,
    pdf_url: r.pdf_url,
    source_date: r.source_date,
    venue: r.venue,
    year: r.year,
    has_analysis: hasAnalysis,
    analysis: hasAnalysis ? {
      tldr: r.tldr || "",
      research_motivation: r.research_motivation || "",
      problem: r.problem || "",
      phenomenon_analysis: r.phenomenon_analysis || "",
      method: r.method || "",
      contributions: safeJsonParse(r.contributions),
      experiments: r.experiments || "",
      limitations: safeJsonParse(r.limitations),
      primary_area_en: r.primary_area_en || "",
      primary_area: r.primary_area || "",
      category: r.category || "",
      sub_area: r.sub_area || "",
      tags: safeJsonParse(r.tags),
      reading_priority: readingPriority,
      recommended_action: r.recommended_action || "",
      analysis_version: r.analysis_version || "",
      analyzed_at: r.analyzed_at || "",
    } : null,
  };
}

export default app;

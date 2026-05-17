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
  return c.json({ latest, dates: results });
});

// GET /api/papers?date=YYYY-MM-DD - Papers for a specific date
app.get("/api/papers", async (c) => {
  const date = c.req.query("date");
  const month = c.req.query("month");
  const id = c.req.query("id");
  const source = c.req.query("source") || "arxiv";

  if (id) {
    // Single paper lookup
    const paper = await c.env.DB.prepare("SELECT id as arxiv_id, source, title, authors, abstract, categories, primary_category, published, updated, entry_url, pdf_url, source_date, venue, year FROM papers WHERE id = ?").bind(id).first();
    if (!paper) return c.json({ error: "Paper not found" }, 404);
    const analysis = await c.env.DB.prepare("SELECT * FROM analyses WHERE arxiv_id = ?").bind(id).first();
    return c.json(normalizePaperRow({ ...paper, ...analysis, analysis_id: (analysis as any)?.arxiv_id || "" }));
  }

  let whereClause = source === "all" ? "WHERE 1=1" : "WHERE p.source = ?";
  let bindings: (string | number)[] = source === "all" ? [] : [source];

  if (date) {
    whereClause += " AND p.source_date = ?";
    bindings.push(date);
  } else if (month) {
    whereClause += " AND p.source_date LIKE ?";
    bindings.push(`${month}-%`);
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
  `).bind(...bindings).all();

  // Parse JSON fields and normalize priority values
  const parsed = results.map(normalizePaperRow);

  return c.json(parsed);
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
    INSERT OR IGNORE INTO papers
    (id, source, title, authors, abstract, categories, primary_category,
     published, updated, entry_url, pdf_url, source_date, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const batch = papers.slice(0, 100); // D1 batch limit
  for (const paper of batch) {
    const arxivId = paper.arxiv_id || paper.id || "";
    if (!arxivId) continue;

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
      source_date || "",
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
    return [];
  }
}

function normalizePaperRow(r: any): any {
  const hasAnalysis = Boolean(r.analysis_id);
  const readingPriority = PRIORITY_MAP[r.reading_priority] || r.reading_priority || "unknown";
  return {
    arxiv_id: r.arxiv_id,
    source: r.source,
    title: r.title,
    authors: safeJsonParse(r.authors),
    abstract: r.abstract,
    categories: safeJsonParse(r.categories),
    primary_category: r.primary_category,
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

window.DPRLiveSearch = (function () {
  const OPENALEX_API = 'https://api.openalex.org';
  const SOURCE_CACHE_KEY = 'dpr_openalex_source_cache_v1';
  const LAST_RESULT_KEY = 'dpr_live_search_last_v1';
  const SOURCE_CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 14;
  const STOPWORDS = new Set([
    'a',
    'an',
    'and',
    'are',
    'as',
    'at',
    'be',
    'by',
    'for',
    'from',
    'in',
    'into',
    'is',
    'it',
    'of',
    'on',
    'or',
    'the',
    'their',
    'this',
    'that',
    'to',
    'via',
    'with',
    'using',
    'used',
    'study',
    'studies',
    'based',
    'materials',
    'material',
  ]);
  const PRESET_SOURCE_IDS = {
    'acta materialia': {
      id: 'https://openalex.org/S64016596',
      display_name: 'Acta Materialia',
    },
    'scripta materialia': {
      id: 'https://openalex.org/S105962883',
      display_name: 'Scripta Materialia',
    },
    'computational materials science': {
      id: 'https://openalex.org/S26018076',
      display_name: 'Computational Materials Science',
    },
    'materials and design': {
      id: 'https://openalex.org/S8792693',
      display_name: 'Materials & Design',
    },
    'npj computational materials': {
      id: 'https://openalex.org/S4210232664',
      display_name: 'npj Computational Materials',
    },
    'journal of materials science and technology': {
      id: 'https://openalex.org/S135187643',
      display_name: 'Journal of Material Science and Technology',
    },
    'metallurgical and materials transactions a': {
      id: 'https://openalex.org/S165830345',
      display_name: 'Metallurgical and Materials Transactions A',
    },
    'journal of alloys and compounds': {
      id: 'https://openalex.org/S67716761',
      display_name: 'Journal of Alloys and Compounds',
    },
    intermetallics: {
      id: 'https://openalex.org/S38855548',
      display_name: 'Intermetallics',
    },
    'international journal of plasticity': {
      id: 'https://openalex.org/S10186584',
      display_name: 'International Journal of Plasticity',
    },
    'advanced functional materials': {
      id: 'https://openalex.org/S135204980',
      display_name: 'Advanced Functional Materials',
    },
    'advanced science': {
      id: 'https://openalex.org/S2737737698',
      display_name: 'Advanced Science',
    },
    'advanced materials': {
      id: 'https://openalex.org/S99352657',
      display_name: 'Advanced Materials',
    },
    'materials today': {
      id: 'https://openalex.org/S63322718',
      display_name: 'Materials Today',
    },
    'materials today advances': {
      id: 'https://openalex.org/S4210206330',
      display_name: 'Materials Today Advances',
    },
    'nature materials': {
      id: 'https://openalex.org/S103895331',
      display_name: 'Nature Materials',
    },
    nature: {
      id: 'https://openalex.org/S137773608',
      display_name: 'Nature',
    },
    science: {
      id: 'https://openalex.org/S3880285',
      display_name: 'Science',
    },
  };

  let overlay = null;
  let statusEl = null;
  let summaryEl = null;
  let resultsEl = null;
  let subStatusEl = null;
  let rerunBtn = null;
  let closeBtn = null;
  let lastRunOptions = null;

  const escapeHtml = (value) =>
    String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

  const normalizeText = (value) => String(value || '').trim();

  const normalizeCompare = (value) =>
    normalizeText(value)
      .toLowerCase()
      .replace(/&/g, ' and ')
      .replace(/[^a-z0-9]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

  const tokenize = (value) =>
    normalizeCompare(value)
      .split(' ')
      .filter((token) => token && token.length >= 3 && !STOPWORDS.has(token));

  const formatDate = (value) => {
    const text = normalizeText(value);
    if (!text) return '';
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  };

  const daysAgo = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 999;
    const diff = Date.now() - date.getTime();
    return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
  };

  const uniqueBy = (items, keyFn) => {
    const map = new Map();
    (Array.isArray(items) ? items : []).forEach((item) => {
      const key = keyFn(item);
      if (!key) return;
      if (!map.has(key)) {
        map.set(key, item);
      }
    });
    return Array.from(map.values());
  };

  const chunk = (items, size) => {
    const out = [];
    for (let i = 0; i < items.length; i += size) {
      out.push(items.slice(i, i + size));
    }
    return out;
  };

  const buildFromDate = (days) => {
    const safeDays = Math.max(1, parseInt(days, 10) || 10);
    const date = new Date();
    date.setDate(date.getDate() - safeDays + 1);
    return date.toISOString().slice(0, 10);
  };

  const journalTierWeight = (tier) => {
    if (tier === 'core') return 2.2;
    if (tier === 'secondary') return 1.1;
    return 0.5;
  };

  const reconstructAbstract = (invertedIndex) => {
    if (!invertedIndex || typeof invertedIndex !== 'object') return '';
    const words = [];
    Object.keys(invertedIndex).forEach((term) => {
      const positions = Array.isArray(invertedIndex[term]) ? invertedIndex[term] : [];
      positions.forEach((pos) => {
        words[pos] = term;
      });
    });
    return words
      .filter(Boolean)
      .join(' ')
      .replace(/\s+([,.;:!?])/g, '$1')
      .replace(/\(\s+/g, '(')
      .replace(/\s+\)/g, ')')
      .trim();
  };

  const cutText = (value, limit) => {
    const text = normalizeText(value);
    if (!text) return '';
    if (text.length <= limit) return text;
    return `${text.slice(0, limit - 1).trim()}...`;
  };

  const buildMeaningfulTerms = (query) => uniqueBy(tokenize(query), (item) => item);

  const termCoverage = (terms, haystack) => {
    if (!terms.length) return 0;
    const matched = terms.filter((term) => haystack.includes(term)).length;
    return matched / terms.length;
  };

  const pickWorkUrl = (work) => {
    const primaryLocation = work.primary_location || {};
    const landing = normalizeText(primaryLocation.landing_page_url);
    const doi = normalizeText(work.doi || (work.ids && work.ids.doi) || '');
    const openalex = normalizeText(work.id || (work.ids && work.ids.openalex) || '');
    return landing || doi || openalex || '';
  };

  const cacheGet = (key) => {
    try {
      const raw = window.localStorage && window.localStorage.getItem(key);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  const cacheSet = (key, value) => {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(key, JSON.stringify(value));
      }
    } catch {
      // ignore storage failures
    }
  };

  const injectStyles = () => {
    if (document.getElementById('dpr-live-search-style')) return;
    const style = document.createElement('style');
    style.id = 'dpr-live-search-style';
    style.textContent = `
      #dpr-live-search-overlay {
        position: fixed;
        inset: 0;
        z-index: 9999;
        background: rgba(10, 14, 23, 0.58);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 16px;
        box-sizing: border-box;
      }
      #dpr-live-search-panel {
        width: min(1180px, 100%);
        max-height: min(88vh, 920px);
        background: #fff;
        border-radius: 16px;
        box-shadow: 0 18px 64px rgba(15, 23, 42, 0.22);
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }
      .dpr-live-search-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        padding: 14px 18px;
        border-bottom: 1px solid #e5e7eb;
        background: #fbfdff;
      }
      .dpr-live-search-title {
        font-size: 18px;
        font-weight: 700;
        color: #0f172a;
      }
      .dpr-live-search-subtitle {
        margin-top: 4px;
        font-size: 12px;
        color: #64748b;
      }
      .dpr-live-search-actions {
        display: flex;
        gap: 8px;
        flex-shrink: 0;
      }
      .dpr-live-search-body {
        overflow: auto;
        padding: 16px 18px 20px;
      }
      .dpr-live-search-status {
        font-size: 13px;
        color: #334155;
        margin-bottom: 10px;
      }
      .dpr-live-search-substatus {
        font-size: 12px;
        color: #64748b;
        margin-bottom: 14px;
      }
      .dpr-live-search-summary-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 10px;
        margin-bottom: 14px;
      }
      .dpr-live-search-summary-card {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 10px 12px;
        background: #f8fbff;
      }
      .dpr-live-search-summary-label {
        font-size: 12px;
        color: #64748b;
        margin-bottom: 4px;
      }
      .dpr-live-search-summary-value {
        font-size: 16px;
        font-weight: 700;
        color: #0f172a;
      }
      .dpr-live-search-group {
        margin-bottom: 18px;
      }
      .dpr-live-search-group-title {
        font-size: 15px;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 10px;
      }
      .dpr-live-search-result {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 12px 14px;
        background: #fff;
        margin-bottom: 12px;
      }
      .dpr-live-search-result-title {
        font-size: 16px;
        font-weight: 700;
        line-height: 1.45;
      }
      .dpr-live-search-result-title a {
        color: #0f3f91;
        text-decoration: none;
      }
      .dpr-live-search-result-title a:hover {
        text-decoration: underline;
      }
      .dpr-live-search-meta {
        margin-top: 6px;
        font-size: 12px;
        color: #475569;
      }
      .dpr-live-search-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
      }
      .dpr-live-search-badge {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 600;
      }
      .dpr-live-search-badge.score {
        background: #e8f5e9;
        color: #1b5e20;
      }
      .dpr-live-search-badge.tag {
        background: #e8f1ff;
        color: #174ea6;
      }
      .dpr-live-search-badge.journal {
        background: #fff4e5;
        color: #b45309;
      }
      .dpr-live-search-evidence {
        margin-top: 10px;
        font-size: 12px;
        color: #1f2937;
        background: #f8fafc;
        border-radius: 10px;
        padding: 8px 10px;
      }
      .dpr-live-search-abstract {
        margin-top: 10px;
        font-size: 13px;
        color: #374151;
        line-height: 1.65;
      }
      .dpr-live-search-footer-links {
        display: flex;
        gap: 10px;
        margin-top: 10px;
        font-size: 12px;
      }
      .dpr-live-search-footer-links a {
        color: #0f3f91;
        text-decoration: none;
      }
      .dpr-live-search-footer-links a:hover {
        text-decoration: underline;
      }
      .dpr-live-search-empty {
        color: #64748b;
        font-size: 13px;
        padding: 12px 2px;
      }
      @media (max-width: 768px) {
        #dpr-live-search-overlay {
          padding: 8px;
        }
        #dpr-live-search-panel {
          max-height: 94vh;
        }
        .dpr-live-search-header {
          padding: 12px;
          align-items: flex-start;
        }
        .dpr-live-search-body {
          padding: 12px;
        }
        .dpr-live-search-title {
          font-size: 16px;
        }
      }
    `;
    document.head.appendChild(style);
  };

  const ensureOverlay = () => {
    injectStyles();
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'dpr-live-search-overlay';
    overlay.innerHTML = `
      <div id="dpr-live-search-panel">
        <div class="dpr-live-search-header">
          <div>
            <div class="dpr-live-search-title">实时论文检索</div>
            <div class="dpr-live-search-subtitle">直接查询期刊元数据与摘要，不依赖 PDF，也不走 GitHub Actions。</div>
          </div>
          <div class="dpr-live-search-actions">
            <button id="dpr-live-search-rerun-btn" class="arxiv-tool-btn" type="button">重新检索</button>
            <button id="dpr-live-search-close-btn" class="arxiv-tool-btn" type="button">关闭</button>
          </div>
        </div>
        <div class="dpr-live-search-body">
          <div id="dpr-live-search-status" class="dpr-live-search-status">准备就绪。</div>
          <div id="dpr-live-search-substatus" class="dpr-live-search-substatus"></div>
          <div id="dpr-live-search-summary"></div>
          <div id="dpr-live-search-results"></div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    statusEl = document.getElementById('dpr-live-search-status');
    subStatusEl = document.getElementById('dpr-live-search-substatus');
    summaryEl = document.getElementById('dpr-live-search-summary');
    resultsEl = document.getElementById('dpr-live-search-results');
    rerunBtn = document.getElementById('dpr-live-search-rerun-btn');
    closeBtn = document.getElementById('dpr-live-search-close-btn');

    if (closeBtn) {
      closeBtn.addEventListener('click', close);
    }
    if (rerunBtn) {
      rerunBtn.addEventListener('click', () => {
        if (lastRunOptions) {
          run(lastRunOptions);
        }
      });
    }
    overlay.addEventListener('mousedown', (event) => {
      if (event.target === overlay) {
        close();
      }
    });
  };

  const open = () => {
    ensureOverlay();
    overlay.style.display = 'flex';
  };

  const close = () => {
    if (!overlay) return;
    overlay.style.display = 'none';
  };

  const setStatus = (text, color) => {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.style.color = color || '#334155';
  };

  const setSubStatus = (text) => {
    if (!subStatusEl) return;
    subStatusEl.textContent = text || '';
  };

  const loadConfig = async (explicitConfig) => {
    if (explicitConfig && typeof explicitConfig === 'object' && Object.keys(explicitConfig).length) {
      return explicitConfig;
    }
    try {
      if (window.SubscriptionsManager && typeof window.SubscriptionsManager.getDraftConfig === 'function') {
        const draft = window.SubscriptionsManager.getDraftConfig();
        if (draft && Object.keys(draft).length) {
          return draft;
        }
      }
    } catch {
      // ignore
    }
    const response = await fetch('docs/config.yaml', { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`读取配置失败：HTTP ${response.status}`);
    }
    const raw = await response.text();
    if (!window.jsyaml || typeof window.jsyaml.load !== 'function') {
      throw new Error('缺少 YAML 解析能力');
    }
    const data = window.jsyaml.load(raw) || {};
    return typeof data === 'object' ? data : {};
  };

  const getActiveJournals = (config) => {
    const journalWatch = config && typeof config === 'object' ? config.journal_watch || {} : {};
    const scopes = Array.isArray(journalWatch.scopes) ? journalWatch.scopes : [];
    const journals = Array.isArray(journalWatch.journals) ? journalWatch.journals : [];
    const activeScopeKey = normalizeText(journalWatch.active_scope || 'all');
    const activeScope = scopes.find((item) => normalizeText(item.key) === activeScopeKey) || scopes[0];
    const tiers = new Set(
      Array.isArray(activeScope && activeScope.tiers) ? activeScope.tiers.map((item) => normalizeText(item)) : [],
    );
    return journals
      .map((item) => ({
        title: normalizeText(item && item.title),
        aliases: Array.isArray(item && item.aliases) ? item.aliases.map((alias) => normalizeText(alias)).filter(Boolean) : [],
        tier: normalizeText(item && item.tier) || 'core',
      }))
      .filter((item) => item.title && (!tiers.size || tiers.has(item.tier)));
  };

  const getEnabledProfiles = (config) => {
    const subscriptions = config && typeof config === 'object' ? config.subscriptions || {} : {};
    const profiles = Array.isArray(subscriptions.intent_profiles) ? subscriptions.intent_profiles : [];
    return profiles
      .map((profile) => ({
        tag: normalizeText(profile && profile.tag) || 'untagged',
        description: normalizeText(profile && profile.description),
        keywords: Array.isArray(profile && profile.keywords)
          ? profile.keywords
              .map((item) => ({
                keyword: normalizeText(item && item.keyword),
                query: normalizeText(item && item.query),
                keyword_cn: normalizeText(item && item.keyword_cn),
              }))
              .filter((item) => item.keyword)
          : [],
        intent_queries: Array.isArray(profile && profile.intent_queries)
          ? profile.intent_queries
              .map((item) => ({
                query: normalizeText(item && item.query),
                query_cn: normalizeText(item && item.query_cn),
                enabled: item && item.enabled !== false,
              }))
              .filter((item) => item.query && item.enabled)
          : [],
        enabled: profile && profile.enabled !== false,
      }))
      .filter((profile) => profile.enabled);
  };

  const loadSourceCache = () => {
    const cached = cacheGet(SOURCE_CACHE_KEY);
    return cached && typeof cached === 'object' ? cached : {};
  };

  const saveSourceCache = (cache) => {
    cacheSet(SOURCE_CACHE_KEY, cache);
  };

  const pickSourceCandidate = (queryName, aliases, results) => {
    const normalizedTargets = uniqueBy(
      [queryName]
        .concat(Array.isArray(aliases) ? aliases : [])
        .map((item) => normalizeCompare(item))
        .filter(Boolean),
      (item) => item,
    );
    const exact = results.find((item) => normalizedTargets.includes(normalizeCompare(item.display_name)));
    if (exact) return exact;
    const includes = results.find((item) => {
      const name = normalizeCompare(item.display_name);
      return normalizedTargets.some((target) => target && (name.includes(target) || target.includes(name)));
    });
    return includes || results[0] || null;
  };

  const resolveSourceId = async (journal) => {
    const title = normalizeText(journal && journal.title);
    if (!title) return null;
    const key = normalizeCompare(title);
    const preset = PRESET_SOURCE_IDS[key];
    if (preset && preset.id) {
      return {
        id: preset.id,
        display_name: normalizeText(preset.display_name) || title,
        updated_at: Date.now(),
        tier: normalizeText(journal.tier) || 'core',
        title,
      };
    }
    const cache = loadSourceCache();
    const cached = cache[key];
    if (cached && cached.id && cached.updated_at && Date.now() - cached.updated_at < SOURCE_CACHE_TTL_MS) {
      return cached;
    }

    const response = await fetch(
      `${OPENALEX_API}/sources?search=${encodeURIComponent(title)}&per-page=8&select=id,display_name,host_organization_name`,
      { cache: 'no-store' },
    );
    if (!response.ok) {
      throw new Error(`查询期刊源失败：${title} (HTTP ${response.status})`);
    }
    const data = await response.json();
    const results = Array.isArray(data && data.results) ? data.results : [];
    const candidate = pickSourceCandidate(title, journal.aliases, results);
    if (!candidate || !candidate.id) {
      return null;
    }
    const resolved = {
      id: candidate.id,
      display_name: normalizeText(candidate.display_name) || title,
      updated_at: Date.now(),
      tier: normalizeText(journal.tier) || 'core',
      title,
    };
    cache[key] = resolved;
    saveSourceCache(cache);
    return resolved;
  };

  const resolveAllSourceIds = async (journals) => {
    const settled = await Promise.allSettled(
      (Array.isArray(journals) ? journals : []).map((journal) => resolveSourceId(journal)),
    );
    return settled
      .map((entry) => (entry.status === 'fulfilled' ? entry.value : null))
      .filter((item) => item && item.id);
  };

  const openAlexFetchJson = async (url) => {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
      },
    });
    if (!response.ok) {
      throw new Error(`OpenAlex 请求失败：HTTP ${response.status}`);
    }
    return response.json();
  };

  const buildSearchQueries = (profile, breadth) => {
    const explicit = (Array.isArray(profile.intent_queries) ? profile.intent_queries : [])
      .map((item) => normalizeText(item.query))
      .filter(Boolean);
    const keywordQueries = (Array.isArray(profile.keywords) ? profile.keywords : [])
      .map((item) => normalizeText(item.query || item.keyword))
      .filter(Boolean);
    const queries = uniqueBy(explicit.concat(keywordQueries), (item) => normalizeCompare(item));
    const limit = breadth === 'expanded' ? 6 : 4;
    return queries.slice(0, limit);
  };

  const selectFields = [
    'id',
    'display_name',
    'publication_date',
    'doi',
    'primary_location',
    'ids',
    'authorships',
    'abstract_inverted_index',
    'cited_by_count',
    'type',
  ].join(',');

  const fetchWorksForQuery = async (query, sourceIds, options) => {
    const idBatches = chunk(sourceIds, 6);
    const settled = await Promise.allSettled(
      idBatches.map((batch) => {
        const url =
          `${OPENALEX_API}/works?search=${encodeURIComponent(query)}` +
          `&filter=from_publication_date:${options.fromDate},primary_location.source.id:${encodeURIComponent(
            batch.join('|'),
          )}` +
          `&per-page=${options.perPage}` +
          `&select=${selectFields}`;
        return openAlexFetchJson(url);
      }),
    );
    const merged = [];
    settled.forEach((entry) => {
      if (entry.status !== 'fulfilled') return;
      const results = Array.isArray(entry.value && entry.value.results) ? entry.value.results : [];
      results.forEach((work, index) => {
        merged.push({
          ...work,
          __query: query,
          __queryRank: index,
        });
      });
    });
    return merged;
  };

  const fetchRecentWorks = async (sourceIds, options) => {
    const idBatches = chunk(sourceIds, 6);
    const settled = await Promise.allSettled(
      idBatches.map((batch) => {
        const url =
          `${OPENALEX_API}/works?filter=from_publication_date:${options.fromDate},primary_location.source.id:${encodeURIComponent(
            batch.join('|'),
          )}` +
          `&sort=publication_date:desc&per-page=${options.recentPerBatch}` +
          `&select=${selectFields}`;
        return openAlexFetchJson(url);
      }),
    );
    const merged = [];
    settled.forEach((entry) => {
      if (entry.status !== 'fulfilled') return;
      const results = Array.isArray(entry.value && entry.value.results) ? entry.value.results : [];
      results.forEach((work, index) => {
        merged.push({
          ...work,
          __query: '',
          __queryRank: index,
        });
      });
    });
    return merged;
  };

  const prepareWorks = (works, sourceMap) => {
    return uniqueBy(
      (Array.isArray(works) ? works : []).map((work) => {
        const source = work && work.primary_location && work.primary_location.source
          ? work.primary_location.source
          : {};
        const sourceId = normalizeText(source && source.id);
        const sourceMeta = sourceMap.get(sourceId) || {};
        const title = normalizeText(work && work.display_name);
        const abstract = reconstructAbstract(work && work.abstract_inverted_index);
        const authors = Array.isArray(work && work.authorships)
          ? work.authorships
              .map((item) => normalizeText(item && item.author && item.author.display_name))
              .filter(Boolean)
          : [];
        const journalTitle = normalizeText(source && source.display_name) || normalizeText(sourceMeta.display_name);
        return {
          id: normalizeText(work && work.id),
          title,
          abstract,
          publication_date: normalizeText(work && work.publication_date),
          url: pickWorkUrl(work),
          doi: normalizeText(work && (work.doi || (work.ids && work.ids.doi))),
          journal: journalTitle,
          journalTier: normalizeText(sourceMeta.tier) || 'core',
          sourceId,
          authors,
          citedByCount: parseInt(work && work.cited_by_count, 10) || 0,
          query: normalizeText(work && work.__query),
          queryRank: parseInt(work && work.__queryRank, 10) || 0,
        };
      }),
      (item) => item.doi || item.id || `${item.title}__${item.publication_date}`,
    );
  };

  const scoreWorkForProfile = (work, profile) => {
    const title = normalizeCompare(work.title);
    const abstract = normalizeCompare(work.abstract);
    const journal = normalizeCompare(work.journal);
    const text = `${title} ${abstract} ${journal}`;
    let score = 0;
    const evidence = [];

    (Array.isArray(profile.keywords) ? profile.keywords : []).forEach((item) => {
      const keyword = normalizeCompare(item.keyword);
      if (!keyword) return;
      const titleExact = title.includes(keyword);
      const abstractExact = !titleExact && abstract.includes(keyword);
      if (titleExact) {
        score += 12;
        evidence.push(`标题命中关键词：${item.keyword}`);
        return;
      }
      if (abstractExact) {
        score += 7;
        evidence.push(`摘要命中关键词：${item.keyword}`);
        return;
      }
      const keywordTerms = buildMeaningfulTerms(item.query || item.keyword);
      const coverage = termCoverage(keywordTerms, text);
      if (coverage >= 0.5) {
        score += 6 * coverage;
        evidence.push(`关键词相关度：${item.keyword}`);
      }
    });

    (Array.isArray(profile.intent_queries) ? profile.intent_queries : []).forEach((item) => {
      const query = normalizeText(item.query);
      if (!query) return;
      const queryNormalized = normalizeCompare(query);
      const queryTerms = buildMeaningfulTerms(query);
      if (queryNormalized && title.includes(queryNormalized)) {
        score += 12;
        evidence.push(`标题高度贴近意图：${cutText(query, 64)}`);
        return;
      }
      const coverage = termCoverage(queryTerms, text);
      if (coverage >= 0.45) {
        score += 10 * coverage;
        evidence.push(`意图匹配：${cutText(query, 64)}`);
      }
    });

    if (work.query) {
      const queryTerms = buildMeaningfulTerms(work.query);
      const coverage = termCoverage(queryTerms, text);
      score += Math.max(0, 4 * coverage);
      if (coverage >= 0.5) {
        evidence.push(`检索召回词：${cutText(work.query, 56)}`);
      }
      score += Math.max(0, 2 - work.queryRank * 0.15);
    }

    score += journalTierWeight(work.journalTier);
    score += Math.max(0, 2.2 - daysAgo(work.publication_date) / 12);
    score += Math.min(1.8, Math.log10((work.citedByCount || 0) + 1));

    return {
      score: Number(score.toFixed(1)),
      evidence: uniqueBy(evidence, (item) => item).slice(0, 4),
    };
  };

  const rankWorks = (works, profiles) => {
    return (Array.isArray(works) ? works : [])
      .map((work) => {
        let best = null;
        (Array.isArray(profiles) ? profiles : []).forEach((profile) => {
          const current = scoreWorkForProfile(work, profile);
          if (!best || current.score > best.score) {
            best = {
              profileTag: profile.tag,
              profileDescription: profile.description,
              score: current.score,
              evidence: current.evidence,
            };
          }
        });
        return best
          ? {
              ...work,
              match: best,
            }
          : null;
      })
      .filter(Boolean)
      .sort((a, b) => {
        if (b.match.score !== a.match.score) return b.match.score - a.match.score;
        return new Date(b.publication_date).getTime() - new Date(a.publication_date).getTime();
      });
  };

  const renderSummary = (meta) => {
    if (!summaryEl) return;
    const cards = [
      { label: '检索窗口', value: `近 ${meta.days} 天` },
      { label: '期刊数量', value: `${meta.journalCount}` },
      { label: '候选论文', value: `${meta.candidateCount}` },
      { label: '最终结果', value: `${meta.resultCount}` },
      { label: '命中专题', value: `${meta.profileCount}` },
    ];
    summaryEl.innerHTML = `
      <div class="dpr-live-search-summary-grid">
        ${cards
          .map(
            (item) => `
              <div class="dpr-live-search-summary-card">
                <div class="dpr-live-search-summary-label">${escapeHtml(item.label)}</div>
                <div class="dpr-live-search-summary-value">${escapeHtml(item.value)}</div>
              </div>
            `,
          )
          .join('')}
      </div>
    `;
  };

  const renderResults = (items) => {
    if (!resultsEl) return;
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      resultsEl.innerHTML = '<div class="dpr-live-search-empty">没有找到足够相关的论文。你可以把时间窗口放宽到 30 天，或补充更具体的检索词。</div>';
      return;
    }

    const groups = new Map();
    list.forEach((item) => {
      const tag = normalizeText(item.match && item.match.profileTag) || '未分组';
      if (!groups.has(tag)) {
        groups.set(tag, []);
      }
      groups.get(tag).push(item);
    });

    const html = Array.from(groups.entries())
      .map(([tag, groupItems]) => {
        const cards = groupItems
          .map((item) => {
            const links = [];
            if (item.url) {
              links.push(`<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">打开论文</a>`);
            }
            if (item.doi) {
              links.push(`<a href="${escapeHtml(item.doi)}" target="_blank" rel="noopener">DOI</a>`);
            }
            if (item.id) {
              links.push(`<a href="${escapeHtml(item.id)}" target="_blank" rel="noopener">OpenAlex</a>`);
            }
            return `
              <div class="dpr-live-search-result">
                <div class="dpr-live-search-result-title">
                  <a href="${escapeHtml(item.url || item.doi || item.id)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
                </div>
                <div class="dpr-live-search-meta">
                  ${escapeHtml(item.journal)} · ${escapeHtml(formatDate(item.publication_date))} · ${escapeHtml(
                    cutText((item.authors || []).slice(0, 4).join(', '), 120),
                  )}
                </div>
                <div class="dpr-live-search-badges">
                  <span class="dpr-live-search-badge score">评分 ${escapeHtml(item.match.score)}</span>
                  <span class="dpr-live-search-badge tag">${escapeHtml(item.match.profileTag)}</span>
                  <span class="dpr-live-search-badge journal">${escapeHtml(item.journalTier || 'core')}</span>
                </div>
                <div class="dpr-live-search-evidence">
                  <strong>命中依据：</strong> ${escapeHtml((item.match.evidence || []).join('； ') || '标题 / 摘要与当前专题高度相关')}
                </div>
                <div class="dpr-live-search-abstract">${escapeHtml(cutText(item.abstract || '该记录暂未提供摘要，建议直接打开 DOI 或期刊落地页查看。', 420))}</div>
                <div class="dpr-live-search-footer-links">${links.join('')}</div>
              </div>
            `;
          })
          .join('');
        return `
          <div class="dpr-live-search-group">
            <div class="dpr-live-search-group-title">${escapeHtml(tag)} (${groupItems.length})</div>
            ${cards}
          </div>
        `;
      })
      .join('');
    resultsEl.innerHTML = html;
  };

  const renderCachedLastResult = () => {
    const cached = cacheGet(LAST_RESULT_KEY);
    if (!cached || !cached.meta || !Array.isArray(cached.items)) return false;
    renderSummary(cached.meta);
    renderResults(cached.items);
    setStatus('已加载上一次实时检索结果。', '#334155');
    setSubStatus(cached.meta.generatedAt ? `上次检索时间：${cached.meta.generatedAt}` : '');
    return true;
  };

  const run = async (options) => {
    ensureOverlay();
    open();
    lastRunOptions = { ...(options || {}) };
    const days = Math.max(1, parseInt(options && options.days, 10) || 10);
    const breadth = normalizeText(options && options.breadth) || 'focus';
    const perQuery = breadth === 'expanded' ? 14 : 8;
    const recentPerBatch = breadth === 'expanded' ? 26 : 14;

    setStatus('正在连接学术元数据源并执行实时检索...', '#1565c0');
    setSubStatus('本次检索将直接读取期刊元数据与摘要，不走 GitHub Actions。');
    if (summaryEl) summaryEl.innerHTML = '';
    if (resultsEl) resultsEl.innerHTML = '<div class="dpr-live-search-empty">正在整理候选论文，请稍候...</div>';

    try {
      const config = await loadConfig(options && options.config);
      const profiles = getEnabledProfiles(config);
      const journals = getActiveJournals(config);
      if (!profiles.length) {
        throw new Error('没有可用的启用专题，请先在后台新增并保存至少一个专题。');
      }
      if (!journals.length) {
        throw new Error('当前期刊池为空，请先检查期刊层级配置。');
      }

      setSubStatus(`正在解析 ${journals.length} 本期刊源，并按 ${profiles.length} 个专题检索近 ${days} 天论文...`);
      const resolvedSources = await resolveAllSourceIds(journals);
      if (!resolvedSources.length) {
        throw new Error('没有解析到可用的期刊源 ID。');
      }
      const sourceMap = new Map(resolvedSources.map((item) => [item.id, item]));
      const sourceIds = resolvedSources.map((item) => item.id);

      const queryTasks = [];
      profiles.forEach((profile) => {
        buildSearchQueries(profile, breadth).forEach((query) => {
          queryTasks.push(
            fetchWorksForQuery(query, sourceIds, {
              fromDate: buildFromDate(days),
              perPage: perQuery,
            }),
          );
        });
      });

      const settled = await Promise.allSettled(queryTasks);
      let works = [];
      settled.forEach((entry) => {
        if (entry.status === 'fulfilled') {
          works = works.concat(entry.value || []);
        }
      });

      const preparedFromQueries = prepareWorks(works, sourceMap);
      let candidates = preparedFromQueries;
      if (candidates.length < 18) {
        setSubStatus(`专题检索候选较少，正在补充近 ${days} 天期刊最新论文...`);
        const recentWorks = await fetchRecentWorks(sourceIds, {
          fromDate: buildFromDate(days),
          recentPerBatch,
        });
        candidates = prepareWorks(works.concat(recentWorks), sourceMap);
      }

      const rankedAll = rankWorks(candidates, profiles);
      let ranked = rankedAll
        .filter((item) => item.match && item.match.score >= 6)
        .slice(0, breadth === 'expanded' ? 60 : 36);
      if (ranked.length < 12) {
        ranked = rankedAll
          .filter((item) => item.match && item.match.score >= 4)
          .slice(0, breadth === 'expanded' ? 48 : 24);
      }

      const generatedAt = new Date().toLocaleString('zh-CN', {
        hour12: false,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      const meta = {
        days,
        journalCount: journals.length,
        candidateCount: candidates.length,
        resultCount: ranked.length,
        profileCount: profiles.length,
        generatedAt,
      };
      renderSummary(meta);
      renderResults(ranked);
      setStatus('实时检索完成。', '#0f766e');
      setSubStatus(`本次共整理 ${candidates.length} 条候选，已按你的专题和期刊层级完成本地排序。`);
      cacheSet(LAST_RESULT_KEY, { meta, items: ranked });
      return { meta, items: ranked };
    } catch (error) {
      console.error(error);
      setStatus(`实时检索失败：${error && error.message ? error.message : error}`, '#c00');
      setSubStatus('如果你刚改过专题但还没保存，也可以直接重试；本次实时检索本身不依赖 GitHub Actions。');
      if (!renderCachedLastResult() && resultsEl) {
        resultsEl.innerHTML = '<div class="dpr-live-search-empty">这次检索没有成功返回结果。你可以稍后重试，或把时间窗口放大到 30 天。</div>';
      }
      throw error;
    }
  };
  return {
    open,
    close,
    run,
    renderCachedLastResult,
  };
})();

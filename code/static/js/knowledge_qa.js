const QA_THEME_KEY = 'liternexus-qa-theme';
const QA_SITE_THEME_KEY = 'liternexus-theme';
const QA_LEGACY_THEME_KEY = 'scholarflow-theme';

const qaState = {
    scope: 'library',
    collectionId: '',
    collections: [],
    summary: null,
    sessions: [],
    sessionId: '',
    sessionTitle: '',
    settings: null,
    busy: false,
    settingsReturnFocus: null,
    settingsCloseTimer: 0,
    composerResizeFrame: 0,
};

document.addEventListener('DOMContentLoaded', async () => {
    initializeQaTheme();
    bindQaEvents();
    resizeQaComposer();
    await Promise.all([loadQaSources(), loadQaSettings(), loadQaSessions()]);
    restoreQaStateFromUrl();
    window.addEventListener('popstate', restoreQaStateFromUrl);
});

function updateQaUrl(changes = {}, replace = true) {
    const url = new URL(window.location.href);
    Object.entries(changes).forEach(([key, value]) => {
        const normalized = String(value ?? '').trim();
        if (normalized) url.searchParams.set(key, normalized);
        else url.searchParams.delete(key);
    });
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({}, '', `${url.pathname}${url.search}${url.hash}`);
}

function restoreQaStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get('session') || '';
    if (sessionId) {
        const button = document.querySelector(`.qa-history-item[data-session-id="${CSS.escape(sessionId)}"]`);
        if (button && qaState.sessionId !== sessionId) {
            button.dataset.restoreState = '1';
            button.click();
        }
        return;
    }
    const collectionId = params.get('collection') || '';
    const scope = params.get('scope') === 'collection' && collectionId ? 'collection' : 'library';
    qaState.scope = scope;
    qaState.collectionId = scope === 'collection' ? collectionId : '';
    qaState.sessionId = '';
    qaState.sessionTitle = '';
    const libraryButton = document.querySelector('.qa-source-option[data-scope="library"]');
    libraryButton?.classList.toggle('active', scope === 'library');
    libraryButton?.setAttribute('aria-checked', scope === 'library' ? 'true' : 'false');
    renderQaCollections();
    renderQaHistory();
    updateQaSourceDisplay();
    updateQaUrl({ scope, collection: qaState.collectionId, session: '' }, true);
}

function initializeQaTheme() {
    const themeToggle = document.getElementById('theme-toggle');
    const storedTheme = localStorage.getItem(QA_THEME_KEY)
        || localStorage.getItem(QA_SITE_THEME_KEY)
        || localStorage.getItem(QA_LEGACY_THEME_KEY);
    applyQaTheme(storedTheme === 'night' ? 'night' : 'day');
    themeToggle?.addEventListener('click', () => {
        applyQaTheme(document.documentElement.getAttribute('data-theme') === 'night' ? 'day' : 'night');
    });
}

function applyQaTheme(theme) {
    const normalized = theme === 'night' ? 'night' : 'day';
    const toggle = document.getElementById('theme-toggle');
    const text = toggle?.querySelector('.theme-toggle-text');
    const icon = toggle?.querySelector('.qa-theme-icon');
    document.documentElement.setAttribute('data-theme', normalized);
    localStorage.setItem(QA_THEME_KEY, normalized);
    document.getElementById('theme-color-meta')?.setAttribute(
        'content',
        normalized === 'night' ? '#091624' : '#eef6fc',
    );
    if (!toggle) return;
    const isNight = normalized === 'night';
    const label = isNight ? '切换到日览模式' : '切换到夜览模式';
    toggle.setAttribute('aria-pressed', isNight ? 'true' : 'false');
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
    if (icon) icon.className = `fas fa-${isNight ? 'sun' : 'moon'} qa-theme-icon`;
    if (text) text.textContent = isNight ? '夜览模式' : '日览模式';
}

function bindQaEvents() {
    document.querySelector('.qa-source-option[data-scope="library"]')?.addEventListener('click', () => setQaScope('library'));
    document.getElementById('qa-collection-list')?.addEventListener('click', event => {
        const button = event.target.closest('.qa-collection-option');
        if (button) setQaScope('collection', button.dataset.collectionId || '');
    });
    document.getElementById('qa-scope-trigger')?.addEventListener('click', toggleQaScopeMenu);
    document.addEventListener('click', event => {
        const picker = document.getElementById('qa-scope-picker');
        if (picker && !picker.contains(event.target)) closeQaScopeMenu();
    });
    document.getElementById('qa-composer')?.addEventListener('submit', handleQaSubmit);
    document.getElementById('qa-question')?.addEventListener('input', resizeQaComposer);
    document.getElementById('qa-question')?.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            document.getElementById('qa-composer')?.requestSubmit();
        }
    });
    document.querySelectorAll('.qa-suggestion').forEach(button => {
        button.addEventListener('click', () => {
            const input = document.getElementById('qa-question');
            if (!input) return;
            input.value = button.dataset.question || '';
            resizeQaComposer();
            input.focus();
        });
    });
    document.getElementById('qa-new-chat')?.addEventListener('click', startNewQaConversation);
    document.getElementById('qa-clear-chat')?.addEventListener('click', deleteCurrentQaConversation);
    document.getElementById('qa-history-list')?.addEventListener('click', handleHistoryClick);
    document.getElementById('qa-history-list')?.addEventListener('click', handleHistoryRenameClick);
    document.getElementById('qa-history-list')?.addEventListener('click', handleHistoryDeleteClick);
    document.getElementById('qa-open-settings')?.addEventListener('click', openQaSettings);
    document.getElementById('qa-close-settings')?.addEventListener('click', closeQaSettings);
    document.getElementById('qa-settings-backdrop')?.addEventListener('click', event => {
        if (event.target.id === 'qa-settings-backdrop') closeQaSettings();
    });
    document.getElementById('qa-settings-form')?.addEventListener('submit', saveQaSettings);
    document.getElementById('qa-test-model')?.addEventListener('click', testQaModel);
    document.getElementById('qa-build-index')?.addEventListener('click', buildQaIndex);
    document.getElementById('qa-deploy-reranker')?.addEventListener('click', deployQaReranker);
    document.getElementById('qa-retrieval-mode')?.addEventListener('change', updateEmbeddingFields);
    document.getElementById('qa-reranker-enabled')?.addEventListener('change', updateRerankerFields);
    document.getElementById('qa-top-k')?.addEventListener('input', event => {
        const mirror = document.getElementById('qa-reranker-final-k');
        if (mirror) mirror.value = event.target.value;
    });
    document.getElementById('qa-reranker-final-k')?.addEventListener('input', event => {
        const source = document.getElementById('qa-top-k');
        if (source) source.value = event.target.value;
    });
    document.querySelectorAll('.qa-secret-toggle').forEach(button => {
        button.addEventListener('click', () => toggleQaSecret(button));
    });
    document.addEventListener('keydown', handleQaDocumentKeydown);
}

function toggleQaSecret(button) {
    const input = document.getElementById(button.dataset.target || '');
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    const label = show ? '隐藏访问密钥' : '显示访问密钥';
    button.setAttribute('aria-label', label);
    button.setAttribute('title', label);
    button.innerHTML = `<i class="fas fa-${show ? 'eye-slash' : 'eye'}" aria-hidden="true"></i>`;
}

async function apiRequest(url, options = {}) {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
        const error = new Error(payload.error || `请求失败（HTTP ${response.status}）`);
        error.code = payload.code || '';
        throw error;
    }
    return payload;
}

async function loadQaSources() {
    try {
        const [summary, collections] = await Promise.all([
            apiRequest('/api/library/summary'),
            apiRequest('/api/library/collections'),
        ]);
        qaState.summary = summary;
        qaState.collections = Array.isArray(collections.data) ? collections.data : [];
        renderQaCollections();
        updateQaSourceDisplay();
    } catch (error) {
        const list = document.getElementById('qa-collection-list');
        const count = document.getElementById('qa-library-count');
        if (list) list.innerHTML = '<div class="qa-source-empty">暂时无法读取文献主题库</div>';
        if (count) count.textContent = '数据状态不可用';
    }
}

async function loadQaSettings() {
    try {
        qaState.settings = await apiRequest('/api/knowledge-qa/settings');
        fillQaSettingsForm(qaState.settings);
        updateQaModelStatus();
        await Promise.all([loadQaIndexStatus(), loadQaRerankerStatus()]);
    } catch (error) {
        showQaToast(error.message, 'error');
    }
}

async function loadQaSessions() {
    try {
        const payload = await apiRequest('/api/knowledge-qa/sessions');
        qaState.sessions = Array.isArray(payload.data) ? payload.data : [];
        if (qaState.sessionId) {
            const current = qaState.sessions.find(session => session.session_id === qaState.sessionId);
            if (current) qaState.sessionTitle = current.title || qaState.sessionTitle;
        }
        renderQaHistory();
        updateQaSourceDisplay();
    } catch (error) {
        showQaToast(error.message, 'error');
    }
}

function renderQaCollections() {
    const list = document.getElementById('qa-collection-list');
    const collectionCount = document.getElementById('qa-collection-count');
    const libraryCount = document.getElementById('qa-library-count');
    const libraryButton = document.querySelector('.qa-source-option[data-scope="library"]');
    const libraryActive = qaState.scope === 'library';
    libraryButton?.classList.toggle('active', libraryActive);
    libraryButton?.setAttribute('aria-checked', libraryActive ? 'true' : 'false');
    if (libraryCount) libraryCount.textContent = `${Number(qaState.summary?.papers || 0)} 篇文献`;
    if (collectionCount) collectionCount.textContent = String(qaState.collections.length);
    if (!list) return;
    if (!qaState.collections.length) {
        list.innerHTML = '<div class="qa-source-empty">暂无文献主题库</div>';
        return;
    }
    list.innerHTML = qaState.collections.map(collection => {
        const active = qaState.scope === 'collection' && qaState.collectionId === collection.collection_id;
        return `<button type="button" class="qa-collection-option${active ? ' active' : ''}" data-collection-id="${escapeQaHtml(collection.collection_id)}" role="menuitemradio" aria-checked="${active}">
            <span class="qa-collection-type qa-collection-type-${escapeQaHtml(collection.collection_type || 'custom')}">${escapeQaHtml(getQaCollectionTypeLabel(collection.collection_type))}</span>
            <span class="qa-source-option-copy"><strong>${escapeQaHtml(collection.name)}</strong><small>${Number(collection.paper_count || 0)} 篇文献</small></span>
        </button>`;
    }).join('');
}

function renderQaHistory() {
    const list = document.getElementById('qa-history-list');
    if (!list) return;
    document.getElementById('qa-new-chat')?.classList.toggle('active', !qaState.sessionId);
    const sessions = qaState.sessions.map(session => {
        let scope = {};
        try { scope = JSON.parse(session.scope_json || '{}'); } catch (_) { scope = {}; }
        const scopeLabel = session.scope_type === 'collection' ? (scope.scope_label || '文献主题库') : '全库文献';
        const updatedAt = formatQaHistoryTime(session.updated_at);
        const messages = Number(session.message_count || 0);
        const active = session.session_id === qaState.sessionId;
        return `<div class="qa-history-row${active ? ' active' : ''}">
            <button type="button" class="qa-history-item${active ? ' active' : ''}" data-session-id="${escapeQaHtml(session.session_id)}" title="打开并继续此问答"${active ? ' aria-current="true"' : ''}>
                <i class="far fa-message" aria-hidden="true"></i>
                <span class="qa-history-copy"><strong>${escapeQaHtml(session.title || '未命名问答')}</strong><small>${escapeQaHtml(scopeLabel)} · ${messages} 条消息${updatedAt ? ` · ${escapeQaHtml(updatedAt)}` : ''}</small></span>
            </button>
            <span class="qa-history-actions">
                <button type="button" class="qa-history-rename" data-rename-session-id="${escapeQaHtml(session.session_id)}" data-session-title="${escapeQaHtml(session.title || '未命名问答')}" title="修改对话名称" aria-label="修改对话名称：${escapeQaHtml(session.title || '未命名问答')}">
                    <i class="fas fa-pen" aria-hidden="true"></i>
                </button>
                <button type="button" class="qa-history-delete" data-delete-session-id="${escapeQaHtml(session.session_id)}" data-session-title="${escapeQaHtml(session.title || '未命名问答')}" title="删除此问答" aria-label="删除问答：${escapeQaHtml(session.title || '未命名问答')}">
                    <i class="fas fa-trash-can" aria-hidden="true"></i>
                </button>
            </span>
        </div>`;
    }).join('');
    list.innerHTML = sessions || '<div class="qa-history-empty">暂无历史对话</div>';
}

function formatQaHistoryTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ');
    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();
    return sameDay
        ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function toggleQaScopeMenu() {
    const menu = document.getElementById('qa-scope-menu');
    const trigger = document.getElementById('qa-scope-trigger');
    if (!menu || !trigger) return;
    if (!menu.hidden) {
        closeQaScopeMenu();
        return;
    }
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    const selected = menu.querySelector('[aria-checked="true"]');
    window.requestAnimationFrame(() => selected?.focus({ preventScroll: true }));
}

function closeQaScopeMenu(returnFocus = false) {
    const menu = document.getElementById('qa-scope-menu');
    const trigger = document.getElementById('qa-scope-trigger');
    if (!menu || !trigger || menu.hidden) return;
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) trigger.focus({ preventScroll: true });
}

function setQaScope(scope, collectionId = '') {
    if (qaState.busy) return;
    qaState.scope = scope === 'collection' ? 'collection' : 'library';
    qaState.collectionId = qaState.scope === 'collection' ? collectionId : '';
    qaState.sessionId = '';
    qaState.sessionTitle = '';
    resetQaMessages();
    const libraryButton = document.querySelector('.qa-source-option[data-scope="library"]');
    libraryButton?.classList.toggle('active', qaState.scope === 'library');
    libraryButton?.setAttribute('aria-checked', qaState.scope === 'library' ? 'true' : 'false');
    renderQaCollections();
    renderQaHistory();
    updateQaSourceDisplay();
    closeQaScopeMenu();
    updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: '' }, false);
}

function getSelectedQaCollection() {
    return qaState.collections.find(collection => collection.collection_id === qaState.collectionId) || null;
}

function getQaCollectionTypeLabel(type) {
    return { material: '材料', method: '方法', project: '项目', custom: '其它' }[type] || '其它';
}

function updateQaSourceDisplay() {
    const collection = getSelectedQaCollection();
    const isCollection = qaState.scope === 'collection';
    const title = isCollection ? (collection?.name || '未选择主题库') : '全库文献';
    const count = isCollection ? Number(collection?.paper_count || 0) : Number(qaState.summary?.papers || 0);
    const chatTitle = document.getElementById('qa-chat-title');
    const eyebrow = document.getElementById('qa-chat-eyebrow');
    if (chatTitle) chatTitle.textContent = qaState.sessionId && qaState.sessionTitle ? qaState.sessionTitle : `基于${title}问答`;
    if (eyebrow) eyebrow.textContent = qaState.sessionId ? `继续问答 · ${title}` : 'Literature-grounded QA';
    const context = document.getElementById('qa-scope-trigger');
    if (context) {
        context.innerHTML = `<i class="fas ${isCollection ? 'fa-layer-group' : 'fa-database'}" aria-hidden="true"></i><span>${escapeQaHtml(title)}</span><i class="fas fa-chevron-down qa-scope-chevron" aria-hidden="true"></i>`;
        context.setAttribute('aria-label', `选择文献范围，当前为${title}，共 ${count} 篇文献`);
    }
    restartQaSoftSwitch(chatTitle?.parentElement);
    restartQaSoftSwitch(context);
}

function restartQaSoftSwitch(element) {
    if (!element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    element.classList.remove('qa-soft-switch');
    window.requestAnimationFrame(() => {
        element.classList.add('qa-soft-switch');
        window.setTimeout(() => element.classList.remove('qa-soft-switch'), 360);
    });
}

async function ensureQaSession(question) {
    if (qaState.sessionId) return qaState.sessionId;
    if (qaState.scope === 'collection' && !qaState.collectionId) throw new Error('请先选择一个文献主题库');
    const session = await apiRequest('/api/knowledge-qa/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scope_type: qaState.scope,
            collection_id: qaState.collectionId,
            title: question.slice(0, 34),
        }),
    });
    qaState.sessionId = session.session_id;
    qaState.sessionTitle = session.title || question.slice(0, 34);
    updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: qaState.sessionId }, false);
    return qaState.sessionId;
}

async function handleQaSubmit(event) {
    event.preventDefault();
    if (qaState.busy) return;
    const input = document.getElementById('qa-question');
    const question = input?.value.trim() || '';
    if (!question) return;
    appendQaMessage({ role: 'user', content: question });
    if (input) input.value = '';
    resizeQaComposer();
    setQaBusy(true);
    const loadingId = appendQaLoading();
    try {
        const sessionId = await ensureQaSession(question);
        const result = await apiRequest(`/api/knowledge-qa/sessions/${encodeURIComponent(sessionId)}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question }),
        });
        document.getElementById(loadingId)?.remove();
        appendQaMessage({ ...(result.answer || {}), role: 'assistant', citations: result.citations || [] });
        updateRetrievalHint(result.retrieval_mode, result.scope_paper_count);
        await loadQaSessions();
    } catch (error) {
        document.getElementById(loadingId)?.remove();
        appendQaMessage({ role: 'assistant', content: `请求未完成：${error.message}`, isError: true });
        showQaToast(error.message, 'error');
        if (error.code === 'settings_required') openQaSettings();
    } finally {
        setQaBusy(false);
    }
}

function appendQaMessage(message) {
    const list = document.getElementById('qa-message-list');
    document.getElementById('qa-welcome')?.setAttribute('hidden', '');
    if (!list) return;
    const role = message.role === 'user' ? 'user' : 'assistant';
    const citations = Array.isArray(message.citations) ? message.citations : [];
    const citationHtml = citations.length ? `<div class="qa-citations">${citations.map(renderQaCitation).join('')}</div>` : '';
    const metaHtml = role === 'assistant' && (message.model || message.total_tokens !== null && message.total_tokens !== undefined)
        ? renderQaMessageMeta(message)
        : '';
    list.insertAdjacentHTML('beforeend', `<article class="qa-message qa-message-${role}${message.isError ? ' is-error' : ''}">
        <div class="qa-message-avatar"><i class="fas ${role === 'user' ? 'fa-user' : 'fa-brain'}" aria-hidden="true"></i></div>
        <div class="qa-message-content"><div class="qa-answer-text">${formatQaAnswer(message.content)}</div>${citationHtml}${metaHtml}</div>
    </article>`);
    const appendedMessage = list.lastElementChild;
    const messageIndex = Math.max(0, list.children.length - 1);
    appendedMessage?.style.setProperty('--qa-message-delay', `${Math.min(messageIndex, 4) * 28}ms`);
    typesetQaMath(appendedMessage);
    scrollQaToBottom();
}

function renderQaMessageMeta(message) {
    const parts = [];
    if (message.model) parts.push(`<span><i class="fas fa-microchip" aria-hidden="true"></i> ${escapeQaHtml(message.model)}</span>`);
    if (message.total_tokens !== null && message.total_tokens !== undefined) {
        const prompt = message.prompt_tokens ?? 0;
        const completion = message.completion_tokens ?? 0;
        parts.push(`<span title="输入 ${Number(prompt)} · 输出 ${Number(completion)}"><i class="fas fa-coins" aria-hidden="true"></i> ${Number(message.total_tokens)} tokens</span>`);
    }
    if (message.retrieval_mode) {
        const hybrid = String(message.retrieval_mode).startsWith('hybrid');
        const reranked = String(message.retrieval_mode).endsWith('_rerank');
        parts.push(`<span><i class="fas fa-magnifying-glass" aria-hidden="true"></i> ${hybrid ? '混合检索' : '关键词检索'}${reranked ? ' + 精排' : ''}</span>`);
    }
    if (message.reranker_model) {
        const duration = Number(message.rerank_duration_ms || 0);
        const candidates = Number(message.rerank_candidates || 0);
        parts.push(`<span title="${candidates} 条候选 · ${escapeQaHtml(message.rerank_device || 'auto')}"><i class="fas fa-arrow-down-wide-short" aria-hidden="true"></i> ${escapeQaHtml(message.reranker_model)} · ${duration} ms</span>`);
    } else if (message.rerank_error) {
        parts.push(`<span title="${escapeQaHtml(message.rerank_error)}"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i> 精排已降级</span>`);
    }
    return `<div class="qa-message-meta">${parts.join('')}</div>`;
}

function renderQaCitation(item) {
    const title = item.paper_title || item.title || item.identity_key || '文献来源';
    const section = item.section_title ? ` · ${item.section_title}` : '';
    const page = item.page_start ? ` · p.${item.page_start}${item.page_end && item.page_end !== item.page_start ? `-${item.page_end}` : ''}` : '';
    const href = item.source_type === 'fulltext'
        ? `/library/papers/${encodeURIComponent(item.identity_key)}/fulltext_view`
        : '#';
    const quote = String(item.quoted_text || '');
    const imageRefs = extractQaImageRefs(quote);
    const contentTypes = [];
    if (/\$\$|\\(?:frac|begin\{(?:equation|align)|mathrm|mathbf|sum|int)\b/.test(quote)) contentTypes.push('公式');
    if (imageRefs.length || /(?:^|\s)(?:fig\.|figure)\s*\d+/i.test(quote)) contentTypes.push('图像');
    if (/(?:^|\s)table\s*\d+/i.test(quote) || /^\s*\|.+\|\s*$/m.test(quote)) contentTypes.push('表格');
    const tag = item.source_type === 'abstract' ? '摘要' : (contentTypes.join(' · ') || '全文');
    const quoteWithoutImages = quote.replace(/!\[[^\]]*\]\([^)]+\)/g, '').trim();
    const gallery = renderQaCitationGallery(item.identity_key, imageRefs);
    return `<details class="qa-citation-card"><summary><span>[${Number(item.citation_order || 0)}]</span><strong>${escapeQaHtml(title)}</strong><em>${tag}</em></summary>
        ${gallery}<div class="qa-citation-evidence">${formatQaAnswer(quoteWithoutImages || '该证据片段仅包含图片资源。')}</div>
        <footer>${escapeQaHtml(`${item.section_title || '文献证据'}${page}`)}${href !== '#' ? `<a href="${href}" target="_blank" rel="noopener noreferrer">查看全文 <i class="fas fa-arrow-up-right-from-square" aria-hidden="true"></i></a>` : ''}</footer>
    </details>`;
}

function formatQaAnswer(value) {
    const protectedMath = protectQaMathSegments(normalizeQaMathSource(value));
    const lines = escapeQaHtml(protectedMath.text).replace(/\r/g, '').split('\n');
    const output = [];
    let listType = '';
    const closeList = () => {
        if (listType) output.push(`</${listType}>`);
        listType = '';
    };
    const inline = text => text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(?<!\!)\[(\d+)\]/g, '<span class="qa-inline-citation">[$1]</span>');
    lines.forEach(line => {
        const heading = line.match(/^(#{2,4})\s+(.+)$/);
        const bullet = line.match(/^\s*[-*]\s+(.+)$/);
        const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
        if (heading) {
            closeList();
            output.push(`<h${Math.min(4, heading[1].length + 1)}>${inline(heading[2])}</h${Math.min(4, heading[1].length + 1)}>`);
        } else if (bullet || numbered) {
            const nextType = bullet ? 'ul' : 'ol';
            if (listType !== nextType) {
                closeList();
                listType = nextType;
                output.push(`<${listType}>`);
            }
            output.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        } else if (!line.trim()) {
            closeList();
        } else {
            closeList();
            output.push(`<p>${inline(line)}</p>`);
        }
    });
    closeList();
    return restoreQaMathSegments(output.join(''), protectedMath.segments);
}

function protectQaMathSegments(value) {
    const segments = [];
    const text = String(value || '').replace(
        /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$(?!\$)[^$\n]+?\$/g,
        match => {
            const token = `@@QAMATH_${segments.length}@@`;
            segments.push(match);
            return token;
        },
    );
    return { text, segments };
}

function restoreQaMathSegments(html, segments) {
    return (segments || []).reduce(
        (result, math, index) => result.replaceAll(`@@QAMATH_${index}@@`, escapeQaHtml(math)),
        String(html || ''),
    );
}

function normalizeQaMathSource(value) {
    let text = String(value || '')
        .replace(/\\bm\s*\{([^{}]+)\}/g, '\\boldsymbol{$1}')
        .replace(/\\bm\s*([A-Za-z])/g, '\\boldsymbol{$1}');
    if ((text.match(/\$\$/g) || []).length % 2) {
        text = `${text.slice(0, text.lastIndexOf('$$')).trimEnd()}\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。`;
    }
    const openBrackets = (text.match(/\\\[/g) || []).length;
    const closeBrackets = (text.match(/\\\]/g) || []).length;
    if (openBrackets > closeBrackets) {
        text = `${text.slice(0, text.lastIndexOf('\\[')).trimEnd()}\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。`;
    }
    return text;
}

function extractQaImageRefs(text) {
    const refs = [];
    const pattern = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)/g;
    let match;
    while ((match = pattern.exec(String(text || ''))) && refs.length < 6) {
        const path = match[2].trim();
        const segments = path.split('/');
        if (!path || path.startsWith('/') || path.includes('://') || segments.includes('..')) continue;
        refs.push({ alt: match[1].trim() || '文献图像', path });
    }
    return refs;
}

function renderQaCitationGallery(identityKey, refs) {
    if (!identityKey || !refs.length) return '';
    const images = refs.map(ref => {
        const url = `/api/library/papers/${encodeURIComponent(identityKey)}/fulltext_asset?path=${encodeURIComponent(ref.path)}`;
        return `<a href="${url}" target="_blank" rel="noopener noreferrer" title="打开原图"><img src="${url}" alt="${escapeQaHtml(ref.alt)}" width="320" height="240" loading="lazy" decoding="async"></a>`;
    }).join('');
    return `<div class="qa-citation-gallery">${images}</div>`;
}

function typesetQaMath(container) {
    if (!container || !window.MathJax?.typesetPromise) return;
    const render = () => window.MathJax.typesetPromise([container]).catch(() => {});
    if (window.MathJax.startup?.promise) window.MathJax.startup.promise.then(render).catch(() => {});
    else render();
}

function appendQaLoading() {
    const id = `qa-loading-${Date.now()}`;
    const list = document.getElementById('qa-message-list');
    list?.insertAdjacentHTML('beforeend', `<article class="qa-message qa-message-assistant" id="${id}" aria-live="polite"><div class="qa-message-avatar"><i class="fas fa-brain" aria-hidden="true"></i></div><div class="qa-message-content"><div class="qa-thinking"><span></span><span></span><span></span><em>正在检索文献并生成回答…</em></div></div></article>`);
    scrollQaToBottom();
    return id;
}

function setQaBusy(busy) {
    qaState.busy = busy;
    const send = document.getElementById('qa-send-button');
    const input = document.getElementById('qa-question');
    if (send) send.disabled = busy;
    if (input) input.disabled = busy;
}

async function handleHistoryClick(event) {
    if (event.target.closest('.qa-history-actions')) return;
    const button = event.target.closest('.qa-history-item');
    if (!button || qaState.busy) return;
    if (button.dataset.action === 'new') {
        startNewQaConversation();
        return;
    }
    const sessionId = button.dataset.sessionId || '';
    if (!sessionId) return;
    const restoringUrlState = button.dataset.restoreState === '1';
    delete button.dataset.restoreState;
    try {
        button.classList.add('is-loading');
        button.setAttribute('aria-busy', 'true');
        const detail = await apiRequest(`/api/knowledge-qa/sessions/${encodeURIComponent(sessionId)}`);
        qaState.sessionId = sessionId;
        qaState.sessionTitle = detail.title || '未命名问答';
        let scope = {};
        try { scope = JSON.parse(detail.scope_json || '{}'); } catch (_) { scope = {}; }
        qaState.scope = detail.scope_type === 'collection' ? 'collection' : 'library';
        qaState.collectionId = qaState.scope === 'collection' ? (scope.collection_id || '') : '';
        updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: qaState.sessionId }, restoringUrlState);
        resetQaMessages();
        (detail.messages || []).forEach(appendQaMessage);
        renderQaCollections();
        renderQaHistory();
        updateQaSourceDisplay();
        const input = document.getElementById('qa-question');
        if (input) {
            input.placeholder = '继续当前问答…';
            input.focus();
        }
        showQaToast('历史问答已恢复，可以继续提问', 'success');
    } catch (error) {
        showQaToast(error.message, 'error');
    } finally {
        button.classList.remove('is-loading');
        button.removeAttribute('aria-busy');
    }
}

async function handleHistoryRenameClick(event) {
    const button = event.target.closest('.qa-history-rename');
    if (!button || qaState.busy) return;
    event.preventDefault();
    event.stopPropagation();
    const sessionId = button.dataset.renameSessionId || '';
    const currentTitle = button.dataset.sessionTitle || '未命名问答';
    if (!sessionId) return;
    const entered = window.prompt('修改对话名称', currentTitle);
    if (entered === null) return;
    const title = entered.replace(/\s+/g, ' ').trim();
    if (!title) {
        showQaToast('对话名称不能为空', 'error');
        return;
    }
    if (title.length > 80) {
        showQaToast('对话名称不能超过 80 个字符', 'error');
        return;
    }
    if (title === currentTitle) return;
    setButtonBusy(button, true);
    try {
        const updated = await apiRequest(`/api/knowledge-qa/sessions/${encodeURIComponent(sessionId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (qaState.sessionId === sessionId) qaState.sessionTitle = updated.title || title;
        await loadQaSessions();
        showQaToast('对话名称已修改', 'success');
    } catch (error) {
        showQaToast(error.message, 'error');
        setButtonBusy(button, false);
    }
}

async function handleHistoryDeleteClick(event) {
    const button = event.target.closest('.qa-history-delete');
    if (!button || qaState.busy) return;
    event.preventDefault();
    event.stopPropagation();
    const sessionId = button.dataset.deleteSessionId || '';
    if (!sessionId) return;
    const title = button.dataset.sessionTitle || '该问答';
    if (!window.confirm(`删除历史问答“${title}”？\n该会话中的问题、回答和引用将一并删除。`)) return;
    setButtonBusy(button, true, '');
    try {
        await apiRequest(`/api/knowledge-qa/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
        if (qaState.sessionId === sessionId) {
            qaState.sessionId = '';
            qaState.sessionTitle = '';
            resetQaMessages();
            updateQaSourceDisplay();
            const input = document.getElementById('qa-question');
            if (input) input.placeholder = '向文献数据库提问…';
            updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: '' }, true);
        }
        await loadQaSessions();
        showQaToast('历史问答已删除', 'success');
    } catch (error) {
        showQaToast(error.message, 'error');
        setButtonBusy(button, false);
    }
}

function startNewQaConversation() {
    if (qaState.busy) return;
    qaState.sessionId = '';
    qaState.sessionTitle = '';
    resetQaMessages();
    renderQaHistory();
    updateQaSourceDisplay();
    updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: '' }, false);
    const input = document.getElementById('qa-question');
    if (input) {
        input.placeholder = '向文献数据库提问…';
        input.focus();
    }
}

async function deleteCurrentQaConversation() {
    if (qaState.busy) return;
    if (!qaState.sessionId) {
        resetQaMessages();
        return;
    }
    if (!window.confirm('删除当前问答记录？')) return;
    try {
        await apiRequest(`/api/knowledge-qa/sessions/${encodeURIComponent(qaState.sessionId)}`, { method: 'DELETE' });
        qaState.sessionId = '';
        qaState.sessionTitle = '';
        updateQaUrl({ scope: qaState.scope, collection: qaState.collectionId, session: '' }, true);
        resetQaMessages();
        await loadQaSessions();
        showQaToast('问答记录已删除', 'success');
    } catch (error) {
        showQaToast(error.message, 'error');
    }
}

function resetQaMessages() {
    const list = document.getElementById('qa-message-list');
    const welcome = document.getElementById('qa-welcome');
    if (list) list.innerHTML = '';
    if (welcome) welcome.hidden = false;
}

function openQaSettings() {
    const backdrop = document.getElementById('qa-settings-backdrop');
    if (!backdrop || !backdrop.hidden) return;
    window.clearTimeout(qaState.settingsCloseTimer);
    backdrop.classList.remove('is-closing');
    qaState.settingsReturnFocus = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : document.getElementById('qa-open-settings');
    backdrop.hidden = false;
    document.querySelectorAll('body > .skip-link, .qa-workspace, body > .footer').forEach(element => {
        element.inert = true;
    });
    document.body.classList.add('qa-modal-open');
    window.requestAnimationFrame(() => document.getElementById('qa-model')?.focus());
}

function closeQaSettings() {
    const backdrop = document.getElementById('qa-settings-backdrop');
    if (!backdrop || backdrop.hidden || backdrop.classList.contains('is-closing')) return;
    backdrop.classList.add('is-closing');
    const returnFocus = qaState.settingsReturnFocus;
    qaState.settingsReturnFocus = null;
    qaState.settingsCloseTimer = window.setTimeout(() => {
        backdrop.hidden = true;
        backdrop.classList.remove('is-closing');
        document.querySelectorAll('body > .skip-link, .qa-workspace, body > .footer').forEach(element => {
            element.inert = false;
        });
        document.body.classList.remove('qa-modal-open');
        window.requestAnimationFrame(() => {
            if (returnFocus?.isConnected) returnFocus.focus();
            else document.getElementById('qa-open-settings')?.focus();
        });
    }, 180);
}

function handleQaDocumentKeydown(event) {
    const scopeMenu = document.getElementById('qa-scope-menu');
    if (event.key === 'Escape' && scopeMenu && !scopeMenu.hidden) {
        event.preventDefault();
        closeQaScopeMenu(true);
        return;
    }
    const backdrop = document.getElementById('qa-settings-backdrop');
    if (!backdrop || backdrop.hidden) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        closeQaSettings();
        return;
    }
    if (event.key !== 'Tab') return;

    const dialog = backdrop.querySelector('.qa-settings-dialog');
    if (!dialog) return;
    const focusable = Array.from(dialog.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )).filter(element => !element.hidden && element.getClientRects().length > 0);
    if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    } else if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
    }
}

function fillQaSettingsForm(settings) {
    const values = {
        'qa-provider': settings.provider || 'openai_compatible',
        'qa-model': settings.model || '',
        'qa-answer-depth': settings.answer_depth || 'detailed',
        'qa-max-tokens': settings.max_tokens || 3200,
        'qa-base-url': settings.base_url || '',
        'qa-retrieval-mode': settings.retrieval_mode || 'lexical',
        'qa-embedding-model': settings.embedding_model || '',
        'qa-embedding-base-url': settings.embedding_base_url || '',
        'qa-top-k': settings.top_k || 10,
        'qa-reranker-final-k': settings.top_k || 10,
        'qa-reranker-model': settings.reranker_model || 'BAAI/bge-reranker-v2-m3',
        'qa-reranker-candidate-k': settings.reranker_candidate_k || 40,
        'qa-reranker-device': settings.reranker_device || 'auto',
        'qa-reranker-batch-size': settings.reranker_batch_size || 4,
        'qa-reranker-max-length': settings.reranker_max_length || 512,
    };
    Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.value = value;
    });
    const key = document.getElementById('qa-api-key');
    const embeddingKey = document.getElementById('qa-embedding-api-key');
    if (key) {
        key.value = '';
        key.placeholder = settings.has_api_key ? '已保存；留空表示保持不变' : '请输入访问密钥';
    }
    if (embeddingKey) {
        embeddingKey.value = '';
        embeddingKey.placeholder = settings.has_embedding_api_key ? '已保存；留空表示保持不变' : '留空时使用回答模型密钥';
    }
    const keyStatus = document.getElementById('qa-api-key-status');
    const embeddingKeyStatus = document.getElementById('qa-embedding-api-key-status');
    if (keyStatus) {
        keyStatus.classList.toggle('is-saved', Boolean(settings.has_api_key));
        keyStatus.innerHTML = `<i class="fas fa-${settings.has_api_key ? 'shield-halved' : 'lock'}" aria-hidden="true"></i> ${settings.has_api_key ? '已安全保存到本机，页面不会回显原文' : '尚未保存'}`;
    }
    if (embeddingKeyStatus) {
        embeddingKeyStatus.classList.toggle('is-saved', Boolean(settings.has_embedding_api_key));
        embeddingKeyStatus.innerHTML = `<i class="fas fa-${settings.has_embedding_api_key ? 'shield-halved' : 'lock'}" aria-hidden="true"></i> ${settings.has_embedding_api_key ? 'Embedding 密钥已安全保存到本机' : '尚未单独保存，将使用回答模型密钥'}`;
    }
    const rerankerEnabled = document.getElementById('qa-reranker-enabled');
    if (rerankerEnabled) rerankerEnabled.checked = Boolean(settings.reranker_enabled);
    updateEmbeddingFields();
    updateRerankerFields();
}

function collectQaSettings() {
    return {
        provider: document.getElementById('qa-provider')?.value || 'openai_compatible',
        model: document.getElementById('qa-model')?.value.trim() || '',
        base_url: document.getElementById('qa-base-url')?.value.trim() || '',
        api_key: document.getElementById('qa-api-key')?.value.trim() || '',
        answer_depth: document.getElementById('qa-answer-depth')?.value || 'detailed',
        max_tokens: Number(document.getElementById('qa-max-tokens')?.value || 3200),
        retrieval_mode: document.getElementById('qa-retrieval-mode')?.value || 'lexical',
        embedding_model: document.getElementById('qa-embedding-model')?.value.trim() || '',
        embedding_base_url: document.getElementById('qa-embedding-base-url')?.value.trim() || '',
        embedding_api_key: document.getElementById('qa-embedding-api-key')?.value.trim() || '',
        top_k: Number(document.getElementById('qa-top-k')?.value || 10),
        reranker_enabled: Boolean(document.getElementById('qa-reranker-enabled')?.checked),
        reranker_model: document.getElementById('qa-reranker-model')?.value.trim() || 'BAAI/bge-reranker-v2-m3',
        reranker_candidate_k: Number(document.getElementById('qa-reranker-candidate-k')?.value || 40),
        reranker_device: document.getElementById('qa-reranker-device')?.value || 'auto',
        reranker_batch_size: Number(document.getElementById('qa-reranker-batch-size')?.value || 4),
        reranker_max_length: Number(document.getElementById('qa-reranker-max-length')?.value || 512),
        preserve_api_key: true,
        preserve_embedding_api_key: true,
    };
}

async function saveQaSettings(event) {
    event.preventDefault();
    try {
        const payload = await apiRequest('/api/knowledge-qa/settings', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectQaSettings()),
        });
        qaState.settings = payload.settings;
        fillQaSettingsForm(payload.settings);
        updateQaModelStatus();
        showQaToast(payload.message || '配置已保存', 'success');
        closeQaSettings();
    } catch (error) {
        showQaToast(error.message, 'error');
    }
}

async function testQaModel() {
    const button = document.getElementById('qa-test-model');
    setButtonBusy(button, true, '正在测试');
    try {
        const payload = await apiRequest('/api/knowledge-qa/settings/test', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectQaSettings()),
        });
        showQaToast(payload.message || '连接成功', 'success');
    } catch (error) {
        showQaToast(error.message, 'error');
    } finally {
        setButtonBusy(button, false);
    }
}

async function buildQaIndex() {
    const button = document.getElementById('qa-build-index');
    setButtonBusy(button, true, '正在建立索引');
    try {
        await apiRequest('/api/knowledge-qa/settings', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectQaSettings()),
        });
        const payload = await apiRequest('/api/knowledge-qa/index', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope_type: qaState.scope, collection_id: qaState.collectionId }),
        });
        showQaToast(payload.message || '语义索引已更新', 'success');
        await loadQaSettings();
    } catch (error) {
        showQaToast(error.message, 'error');
    } finally {
        setButtonBusy(button, false);
    }
}

async function loadQaIndexStatus() {
    const status = document.getElementById('qa-index-status');
    if (!status) return;
    try {
        const payload = await apiRequest('/api/knowledge-qa/index/status');
        status.textContent = payload.total > 0
            ? `当前模型已索引 ${Number(payload.total)} 条证据，覆盖 ${Number(payload.papers)} 篇文献 · ${payload.updated_at || ''}`
            : '当前 Embedding 模型尚未建立语义索引';
    } catch (error) {
        status.textContent = error.message;
    }
}

async function loadQaRerankerStatus() {
    const status = document.getElementById('qa-reranker-status');
    if (!status) return;
    try {
        const payload = await apiRequest('/api/knowledge-qa/reranker/status');
        const sizeGb = Number(payload.size_bytes || 0) / (1024 ** 3);
        if (!payload.deployed) {
            status.innerHTML = '<i class="fas fa-circle-exclamation" aria-hidden="true"></i> 模型尚未部署；问答会自动使用原有 RRF 排名';
            status.classList.remove('is-ready');
            return;
        }
        status.classList.add('is-ready');
        status.innerHTML = `<i class="fas fa-circle-check" aria-hidden="true"></i> ${escapeQaHtml(payload.model_id || '本地 Reranker')} · ${escapeQaHtml(payload.device || 'cpu')} · ${sizeGb.toFixed(2)} GB · ${payload.loaded ? '已加载' : '已部署，首次问答时加载'}`;
    } catch (error) {
        status.textContent = error.message;
        status.classList.remove('is-ready');
    }
}

async function deployQaReranker() {
    const button = document.getElementById('qa-deploy-reranker');
    setButtonBusy(button, true, '正在部署模型');
    try {
        await apiRequest('/api/knowledge-qa/settings', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectQaSettings()),
        });
        const payload = await apiRequest('/api/knowledge-qa/reranker/deploy', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model_id: document.getElementById('qa-reranker-model')?.value.trim(),
                device: document.getElementById('qa-reranker-device')?.value || 'auto',
            }),
        });
        qaState.settings = payload.settings;
        fillQaSettingsForm(payload.settings);
        showQaToast(payload.message || '本地 Reranker 已部署', 'success');
        await loadQaRerankerStatus();
    } catch (error) {
        showQaToast(error.message, 'error');
        await loadQaRerankerStatus();
    } finally {
        setButtonBusy(button, false);
    }
}

function updateEmbeddingFields() {
    const hybrid = document.getElementById('qa-retrieval-mode')?.value === 'hybrid';
    document.getElementById('qa-embedding-fields')?.classList.toggle('is-disabled', !hybrid);
    document.getElementById('qa-build-index')?.toggleAttribute('disabled', !hybrid);
}

function updateRerankerFields() {
    const enabled = Boolean(document.getElementById('qa-reranker-enabled')?.checked);
    document.getElementById('qa-reranker-fields')?.classList.toggle('is-disabled', !enabled);
}

function updateQaModelStatus() {
    const status = document.getElementById('qa-model-status');
    const configured = Boolean(qaState.settings?.model && qaState.settings?.base_url && (qaState.settings.provider === 'ollama' || qaState.settings.has_api_key));
    if (status) {
        status.classList.toggle('is-ready', configured);
        status.innerHTML = `<i class="fas fa-circle" aria-hidden="true"></i> ${configured ? escapeQaHtml(qaState.settings.model) : '未配置模型'}`;
    }
    const mode = qaState.settings?.retrieval_mode === 'hybrid' ? 'hybrid' : 'lexical';
    updateRetrievalHint(qaState.settings?.reranker_enabled ? `${mode}_rerank` : mode);
}

function updateRetrievalHint(mode, paperCount = null) {
    const hint = document.getElementById('qa-retrieval-hint');
    if (!hint) return;
    const hybrid = String(mode || '').startsWith('hybrid');
    const reranked = String(mode || '').endsWith('_rerank');
    const label = hybrid ? '关键词 + 向量混合检索' : '本地关键词检索';
    hint.textContent = `${label}${reranked ? ' + 本地精排' : ''}${paperCount !== null ? ` · 已在 ${Number(paperCount)} 篇文献中检索` : ''} · 回答保留引用来源`;
}

function setButtonBusy(button, busy, label = '') {
    if (!button) return;
    if (busy) {
        button.dataset.originalHtml = button.innerHTML;
        const busyLabel = label ? `${label}…` : '';
        button.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>${busyLabel ? ` ${escapeQaHtml(busyLabel)}` : ''}`;
    } else if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
    }
    button.disabled = busy;
    button.toggleAttribute('aria-busy', busy);
}

function showQaToast(message, type = 'info') {
    const stack = document.getElementById('qa-toast-stack');
    if (!stack) return;
    const toast = document.createElement('div');
    toast.className = `qa-toast qa-toast-${type}`;
    toast.innerHTML = `<i class="fas ${type === 'success' ? 'fa-circle-check' : type === 'error' ? 'fa-circle-exclamation' : 'fa-circle-info'}" aria-hidden="true"></i><span>${escapeQaHtml(message)}</span>`;
    stack.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4200);
}

function scrollQaToBottom() {
    const body = document.getElementById('qa-chat-body');
    if (!body) return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    body.scrollTo({ top: body.scrollHeight, behavior: reduceMotion ? 'auto' : 'smooth' });
}

function resizeQaComposer() {
    const input = document.getElementById('qa-question');
    if (!input) return;
    if (window.CSS?.supports?.('field-sizing', 'content')) {
        input.style.height = '';
        return;
    }
    window.cancelAnimationFrame(qaState.composerResizeFrame);
    qaState.composerResizeFrame = window.requestAnimationFrame(() => {
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
    });
}

function escapeQaHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

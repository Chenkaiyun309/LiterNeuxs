// 全局变量
let currentTab = 'search';
let tasks = {};
let taskLogOffsets = {};
let currentCsvPath = '';
let currentCsvPage = 1;
let currentLibraryPage = 1;
let currentLibraryQuery = '';
let currentLibraryFulltextQuery = '';
let currentLibraryFulltextScope = 'selected_papers';
let currentQaSessionId = '';
let currentQaPaper = null;
let currentCollections = [];
let currentCollectionId = '';
let selectedCsvRows = new Set();
let selectedLibraryPaperIds = new Set();
let selectedCollectionPaperIds = new Set();
let currentGraphData = null;
let graphSettingsState = { has_api_key: false };
let reportSettingsState = { has_api_key: false };
let reportSourceSummaryState = { ready: false, can_generate: false, request_id: 0 };
let reportSourceSummaryTimer = null;
let previewSwitchMotionTimer = null;
let graphInteractionState = {
    nodeMap: new Map(),
    edges: [],
    selectedNodeId: '',
    draggedNodeId: '',
    dragMoved: false,
    isPanning: false,
    panMoved: false,
    transform: { scale: 1, x: 0, y: 0 }
};
let literatureSort = { field: '', direction: 'desc' };
let outputDirChoices = [];
let trendTopics = [];
let trendEvidenceStore = {};
const literaturePageSize = 20;
const DEFAULT_METADATA_SOURCES = [];
const RUN_LOG_TASK_RE = /^(search|generate|enrich|graph)_/;
const MAX_RUN_LOG_ENTRIES = 300;
const RUN_LOG_MESSAGE_RE = /(搜索任务|搜索失败|搜索请求失败|开始检索|检索完成|检索过程中|文献检索|文献数据库|多源补全|补全文献数据库|DOI 回查|开始生成日报|日报生成完成|生成任务|生成失败|生成请求失败|生成过程中|科研日报生成完成|本次共生成|大模型访问密钥|知识图谱|图谱生成|三元组|微观结构细化)/;
const ACTION_NOTIFICATION_RE = /(入库|文献主题库|自动归类|PDF|MD|Markdown|Marker|解析|上传|删除|移除|加入|多源补全|知识图谱|综述|搜索任务|检索|输出目录|任务).*(完成|成功|失败|已|请|不能为空|开始|取消|提示|启动)|^(请先|请选择|未选择|文献主题库名称不能为空)/;
const THEME_STORAGE_KEY = 'liternexus-theme';
const LEGACY_THEME_STORAGE_KEY = 'scholarflow-theme';
const FULLTEXT_FONT_SCALE_STORAGE_KEY = 'liternexus-fulltext-font-scale';
const LEGACY_FULLTEXT_FONT_SCALE_STORAGE_KEY = 'scholarflow-fulltext-font-scale';
const GRAPH_MOTION_STORAGE_KEY = 'liternexus-graph-motion';
const FULLTEXT_FONT_SCALE_MIN = 0.8;
const FULLTEXT_FONT_SCALE_MAX = 5;
const FULLTEXT_FONT_SCALE_STEP = 0.5;
const fullTextModalState = {
    identityKey: '',
    sourceText: '',
    draftText: '',
    data: null,
    assetBaseUrl: '',
    mode: 'render',
    saving: false,
    notice: '',
    fontScale: 1,
    dirty: false,
};
const managedModalState = new WeakMap();
const databaseCredentialHints = {
    semantic_scholar: 'Semantic Scholar：建议填写自己的访问密钥；不填也能请求，但更容易限流。',
    openalex: 'OpenAlex：不需要访问密钥；建议填写联系邮箱以使用更稳定的服务通道。',
    crossref: 'Crossref：不需要访问密钥；建议填写联系邮箱以使用更稳定的服务通道。',
    arxiv: 'arXiv：不需要访问密钥。',
    pubmed: 'PubMed：可填写 NCBI 访问密钥提高请求额度，并建议填写联系邮箱。',
    springer_nature: 'Springer Nature：需要填写访问密钥，可选择开放获取接口或元数据接口。'
};

// DOM加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM加载完成');
    if (window.LITERNEXUS_FULLTEXT_VIEW || window.SCHOLARFLOW_FULLTEXT_VIEW) {
        initializeFullTextViewPage();
        return;
    }
    if (!document.body.classList.contains('workspace-page')) {
        initializeThemeToggle();
        document.getElementById('theme-toggle')?.addEventListener('click', toggleThemeMode);
        return;
    }

    // 初始化界面
    initializeUI();
    
    // 绑定事件监听器
    bindEventListeners();
    
    // 加载初始数据
    loadInitialData();

    // 加载本机保存的综述生成参数
    loadReportSettings();

    // 加载本机保存的知识图谱参数与模型配置
    loadGraphSettings();
    
    // 刷新文件列表
    refreshFileList({ activatePreview: false });

    // 同步文献主题库到知识图谱选择器
    loadLibraryCollections(false);

    // 加载研究热点主题
    refreshTrendTopics();

    restoreWorkspaceStateFromUrl();
    window.addEventListener('popstate', restoreWorkspaceStateFromUrl);
});

function updateWorkspaceUrl(changes = {}, replace = true) {
    const url = new URL(window.location.href);
    Object.entries(changes).forEach(([key, value]) => {
        const normalized = String(value ?? '').trim();
        if (normalized) url.searchParams.set(key, normalized);
        else url.searchParams.delete(key);
    });
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({}, '', `${url.pathname}${url.search}${url.hash}`);
}

function restoreWorkspaceStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const moduleName = params.get('module');
    const previewName = params.get('preview');
    const validModules = new Set(['search', 'report', 'graph', 'trend']);
    const validPreviews = new Set(['literature', 'library', 'collections', 'report', 'graph', 'trend', 'logs']);
    const restoredModule = validModules.has(moduleName) ? moduleName : 'search';
    const restoredPreview = validPreviews.has(previewName) ? previewName : 'literature';
    showControlSection(restoredModule, false);
    showPreviewTab(restoredPreview, false);
    updateWorkspaceUrl({ module: restoredModule, preview: restoredPreview }, true);
    const libraryQuery = params.get('library_q') || '';
    const libraryPage = Math.max(1, Number.parseInt(params.get('library_page') || '1', 10) || 1);
    if (libraryQuery || libraryPage > 1) {
        currentLibraryQuery = libraryQuery;
        const input = document.getElementById('library-search-input');
        if (input) input.value = libraryQuery;
        if (restoredPreview === 'library') loadLibraryPapers(libraryPage, false);
    }
}

function getManagedModalFocusable(modal) {
    return Array.from(modal.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(element => !element.hidden && element.getClientRects().length > 0);
}

function activateManagedModal(modal, initialFocus = null) {
    if (!modal || managedModalState.has(modal)) return;
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const background = Array.from(document.body.children).filter(element => (
        element !== modal && element.tagName !== 'SCRIPT' && !element.inert
    ));
    background.forEach(element => { element.inert = true; });
    managedModalState.set(modal, { returnFocus, background });
    window.setTimeout(() => {
        const target = initialFocus || getManagedModalFocusable(modal)[0] || modal.querySelector('[role="dialog"]');
        target?.focus();
    }, 0);
}

function deactivateManagedModal(modal) {
    const state = modal ? managedModalState.get(modal) : null;
    if (!state) return;
    state.background.forEach(element => { element.inert = false; });
    managedModalState.delete(modal);
    window.setTimeout(() => {
        if (state.returnFocus?.isConnected) state.returnFocus.focus();
    }, 0);
}

function trapManagedModalFocus(event, modal) {
    if (event.key !== 'Tab' || !modal?.classList.contains('is-open')) return;
    const focusable = getManagedModalFocusable(modal);
    if (!focusable.length) {
        event.preventDefault();
        modal.querySelector('[role="dialog"]')?.focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
    }
}

function isFullTextDirty() {
    if (fullTextModalState.mode !== 'edit') return false;
    const editor = document.querySelector('#paper-fulltext-editor, #fulltext-page-editor');
    const draft = editor ? editor.value : fullTextModalState.draftText;
    return fullTextModalState.dirty || draft !== fullTextModalState.sourceText;
}

window.addEventListener('beforeunload', event => {
    if (!isFullTextDirty()) return;
    event.preventDefault();
    event.returnValue = '';
});

// 初始化界面
function initializeUI() {
    initializeThemeToggle();
    normalizeCollectionTypeOptions();
    initializeControlSectionsCollapsed('search');
    initializePreviewSectionsCollapsed('literature');
}

function initializeControlSectionsCollapsed(defaultSection = 'search') {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.getAttribute('data-tab') === defaultSection);
    });
    document.querySelectorAll('.module-tab').forEach(tab => {
        const isDefault = tab.getAttribute('data-module-tab') === defaultSection;
        tab.classList.toggle('active', isDefault);
        tab.setAttribute('aria-selected', isDefault ? 'true' : 'false');
        tab.setAttribute('aria-expanded', 'false');
        updateModuleTabChevron(tab, false);
    });
    document.querySelectorAll('.accordion-collapse').forEach(panel => {
        panel.classList.remove('show');
    });
    document.querySelectorAll('.accordion-button').forEach(button => {
        button.classList.add('collapsed');
        button.setAttribute('aria-expanded', 'false');
    });
}

function initializePreviewSectionsCollapsed(defaultTab = 'literature') {
    document.querySelector('.preview-panel')?.classList.add('is-collapsed');
    document.querySelectorAll('.tab-btn').forEach(button => {
        const isDefault = button.getAttribute('data-tab') === defaultTab;
        button.classList.toggle('active', isDefault);
        button.setAttribute('aria-selected', isDefault ? 'true' : 'false');
        button.setAttribute('aria-expanded', 'false');
        updatePreviewTabChevron(button, false);
    });
    document.querySelectorAll('.preview-tab').forEach(tab => {
        tab.classList.toggle('active', tab.id === `${defaultTab}-preview`);
    });
}

function normalizeCollectionTypeOptions() {
    const customOption = document.querySelector('#collection-type option[value="custom"]');
    if (customOption) {
        customOption.textContent = '其它';
    }
}

function getStoredThemeMode() {
    const stored = localStorage.getItem(THEME_STORAGE_KEY) || localStorage.getItem(LEGACY_THEME_STORAGE_KEY);
    return stored === 'night' ? 'night' : 'day';
}

function clampFullTextFontScale(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 1;
    return Math.min(FULLTEXT_FONT_SCALE_MAX, Math.max(FULLTEXT_FONT_SCALE_MIN, Number(numeric.toFixed(2))));
}

function getStoredFullTextFontScale() {
    const stored = localStorage.getItem(FULLTEXT_FONT_SCALE_STORAGE_KEY)
        || localStorage.getItem(LEGACY_FULLTEXT_FONT_SCALE_STORAGE_KEY);
    return clampFullTextFontScale(stored || 1);
}

function setStoredFullTextFontScale(value) {
    const normalized = clampFullTextFontScale(value);
    localStorage.setItem(FULLTEXT_FONT_SCALE_STORAGE_KEY, String(normalized));
    return normalized;
}

function applyThemeMode(theme) {
    const normalizedTheme = theme === 'night' ? 'night' : 'day';
    const root = document.documentElement;
    const toggle = document.getElementById('theme-toggle');
    const toggleText = toggle ? toggle.querySelector('.theme-toggle-text') : null;

    root.setAttribute('data-theme', normalizedTheme);
    localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
    document.getElementById('theme-color-meta')?.setAttribute(
        'content',
        normalizedTheme === 'night' ? '#091624' : '#eef6fc',
    );

    if (!toggle) return;

    const isNight = normalizedTheme === 'night';
    toggle.setAttribute('aria-pressed', isNight ? 'true' : 'false');
    toggle.setAttribute('aria-label', isNight ? '切换到日览模式' : '切换到夜览模式');
    if (toggleText) {
        toggleText.textContent = isNight ? '夜览模式' : '日览模式';
    }
}

function initializeThemeToggle() {
    applyThemeMode(getStoredThemeMode());
    fullTextModalState.fontScale = getStoredFullTextFontScale();
}

function toggleThemeMode() {
    const currentTheme = document.documentElement.getAttribute('data-theme') === 'night' ? 'night' : 'day';
    applyThemeMode(currentTheme === 'night' ? 'day' : 'night');
}

// 绑定事件监听器
function bindEventListeners() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            showControlSection(this.getAttribute('data-tab'));
        });
    });

    document.querySelectorAll('.module-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            toggleModuleSection(this.getAttribute('data-module-tab'));
        });
    });

    document.querySelectorAll('.accordion-button').forEach(button => {
        button.addEventListener('click', function() {
            const targetSelector = this.getAttribute('data-bs-target');
            if (targetSelector) {
                toggleAccordion(targetSelector, this);
            }
        });
    });

    // 预览标签切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const tab = this.getAttribute('data-tab');
            togglePreviewSection(tab);
        });
    });

    document.addEventListener('click', function(e) {
        if (!e.target.closest('.collection-chooser')) {
            closeCollectionChoosers();
        }
    });
    
    // 查询词操作
    document.getElementById('add-query').addEventListener('click', addQueryField);
    document.getElementById('query-list').addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-query')) {
            removeQueryField(e.target);
        }
    });
    
    // 表单提交
    document.getElementById('search-form').addEventListener('submit', handleSearch);
    document.getElementById('report-form').addEventListener('submit', handleGenerate);
    
    // 其他按钮
    document.getElementById('clear-log').addEventListener('click', clearLog);
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleThemeMode);
    }
    document.getElementById('toggle-llm-api-key').addEventListener('click', toggleLlmApiKeyVisibility);
    document.getElementById('toggle-graph-llm-api-key')?.addEventListener('click', toggleGraphLlmApiKeyVisibility);
    document.getElementById('save-report-config-btn')?.addEventListener('click', saveReportSettings);
    document.getElementById('save-graph-config-btn')?.addEventListener('click', saveGraphSettings);
    document.getElementById('search-file-list').addEventListener('change', handleSearchFileSelection);
    document.getElementById('search-file-list').addEventListener('click', handleSearchFileSelection);
    document.getElementById('preview-csv-select').addEventListener('change', handlePreviewCsvSelection);
    document.getElementById('preview-csv-select').addEventListener('change', refreshTrendTopics);
    document.getElementById('open-preview-csv').addEventListener('click', handleOpenPreviewCsvFile);
    document.getElementById('enrich-preview-csv').addEventListener('click', handleEnrichPreviewCsv);
    document.getElementById('report-file-list').addEventListener('change', handleFileSelection);
    document.getElementById('open-report-location').addEventListener('click', openReportLocation);
    document.getElementById('report-file-picker').addEventListener('change', handleReportFilePicked);
    document.getElementById('browse-csv').addEventListener('click', handleBrowseCsv);
    document.getElementById('csv-file-picker').addEventListener('change', handleCsvFilePicked);
    document.getElementById('browse-output').addEventListener('click', handleBrowseOutput);
    document.getElementById('report-data-source')?.addEventListener('change', updateReportSourceControls);
    document.getElementById('report-collection-select')?.addEventListener('change', scheduleReportSourceSummary);
    document.getElementById('report-input-mode')?.addEventListener('change', scheduleReportSourceSummary);
    document.getElementById('refresh-report-source-summary')?.addEventListener('click', () => refreshReportSourceSummary());
    document.getElementById('output-dir').addEventListener('focus', showOutputDirOptions);
    document.getElementById('output-dir').addEventListener('input', showOutputDirOptions);
    document.getElementById('graph-data-source-select')?.addEventListener('change', updateGraphScopeControls);
    document.getElementById('graph-collection-select')?.addEventListener('change', function() {
        currentCollectionId = this.value || currentCollectionId;
        updateGraphScopeControls();
    });
    document.getElementById('graph-csv-select').addEventListener('change', handleGraphCsvSelection);
    document.getElementById('graph-csv-select').addEventListener('change', refreshTrendTopics);
    document.getElementById('generate-graph-btn').addEventListener('click', loadKnowledgeGraph);
    document.getElementById('load-trend-btn').addEventListener('click', loadTrendAnalysis);
    document.getElementById('add-trend-topic-btn')?.addEventListener('click', addTrendTopicRow);
    document.getElementById('trend-window-select')?.addEventListener('change', refreshTrendTopics);
    document.getElementById('trend-publication-window-select')?.addEventListener('change', refreshTrendTopics);
    document.getElementById('trend-source-select')?.addEventListener('change', refreshTrendTopics);
    document.getElementById('library-search-btn')?.addEventListener('click', handleLibrarySearch);
    document.getElementById('library-search-input')?.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleLibrarySearch();
        }
    });
    document.getElementById('library-fulltext-search-btn')?.addEventListener('click', handleLibraryFulltextSearch);
    document.getElementById('library-fulltext-query')?.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleLibraryFulltextSearch();
        }
    });
    document.getElementById('library-fulltext-scope')?.addEventListener('change', function() {
        currentLibraryFulltextScope = this.value || 'selected_papers';
    });
    document.getElementById('library-import-metadata-btn')?.addEventListener('click', function() {
        const picker = document.getElementById('library-metadata-file-picker');
        if (!picker) return;
        picker.value = '';
        picker.click();
    });
    document.getElementById('library-metadata-file-picker')?.addEventListener('change', handleLibraryMetadataFilePicked);
    document.getElementById('library-create-paper-btn')?.addEventListener('click', openLibraryMetadataModal);
    document.getElementById('library-metadata-form')?.addEventListener('submit', submitManualLibraryPaper);
    document.querySelectorAll('[data-library-metadata-close]').forEach(element => {
        element.addEventListener('click', closeLibraryMetadataModal);
    });
    document.getElementById('library-metadata-modal')?.addEventListener('keydown', function(event) {
        trapManagedModalFocus(event, this);
        if (event.key === 'Escape' && this.classList.contains('is-open')) {
            closeLibraryMetadataModal();
        }
    });
    document.getElementById('create-collection-btn')?.addEventListener('click', createLibraryCollection);
    document.querySelectorAll('input[name="selected-source"]').forEach(input => {
        input.addEventListener('change', updateDatabaseCredentialPanel);
    });
    document.addEventListener('click', handleDocumentClickForPathOptions);
    document.addEventListener('click', handleTrendEvidenceClick);
}

function toggleModuleSection(sectionName) {
    const targetPanel = document.getElementById(`${sectionName}-collapse`);
    const targetTab = document.querySelector(`.module-tab[data-module-tab="${sectionName}"]`);
    if (!targetPanel || !targetTab) return;

    if (!targetTab.classList.contains('active') || !targetPanel.classList.contains('show')) {
        showControlSection(sectionName);
        return;
    }

    targetPanel.classList.remove('show');
    targetTab.setAttribute('aria-expanded', 'false');
    updateModuleTabChevron(targetTab, false);

    const targetButton = document.querySelector(`[data-bs-target="#${sectionName}-collapse"]`);
    if (targetButton) {
        targetButton.classList.add('collapsed');
        targetButton.setAttribute('aria-expanded', 'false');
    }
}

function updateModuleTabChevron(tab, expanded) {
    const icon = tab?.querySelector('.module-tab-chevron');
    if (!icon) return;
    icon.classList.toggle('fa-chevron-up', expanded);
    icon.classList.toggle('fa-chevron-down', !expanded);
}

function showControlSection(sectionName, syncUrl = true) {
    const sectionMap = {
        search: '#search-collapse',
        report: '#report-collapse',
        graph: '#graph-collapse',
        trend: '#trend-collapse'
    };
    const targetSelector = sectionMap[sectionName] || sectionMap.search;

    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.getAttribute('data-tab') === sectionName);
    });

    document.querySelectorAll('.module-tab').forEach(tab => {
        const isActive = tab.getAttribute('data-module-tab') === sectionName;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        tab.setAttribute('aria-expanded', isActive ? 'true' : 'false');
        updateModuleTabChevron(tab, isActive);
    });

    document.querySelectorAll('.accordion-collapse').forEach(panel => {
        panel.classList.remove('show');
    });
    document.querySelectorAll('.accordion-button').forEach(button => {
        button.classList.add('collapsed');
        button.setAttribute('aria-expanded', 'false');
    });

    const targetPanel = document.querySelector(targetSelector);
    if (targetPanel) {
        targetPanel.classList.add('show');
    }
    const targetButton = document.querySelector(`[data-bs-target="${targetSelector}"]`);
    if (targetButton) {
        targetButton.classList.remove('collapsed');
        targetButton.setAttribute('aria-expanded', 'true');
    }
    if (syncUrl) updateWorkspaceUrl({ module: sectionName }, false);
}

function toggleAccordion(targetSelector, button) {
    const panel = document.querySelector(targetSelector);
    if (!panel) return;

    const nextVisible = !panel.classList.contains('show');
    panel.classList.toggle('show', nextVisible);
    button.classList.toggle('collapsed', !nextVisible);
    button.setAttribute('aria-expanded', nextVisible ? 'true' : 'false');

    const sectionName = targetSelector.replace('#', '').replace('-collapse', '');
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.getAttribute('data-tab') === sectionName && nextVisible);
    });
    document.querySelectorAll('.module-tab').forEach(tab => {
        const isActive = tab.getAttribute('data-module-tab') === sectionName && nextVisible;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
}

function updatePreviewTabChevron(tab, expanded) {
    const icon = tab?.querySelector('.preview-tab-chevron');
    if (!icon) return;
    icon.classList.toggle('fa-chevron-up', expanded);
    icon.classList.toggle('fa-chevron-down', !expanded);
}

function playPreviewSwitchMotion(previewPanel) {
    if (!previewPanel || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    window.clearTimeout(previewSwitchMotionTimer);
    previewPanel.classList.remove('is-tab-switching');
    window.requestAnimationFrame(() => {
        previewPanel.classList.add('is-tab-switching');
        previewSwitchMotionTimer = window.setTimeout(() => {
            previewPanel.classList.remove('is-tab-switching');
        }, 300);
    });
}

function togglePreviewSection(tabName) {
    const previewPanel = document.querySelector('.preview-panel');
    const targetButton = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (!previewPanel || !targetButton) return;

    const isExpanded = targetButton.classList.contains('active') && !previewPanel.classList.contains('is-collapsed');
    if (!isExpanded) {
        showPreviewTab(tabName);
        return;
    }

    previewPanel.classList.add('is-collapsed');
    targetButton.setAttribute('aria-expanded', 'false');
    updatePreviewTabChevron(targetButton, false);
}

// 显示预览标签
function showPreviewTab(tabName, syncUrl = true) {
    const previewPanel = document.querySelector('.preview-panel');
    const updatePreviewState = () => {
        previewPanel?.classList.remove('is-collapsed');

        // 更新标签按钮状态
        document.querySelectorAll('.tab-btn').forEach(btn => {
            const isActive = btn.getAttribute('data-tab') === tabName;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
            btn.setAttribute('aria-expanded', isActive ? 'true' : 'false');
            updatePreviewTabChevron(btn, isActive);
        });

        // 显示对应的预览内容
        document.querySelectorAll('.preview-tab').forEach(tab => {
            tab.classList.remove('active');
        });
        const targetPreview = document.getElementById(`${tabName}-preview`);
        if (targetPreview) {
            targetPreview.classList.add('active');
        }
    };
    updatePreviewState();
    if (syncUrl) playPreviewSwitchMotion(previewPanel);
    if (tabName === 'library') {
        loadLibraryPapers(currentLibraryPage || 1, false);
    } else if (tabName === 'collections') {
        loadLibraryCollections(true);
    }
    if (syncUrl) {
        updateWorkspaceUrl({
            preview: tabName,
            library_page: tabName === 'library' ? String(currentLibraryPage || 1) : '',
        }, false);
    }
}

// 添加查询字段
function addQueryField() {
    const queryList = document.getElementById('query-list');
    const queryCount = queryList.children.length;
    
    const queryItem = document.createElement('div');
    queryItem.className = 'query-item';
    queryItem.innerHTML = `
        <input type="text" class="form-control query-input" name="queries[]" aria-label="检索词 ${queryCount + 1}" placeholder="请输入检索词…" autocomplete="off">
        <button type="button" class="btn btn-secondary remove-query" aria-label="删除检索词 ${queryCount + 1}" title="删除检索词">
            <i class="fas fa-times" aria-hidden="true"></i>
        </button>
    `;
    
    queryList.appendChild(queryItem);
}

// 移除查询字段
function removeQueryField(button) {
    const queryList = document.getElementById('query-list');
    if (queryList.children.length > 1) {
        button.closest('.query-item').remove();
    } else {
        // 如果只剩一个字段，清空内容而不是移除
        button.closest('.query-item').querySelector('input').value = '';
    }
}

// 加载初始数据
function loadInitialData() {
    const data = window.INITIAL_DATA || {};
    
    // 设置查询词
    const queries = data.queries || [''];
    const queryList = document.getElementById('query-list');
    queryList.innerHTML = '';
    
    queries.forEach((query, index) => {
        const queryItem = document.createElement('div');
        queryItem.className = 'query-item';
        queryItem.innerHTML = `
            <input type="text" class="form-control query-input" name="queries[]" aria-label="检索词 ${index + 1}" placeholder="请输入检索词…" value="${escapeAttribute(query)}" autocomplete="off">
            <button type="button" class="btn btn-secondary remove-query" aria-label="删除检索词 ${index + 1}" title="删除检索词">
                <i class="fas fa-times" aria-hidden="true"></i>
            </button>
        `;
        queryList.appendChild(queryItem);
    });
    
    // 设置操作符
    document.getElementById('query-operator').value = data.operator || '与 (AND)';
    
    // 设置访问密钥
    document.getElementById('api-key').value = data.api_key || '';
    document.getElementById('openalex-email').value = '';
    document.getElementById('crossref-email').value = '';
    document.getElementById('pubmed-api-key').value = '';
    document.getElementById('pubmed-email').value = '';
    document.getElementById('springer-nature-api-key').value = '';

    const selectedSources = Array.isArray(data.selected_sources)
        ? data.selected_sources
        : DEFAULT_METADATA_SOURCES;
    document.querySelectorAll('input[name="selected-source"]').forEach(input => {
        input.checked = selectedSources.includes(input.value);
    });
    updateDatabaseCredentialPanel();
    
    // 设置限制和休眠时间
    document.getElementById('limit-per-query').value = data.limit_per_query || '10';
    document.getElementById('sleep-each-req').value = data.sleep_each_req || '1.0';
    
    // 设置配置
    const config = data.config || {};
    document.getElementById('output-dir').value = config.output_dir || '';
    document.getElementById('llm-provider').value = config.llm_provider || 'openai_compatible';
    document.getElementById('ollama-base-url').value = config.llm_base_url || config.ollama_base_url || '';
    document.getElementById('llm-api-key').value = config.llm_api_key || '';
    document.getElementById('model').value = config.model || '';
    document.getElementById('graph-llm-provider').value = config.graph_llm_provider || 'openai_compatible';
    document.getElementById('graph-llm-base-url').value = config.graph_llm_base_url || '';
    document.getElementById('graph-llm-api-key').value = config.graph_llm_api_key || '';
    document.getElementById('graph-llm-model').value = config.graph_llm_model || '';
    document.getElementById('max-papers').value = config.max_papers_for_llm || '10';
    document.getElementById('report-style').value = config.report_style || '科研日报';
    document.getElementById('report-data-source').value = config.report_data_source || 'csv';
    reportSettingsState.report_collection_id = config.report_collection_id || '';
    document.getElementById('report-input-mode').value = config.report_input_mode || 'abstract_only';
    document.getElementById('temperature').value = config.temperature || '0.7';
    document.getElementById('top-p').value = config.top_p || '0.9';
    document.getElementById('num-predict').value = config.num_predict || '8000';
    document.getElementById('max-retry').value = config.max_retry || '3';
    document.getElementById('topic-override').value = config.topic_override || '';
    document.getElementById('min-chars').value = config.min_research_content_chars || '500';
    document.getElementById('keep-empty-abstract').checked = config.keep_empty_abstract || false;
    document.getElementById('save-debug-files').checked = config.save_debug_files || false;
    updateReportSourceControls();
}

// 处理搜索表单提交
async function handleSearch(e) {
    e.preventDefault();
    
    const formData = getSearchFormData();
    if (!ensureDatabaseSelected(formData)) return;
    
    try {
        showLoading(true, 'search-btn');
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            addLog(`搜索任务已启动，任务ID: ${result.task_id}`);
            startTaskPolling(result.task_id);
        } else {
            addLog(`搜索失败: ${result.error}`, 'error');
        }
    } catch (error) {
        addLog(`搜索请求失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'search-btn');
    }
}

// 获取搜索表单数据
function getSearchFormData() {
    const queries = [];
    document.querySelectorAll('.query-input').forEach(input => {
        if (input.value.trim()) {
            queries.push(input.value.trim());
        }
    });
    
    return {
        queries: queries,
        operator: document.getElementById('query-operator').value,
        limit_per_query: document.getElementById('limit-per-query').value,
        sleep_each_req: document.getElementById('sleep-each-req').value,
        api_key: document.getElementById('api-key').value,
        source_credentials: getSourceCredentials(),
        start_date: document.getElementById('start-date').value,
        end_date: document.getElementById('end-date').value,
        selected_sources: getSelectedSources()
    };
}

function getSelectedSources() {
    const sources = [];
    document.querySelectorAll('input[name="selected-source"]:checked').forEach(input => {
        sources.push(input.value);
    });
    return sources;
}

function getSourceCredentials() {
    return {
        semantic_scholar_api_key: document.getElementById('api-key').value.trim(),
        openalex_email: document.getElementById('openalex-email').value.trim(),
        crossref_email: document.getElementById('crossref-email').value.trim(),
        pubmed_api_key: document.getElementById('pubmed-api-key').value.trim(),
        pubmed_email: document.getElementById('pubmed-email').value.trim(),
        springer_nature_api_key: document.getElementById('springer-nature-api-key').value.trim(),
        springer_nature_api_type: document.getElementById('springer-nature-api-type')?.value || 'openaccess'
    };
}

function updateDatabaseCredentialPanel() {
    const selectedSources = getSelectedSources();
    const selectedSet = new Set(selectedSources);

    document.querySelectorAll('.credential-field').forEach(field => {
        const source = field.getAttribute('data-credential-source');
        field.classList.toggle('active', selectedSet.has(source));
    });

    const alert = document.getElementById('credential-alert');
    if (!alert) return;
    if (selectedSources.length === 0) {
        alert.textContent = '请至少选择一个文献数据库。';
        return;
    }
    alert.textContent = selectedSources
        .map(source => databaseCredentialHints[source])
        .filter(Boolean)
        .join(' ');
}

function ensureDatabaseSelected(formData) {
    if (formData.selected_sources && formData.selected_sources.length > 0) {
        return true;
    }
    addLog('请至少选择一个文献数据库', 'warning');
    showPreviewTab('log');
    return false;
}

// 处理生成表单提交
async function handleGenerate(e) {
    e.preventDefault();
    
    const formData = getReportFormData();
    if (!ensureReportSourceConfig(formData)) return;
    if (!ensureReportModelConfig(formData)) return;
    const summaryReady = await refreshReportSourceSummary();
    if (!summaryReady || !reportSourceSummaryState.can_generate) return;
    
    let taskStarted = false;
    try {
        showLoading(true, 'generate-btn');
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            taskStarted = true;
            addLog(`生成任务已启动，任务ID: ${result.task_id}`);
            startTaskPolling(result.task_id, 'report');
        } else {
            addLog(`生成失败: ${result.error}`, 'error');
        }
    } catch (error) {
        addLog(`生成请求失败: ${error.message}`, 'error');
    } finally {
        if (!taskStarted) {
            showLoading(false, 'generate-btn');
            syncReportGenerateButton();
        }
    }
}

// 获取报告表单数据
function getReportFormData() {
    return {
        report_data_source: document.getElementById('report-data-source')?.value || 'csv',
        report_collection_id: document.getElementById('report-collection-select')?.value || '',
        input_csv: document.getElementById('input-csv').value,
        output_dir: document.getElementById('output-dir').value,
        llm_provider: document.getElementById('llm-provider').value,
        ollama_base_url: document.getElementById('ollama-base-url').value,
        llm_base_url: document.getElementById('ollama-base-url').value,
        llm_api_key: document.getElementById('llm-api-key').value,
        model: document.getElementById('model').value,
        max_papers_for_llm: document.getElementById('max-papers').value,
        report_style: document.getElementById('report-style').value,
        report_input_mode: document.getElementById('report-input-mode').value,
        temperature: document.getElementById('temperature').value,
        top_p: document.getElementById('top-p').value,
        num_predict: document.getElementById('num-predict').value,
        max_retry: document.getElementById('max-retry').value,
        topic_override: document.getElementById('topic-override').value,
        min_research_content_chars: document.getElementById('min-chars').value,
        keep_empty_abstract: document.getElementById('keep-empty-abstract').checked,
        save_debug_files: document.getElementById('save-debug-files').checked
    };
}

function ensureReportSourceConfig(formData, silent = false) {
    if (formData.report_data_source === 'csv' && !String(formData.input_csv || '').trim()) {
        if (!silent) {
            addLog('请先选择一个 CSV 数据集。', 'warning');
            document.getElementById('search-file-list')?.focus();
        }
        return false;
    }
    if (formData.report_data_source === 'collection' && !String(formData.report_collection_id || '').trim()) {
        if (!silent) {
            addLog('请先选择一个文献主题库。', 'warning');
            document.getElementById('report-collection-select')?.focus();
        }
        return false;
    }
    return true;
}

function updateReportSourceControls() {
    const source = document.getElementById('report-data-source')?.value || 'csv';
    document.querySelectorAll('[data-report-source-panel]').forEach(panel => {
        panel.hidden = panel.dataset.reportSourcePanel !== source;
    });
    reportSourceSummaryState.ready = false;
    reportSourceSummaryState.can_generate = false;
    syncReportGenerateButton();
    scheduleReportSourceSummary();
}

function scheduleReportSourceSummary() {
    if (reportSourceSummaryTimer) window.clearTimeout(reportSourceSummaryTimer);
    reportSourceSummaryTimer = window.setTimeout(() => refreshReportSourceSummary(), 180);
}

function setReportSourceSummaryLoading() {
    const summary = document.getElementById('report-source-summary');
    if (summary) summary.dataset.state = 'loading';
    const label = document.getElementById('report-source-summary-label');
    const message = document.getElementById('report-source-summary-message');
    if (label) label.textContent = '正在检查所选数据';
    if (message) message.textContent = '正在统计摘要、全文和证据片段，请稍候。';
}

function renderReportSourceSummary(data) {
    const summary = document.getElementById('report-source-summary');
    if (summary) summary.dataset.state = data.can_generate ? 'ready' : 'warning';
    const values = {
        'report-source-paper-count': data.paper_count,
        'report-source-abstract-count': data.abstract_count,
        'report-source-fulltext-count': data.fulltext_paper_count,
        'report-source-chunk-count': data.chunk_count,
        'report-source-usable-count': data.usable_count,
    };
    Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = Number(value || 0).toLocaleString('zh-CN');
    });
    const label = document.getElementById('report-source-summary-label');
    if (label) label.textContent = data.source_label || '所选文献';
    const mappings = Object.entries(data.column_mappings || {});
    const mappingText = mappings.length
        ? `已识别列名：${mappings.map(([source, target]) => `${source}→${target}`).join('，')}。`
        : '';
    const message = document.getElementById('report-source-summary-message');
    if (message) {
        message.textContent = data.warning
            ? `${data.warning}。${mappingText}`
            : `${mappingText}当前证据范围可使用 ${data.usable_count || 0} 篇文献。`;
    }
}

function renderReportSourceSummaryError(messageText) {
    const summary = document.getElementById('report-source-summary');
    if (summary) summary.dataset.state = 'error';
    ['report-source-paper-count', 'report-source-abstract-count', 'report-source-fulltext-count', 'report-source-chunk-count', 'report-source-usable-count']
        .forEach(id => {
            const element = document.getElementById(id);
            if (element) element.textContent = '--';
        });
    const label = document.getElementById('report-source-summary-label');
    const message = document.getElementById('report-source-summary-message');
    if (label) label.textContent = '数据检查未通过';
    if (message) message.textContent = messageText || '请重新选择文献来源。';
}

function syncReportGenerateButton() {
    const button = document.getElementById('generate-btn');
    if (!button || button.dataset.loading === 'true') return;
    button.disabled = !reportSourceSummaryState.ready || !reportSourceSummaryState.can_generate;
}

async function refreshReportSourceSummary() {
    if (reportSourceSummaryTimer) {
        window.clearTimeout(reportSourceSummaryTimer);
        reportSourceSummaryTimer = null;
    }
    const formData = getReportFormData();
    if (!ensureReportSourceConfig(formData, true)) {
        reportSourceSummaryState = { ...reportSourceSummaryState, ready: false, can_generate: false };
        renderReportSourceSummaryError('请选择可用的文献来源。');
        syncReportGenerateButton();
        return false;
    }

    const requestId = reportSourceSummaryState.request_id + 1;
    reportSourceSummaryState = { ready: false, can_generate: false, request_id: requestId };
    setReportSourceSummaryLoading();
    syncReportGenerateButton();
    try {
        const response = await fetch('/api/report/source-summary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        });
        const result = await response.json();
        if (requestId !== reportSourceSummaryState.request_id) return false;
        if (!response.ok) throw new Error(result.error || '数据检查失败');
        reportSourceSummaryState = {
            ready: true,
            can_generate: Boolean(result.can_generate),
            request_id: requestId,
            data: result,
        };
        renderReportSourceSummary(result);
        syncReportGenerateButton();
        return true;
    } catch (error) {
        if (requestId !== reportSourceSummaryState.request_id) return false;
        reportSourceSummaryState = { ready: false, can_generate: false, request_id: requestId };
        renderReportSourceSummaryError(error.message);
        syncReportGenerateButton();
        return false;
    }
}

function ensureReportModelConfig(formData) {
    const serviceUrl = String(formData.llm_base_url || formData.ollama_base_url || '').trim();
    const modelName = String(formData.model || '').trim();
    if (!serviceUrl) {
        addLog('请先填写模型服务地址。', 'warning');
        showPreviewTab('log');
        const urlInput = document.getElementById('ollama-base-url');
        if (urlInput) {
            urlInput.focus();
        }
        return false;
    }
    if (!modelName) {
        addLog('请先填写模型名称。', 'warning');
        showPreviewTab('log');
        const modelInput = document.getElementById('model');
        if (modelInput) {
            modelInput.focus();
        }
        return false;
    }
    if (
        formData.llm_provider === 'openai_compatible'
        && !String(formData.llm_api_key || '').trim()
        && !reportSettingsState.has_api_key
    ) {
        addLog('请先填写大模型访问密钥，或把接口类型切换为本地 Ollama 模型。', 'warning');
        showPreviewTab('log');
        const apiKeyInput = document.getElementById('llm-api-key');
        if (apiKeyInput) {
            apiKeyInput.focus();
        }
        return false;
    }
    return true;
}

function toggleLlmApiKeyVisibility() {
    togglePasswordVisibility('llm-api-key', 'toggle-llm-api-key', '访问密钥');
}

function toggleGraphLlmApiKeyVisibility() {
    togglePasswordVisibility('graph-llm-api-key', 'toggle-graph-llm-api-key', '图谱模型访问密钥');
}

function applyReportSettings(settings = {}) {
    reportSettingsState = { ...reportSettingsState, ...settings };
    const fieldValues = {
        'llm-provider': settings.llm_provider,
        'ollama-base-url': settings.llm_base_url,
        'model': settings.model,
        'max-papers': settings.max_papers_for_llm,
        'report-style': settings.report_style,
        'report-data-source': settings.report_data_source,
        'report-input-mode': settings.report_input_mode,
        'temperature': settings.temperature,
        'top-p': settings.top_p,
        'num-predict': settings.num_predict,
        'max-retry': settings.max_retry,
        'topic-override': settings.topic_override,
        'min-chars': settings.min_research_content_chars,
    };
    Object.entries(fieldValues).forEach(([id, value]) => {
        const field = document.getElementById(id);
        if (field && value !== undefined && value !== null && value !== '') {
            field.value = String(value);
        }
    });

    if (settings.report_collection_id) {
        reportSettingsState.report_collection_id = settings.report_collection_id;
    }
    updateReportSourceControls();

    const keepEmpty = document.getElementById('keep-empty-abstract');
    if (keepEmpty && settings.keep_empty_abstract !== undefined) {
        keepEmpty.checked = Boolean(settings.keep_empty_abstract);
    }
    const saveDebug = document.getElementById('save-debug-files');
    if (saveDebug && settings.save_debug_files !== undefined) {
        saveDebug.checked = Boolean(settings.save_debug_files);
    }

    const keyInput = document.getElementById('llm-api-key');
    if (keyInput) {
        keyInput.value = '';
        keyInput.placeholder = settings.has_api_key
            ? '已安全保存；留空表示继续使用'
            : '使用远程大模型接口时需要填写';
    }
    const status = document.getElementById('report-config-status');
    if (status) {
        status.textContent = settings.has_api_key ? '综述参数已保存，访问密钥已保存到本机' : '综述参数尚未保存访问密钥';
        status.classList.toggle('is-saved', Boolean(settings.has_api_key));
    }
}

async function loadReportSettings() {
    try {
        const response = await fetch('/api/report/settings');
        const settings = await response.json();
        if (!response.ok) throw new Error(settings.error || '读取失败');
        applyReportSettings(settings);
    } catch (error) {
        addLog(`读取综述参数失败: ${error.message}`, 'warning', { toast: false });
    }
}

function getReportSettingsFormData() {
    return {
        llm_provider: document.getElementById('llm-provider')?.value || 'openai_compatible',
        llm_base_url: document.getElementById('ollama-base-url')?.value || '',
        llm_api_key: document.getElementById('llm-api-key')?.value || '',
        model: document.getElementById('model')?.value || '',
        max_papers_for_llm: document.getElementById('max-papers')?.value || '15',
        report_style: document.getElementById('report-style')?.value || '科研日报',
        report_data_source: document.getElementById('report-data-source')?.value || 'csv',
        report_collection_id: document.getElementById('report-collection-select')?.value || '',
        report_input_mode: document.getElementById('report-input-mode')?.value || 'abstract_only',
        temperature: document.getElementById('temperature')?.value || '0',
        top_p: document.getElementById('top-p')?.value || '0.9',
        num_predict: document.getElementById('num-predict')?.value || '6000',
        max_retry: document.getElementById('max-retry')?.value || '3',
        topic_override: document.getElementById('topic-override')?.value || '',
        min_research_content_chars: document.getElementById('min-chars')?.value || '350',
        keep_empty_abstract: document.getElementById('keep-empty-abstract')?.checked || false,
        save_debug_files: document.getElementById('save-debug-files')?.checked || false,
        preserve_api_key: true,
    };
}

async function saveReportSettings() {
    const button = document.getElementById('save-report-config-btn');
    try {
        if (button) button.disabled = true;
        const response = await fetch('/api/report/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(getReportSettingsFormData()),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '保存失败');
        applyReportSettings(result.settings || {});
        addLog(result.message || '综述参数已保存', 'success');
    } catch (error) {
        addLog(`保存综述参数失败: ${error.message}`, 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

function applyGraphSettings(settings = {}) {
    graphSettingsState = { ...graphSettingsState, ...settings };
    const fieldValues = {
        'graph-mode-select': settings.mode,
        'graph-input-source-select': settings.input_source,
        'graph-max-chunks': settings.max_chunks_per_paper,
        'graph-llm-provider': settings.llm_provider,
        'graph-llm-base-url': settings.llm_base_url,
        'graph-llm-model': settings.model,
    };
    Object.entries(fieldValues).forEach(([id, value]) => {
        const field = document.getElementById(id);
        if (field && value !== undefined && value !== null && value !== '') {
            field.value = String(value);
        }
    });

    const keyInput = document.getElementById('graph-llm-api-key');
    if (keyInput) {
        keyInput.value = '';
        keyInput.placeholder = settings.has_api_key
            ? '已安全保存；留空表示继续使用'
            : '仅图谱增强使用';
    }
    const status = document.getElementById('graph-config-status');
    if (status) {
        status.textContent = settings.has_api_key ? '访问密钥已保存到本机' : '访问密钥尚未保存';
        status.classList.toggle('is-saved', Boolean(settings.has_api_key));
    }
}

async function loadGraphSettings() {
    try {
        const response = await fetch('/api/knowledge-graph/settings');
        const settings = await response.json();
        if (!response.ok) throw new Error(settings.error || '读取失败');
        applyGraphSettings(settings);
    } catch (error) {
        addLog(`读取知识图谱配置失败: ${error.message}`, 'warning', { toast: false });
    }
}

function getGraphSettingsFormData() {
    return {
        mode: document.getElementById('graph-mode-select')?.value || 'hybrid',
        input_source: document.getElementById('graph-input-source-select')?.value || 'abstract',
        max_chunks_per_paper: document.getElementById('graph-max-chunks')?.value || '20',
        llm_provider: document.getElementById('graph-llm-provider')?.value || 'openai_compatible',
        llm_base_url: document.getElementById('graph-llm-base-url')?.value || '',
        llm_api_key: document.getElementById('graph-llm-api-key')?.value || '',
        model: document.getElementById('graph-llm-model')?.value || '',
        preserve_api_key: true,
    };
}

async function saveGraphSettings() {
    const button = document.getElementById('save-graph-config-btn');
    try {
        if (button) button.disabled = true;
        const response = await fetch('/api/knowledge-graph/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(getGraphSettingsFormData()),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '保存失败');
        applyGraphSettings(result.settings || {});
        addLog(result.message || '知识图谱配置已保存', 'success');
    } catch (error) {
        addLog(`保存知识图谱配置失败: ${error.message}`, 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

function togglePasswordVisibility(inputId, buttonId, label) {
    const input = document.getElementById(inputId);
    const button = document.getElementById(buttonId);
    if (!input || !button) return;

    const shouldShow = input.type === 'password';
    input.type = shouldShow ? 'text' : 'password';
    button.setAttribute('aria-label', shouldShow ? `隐藏 ${label}` : `显示 ${label}`);
    button.setAttribute('title', shouldShow ? `隐藏 ${label}` : `显示 ${label}`);

    const icon = button.querySelector('i');
    if (icon) {
        icon.classList.toggle('fa-eye', !shouldShow);
        icon.classList.toggle('fa-eye-slash', shouldShow);
    }
}

// 刷新文件列表
async function refreshFileList(options = {}) {
    const activatePreview = options.activatePreview !== false;
    const previewReport = options.previewReport === true;
    const previewCsv = options.previewCsv !== false;
    const preferredCsv = String(options.preferredCsv || '');
    try {
        const response = await fetch('/api/files');
        const result = await response.json();
        
        if (response.ok) {
            const searchFileList = document.getElementById('search-file-list');
            const previewCsvSelect = document.getElementById('preview-csv-select');
            const graphCsvSelect = document.getElementById('graph-csv-select');
            searchFileList.innerHTML = '';
            previewCsvSelect.innerHTML = '';
            graphCsvSelect.innerHTML = '';
            outputDirChoices = result.output_dirs || [];
            renderOutputDirOptions();

            result.search_csvs.forEach(file => {
                const option = document.createElement('option');
                option.value = file;
                option.textContent = file;
                searchFileList.appendChild(option);

                const previewOption = document.createElement('option');
                previewOption.value = file;
                previewOption.textContent = file;
                previewCsvSelect.appendChild(previewOption);

                const graphOption = document.createElement('option');
                graphOption.value = file;
                graphOption.textContent = file;
                graphCsvSelect.appendChild(graphOption);
            });

            if (result.search_csvs.length > 0) {
                const selectedCsv = result.search_csvs.includes(preferredCsv)
                    ? preferredCsv
                    : (searchFileList.value || result.search_csvs[0]);
                searchFileList.value = selectedCsv;
                previewCsvSelect.value = selectedCsv;
                graphCsvSelect.value = selectedCsv;
                document.getElementById('input-csv').value = selectedCsv;
                updateGraphScopeControls();
                if (previewCsv) {
                    await previewCSV(selectedCsv, 1, { activatePreview });
                }
            } else {
                const option = document.createElement('option');
                option.value = '';
                option.textContent = '暂无CSV文件';
                graphCsvSelect.appendChild(option);
                updateGraphScopeControls();
            }
            scheduleReportSourceSummary();
            
            // 更新报告文件列表
            const fileList = document.getElementById('report-file-list');
            const previousReportFile = fileList.value;
            fileList.innerHTML = '';
            
            result.output_files.forEach(file => {
                const option = document.createElement('option');
                option.value = file;
                option.textContent = file;
                fileList.appendChild(option);
            });

            if (result.output_files.length > 0) {
                fileList.value = result.output_files.includes(previousReportFile)
                    ? previousReportFile
                    : result.output_files[0];
            }
            if (previewReport && fileList.value) {
                await handleFileSelection();
            }
            
            addLog(`刷新文件列表完成，找到 ${result.search_csvs.length} 个CSV和 ${result.output_files.length} 个输出文件`);
        } else {
            addLog(`刷新文件列表失败: ${result.error}`, 'error');
        }
    } catch (error) {
        addLog(`刷新文件列表请求失败: ${error.message}`, 'error');
    }
}

function renderOutputDirOptions() {
    const optionsPanel = document.getElementById('output-dir-options');
    if (!optionsPanel) return;

    optionsPanel.innerHTML = '';
    const scrollContent = document.createElement('div');
    scrollContent.className = 'path-option-scroll';

    outputDirChoices.forEach(dir => {
        const optionButton = document.createElement('button');
        optionButton.type = 'button';
        optionButton.className = 'path-option';
        optionButton.textContent = dir;
        optionButton.title = dir;
        optionButton.addEventListener('click', () => {
            document.getElementById('output-dir').value = dir;
            hideOutputDirOptions();
        });
        scrollContent.appendChild(optionButton);
    });

    optionsPanel.appendChild(scrollContent);
}

function showOutputDirOptions() {
    const optionsPanel = document.getElementById('output-dir-options');
    if (!optionsPanel || outputDirChoices.length === 0) return;
    renderOutputDirOptions();
    optionsPanel.hidden = false;
}

function hideOutputDirOptions() {
    const optionsPanel = document.getElementById('output-dir-options');
    if (optionsPanel) {
        optionsPanel.hidden = true;
    }
}

function handleDocumentClickForPathOptions(event) {
    const combobox = document.querySelector('.path-combobox');
    if (combobox && !combobox.contains(event.target)) {
        hideOutputDirOptions();
    }
}

async function handleSearchFileSelection() {
    const selectedFile = document.getElementById('search-file-list').value;
    if (!selectedFile) return;

    document.getElementById('input-csv').value = selectedFile;
    document.getElementById('preview-csv-select').value = selectedFile;
    document.getElementById('graph-csv-select').value = selectedFile;
    await previewCSV(selectedFile, 1);
    scheduleReportSourceSummary();
}

async function handlePreviewCsvSelection() {
    const selectedFile = document.getElementById('preview-csv-select').value;
    if (!selectedFile) return;

    document.getElementById('input-csv').value = selectedFile;
    document.getElementById('search-file-list').value = selectedFile;
    document.getElementById('graph-csv-select').value = selectedFile;
    await previewCSV(selectedFile, 1);
    scheduleReportSourceSummary();
}

async function handleOpenPreviewCsvFile() {
    const selectedFile = document.getElementById('preview-csv-select').value;
    if (!selectedFile) return;

    try {
        const response = await fetch('/api/open_file', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ path: selectedFile })
        });
        const result = await response.json();
        if (response.ok) {
            addLog(`已用本地应用打开: ${selectedFile}`);
        } else {
            addLog(`打开CSV文件失败: ${result.error || '未知错误'}`, 'error');
        }
    } catch (error) {
        addLog(`打开CSV文件失败: ${error.message}`, 'error');
    }
}

function handleGraphCsvSelection() {
    const selectedFile = document.getElementById('graph-csv-select').value;
    if (!selectedFile) return;

    document.getElementById('input-csv').value = selectedFile;
    document.getElementById('search-file-list').value = selectedFile;
    document.getElementById('preview-csv-select').value = selectedFile;
    document.getElementById('graph-info').textContent = `${selectedFile} · 等待生成`;
}

function updateGraphScopeControls() {
    const dataSource = document.getElementById('graph-data-source-select')?.value || 'csv';
    const scope = dataSource === 'library' ? 'library' : 'topic';
    const topicSource = dataSource === 'collection' ? 'collection' : 'csv';
    const csvSelect = document.getElementById('graph-csv-select');
    const collectionSelect = document.getElementById('graph-collection-select');
    if (!csvSelect) return;
    renderGraphCollectionOptions();
    if (collectionSelect) {
        collectionSelect.disabled = scope === 'library' || topicSource !== 'collection' || currentCollections.length === 0;
    }
    csvSelect.disabled = scope === 'library' || topicSource === 'collection';
    csvSelect.title = scope === 'library'
        ? '全库图谱将从 literature_library.sqlite 构建'
        : (topicSource === 'collection' ? '主题库图谱将使用所选文献主题库' : '主题库图谱将使用当前 CSV');
    const selectedFile = csvSelect.value || document.getElementById('input-csv')?.value || '';
    const selectedCollection = currentCollections.find(item => item.collection_id === (collectionSelect?.value || currentCollectionId));
    const info = document.getElementById('graph-info');
    if (info) {
        info.textContent = scope === 'library'
            ? '全库 · literature_library.sqlite · 等待生成'
            : (topicSource === 'collection'
                ? `文献主题库 · ${selectedCollection?.name || '未选择主题库'} · 等待生成`
                : `${selectedFile || '未选择数据集'} · 等待生成`);
    }
}

function renderGraphCollectionOptions() {
    const select = document.getElementById('graph-collection-select');
    if (!select) return;
    const previous = select.value || currentCollectionId;
    if (!currentCollections.length) {
        select.innerHTML = '<option value="">暂无文献主题库</option>';
        return;
    }
    select.innerHTML = currentCollections.map(collection => `
        <option value="${escapeAttribute(collection.collection_id)}">
            ${escapeHtml(collection.name)} (${escapeHtml(collection.paper_count || 0)}篇)
        </option>
    `).join('');
    const nextValue = currentCollections.some(item => item.collection_id === previous)
        ? previous
        : currentCollections[0].collection_id;
    select.value = nextValue;
}

async function previewReportFile(filePath) {
    const selectedFile = filePath || document.getElementById('report-file-list').value;
    if (!selectedFile) return;
    
    try {
        const response = await fetch(`/api/preview?path=${encodeURIComponent(selectedFile)}`);
        const result = await response.json();
        
        if (response.ok) {
            const reportInfo = document.getElementById('report-info');
            reportInfo.hidden = false;
            reportInfo.textContent = `当前文件：${selectedFile}`;
            
            if (result.type === 'text') {
                renderReportContent(selectedFile, result.content);
            } else {
                document.getElementById('report-content').innerHTML = '<p>无法预览此文件类型</p>';
            }
        } else {
            addLog(`预览文件失败: ${result.error}`, 'error');
        }
    } catch (error) {
        addLog(`预览文件请求失败: ${error.message}`, 'error');
    }
}

function showReportReadyState(reportPath) {
    const reportInfo = document.getElementById('report-info');
    const reportContent = document.getElementById('report-content');
    if (reportInfo) {
        reportInfo.hidden = false;
        reportInfo.textContent = `当前文件：${reportPath}`;
    }
    if (!reportContent) return;
    reportContent.innerHTML = `
        <div class="report-ready-panel">
            <p>综述已生成。为避免页面卡顿，系统不会自动展开全文预览。</p>
            <button type="button" class="btn btn-primary" id="preview-generated-report-btn">
                <i class="fas fa-file-lines"></i> 预览报告
            </button>
        </div>
    `;
    document.getElementById('preview-generated-report-btn')?.addEventListener('click', () => {
        previewReportFile(reportPath);
    });
}

// 处理文件选择
async function handleFileSelection() {
    await previewReportFile();
}

// 浏览本地报告文件，默认定位到当前相对路径所在目录
async function openReportLocation() {
    const currentValue = document.getElementById('report-file-list').value;

    try {
        showLoading(true, 'open-report-location');
        const response = await fetch('/api/select_report_file', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ current_report: currentValue })
        });
        const result = await response.json();

        if (result.cancelled) {
            return;
        }
        if (!response.ok) {
            addLog(`综述文件选择失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        const reportPath = result.report_path;
        const reportFileList = document.getElementById('report-file-list');
        if (![...reportFileList.options].some(option => option.value === reportPath)) {
            const option = document.createElement('option');
            option.value = reportPath;
            option.textContent = reportPath;
            reportFileList.prepend(option);
        }
        reportFileList.value = reportPath;
        await previewReportFile(reportPath);
        showPreviewTab('report');
        addLog(`已选择本地综述文件: ${reportPath}`);
    } catch (error) {
        addLog(`综述文件选择失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'open-report-location');
    }
}

function handleReportFilePicked(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const reportInfo = document.getElementById('report-info');
    const reportContent = document.getElementById('report-content');
    reportInfo.textContent = file.name;

    const lowerName = file.name.toLowerCase();
    if (lowerName.endsWith('.pdf') || file.type === 'application/pdf') {
        const objectUrl = URL.createObjectURL(file);
        reportContent.innerHTML = `<iframe class="pdf-preview" src="${escapeAttribute(objectUrl)}" title="${escapeAttribute(file.name)}"></iframe>`;
        showPreviewTab('report');
        event.target.value = '';
        return;
    }

    const reader = new FileReader();
    reader.onload = function() {
        renderReportContent(file.name, reader.result || '');
        showPreviewTab('report');
        addLog(`已打开本地综述文件: ${file.name}`);
    };
    reader.onerror = function() {
        addLog(`读取本地综述文件失败: ${file.name}`, 'error');
    };
    reader.readAsText(file, 'utf-8');
    event.target.value = '';
}

function renderReportContent(fileName, content) {
    const reportContent = document.getElementById('report-content');
    if (isMarkdownFile(fileName)) {
        reportContent.innerHTML = `<article class="markdown-preview">${renderMarkdownDocument(content)}</article>`;
        typesetMarkdownMath(reportContent);
    } else {
        reportContent.innerHTML = `<pre>${escapeHtml(content)}</pre>`;
    }
}

function isMarkdownFile(fileName) {
    return /\.(md|markdown)$/i.test(String(fileName || '').split('?')[0]);
}

function normalizeMarkdownText(markdownText, options = {}) {
    const text = String(markdownText || '')
        .replace(/\r\n?/g, '\n')
        .replace(/\[\[([^\]]+?)\\?\]\]\(#page-\d+-\d+\)/g, (_match, label) => cleanMarkdownAnchorLabel(`[${label}]`))
        .replace(/\[((?:\\.|[^\]])+)\]\(#page-\d+-\d+\)/g, (_match, label) => cleanMarkdownAnchorLabel(label))
        .replace(/\(#page-\d+-\d+\)/g, '')
        .replace(/([A-Za-z])\s*-\s+(\d+(?:[-–]\d+)?\b)/g, '$1-$2')
        .replace(/^\d+\s*$/gm, '')
        .replace(/\n{3,}/g, '\n\n');
    return options.normalizeHeadings === false ? text : normalizeMarkdownHeadings(text);
}

function cleanMarkdownAnchorLabel(label) {
    let value = String(label || '')
        .replace(/\\\[/g, '[')
        .replace(/\\\]/g, ']')
        .replace(/\\(?=[\[\]().])/g, '')
        .replace(/\\/g, '')
        .trim();
    if (/^\d+(?:[-–]\d+)?$/.test(value)) {
        value = `[${value}]`;
    }
    return value;
}

function normalizeMarkdownHeadings(markdownText) {
    let seenTitle = false;
    let hasMainHeading = false;
    return String(markdownText || '').split('\n').map(line => {
        const match = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*$/);
        if (!match) return line;
        const originalLevel = match[1].length;
        const headingText = match[2].trim();
        const level = !seenTitle && !looksLikeMarkdownSectionHeading(headingText)
            ? 1
            : markdownHeadingLevelAfterTitle(headingText, originalLevel, hasMainHeading);
        if (level === 2) hasMainHeading = true;
        seenTitle = true;
        return `${'#'.repeat(level)} ${headingText}`;
    }).join('\n');
}

function markdownHeadingLevelAfterTitle(rawHeading, originalLevel, hasMainHeading = false) {
    const plain = String(rawHeading || '')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/\s+/g, ' ')
        .trim();
    const numeric = plain.match(/^(\d+(?:\.\d+)*)(?:[.)])?\s+\S+/);
    if (numeric) {
        return Math.min(2 + (numeric[1].match(/\./g) || []).length, 4);
    }
    const letter = plain.match(/^([A-Z])\.\s+(.+)/);
    if (letter && letter[2] !== letter[2].toUpperCase()) return 3;
    if (/^[IVXLCDM]+\.\s+\S+/i.test(plain)) return 2;
    if (letter) return 3;
    const normalized = plain.toLowerCase().replace(/[^a-z]+/g, ' ').trim();
    const mainSections = new Set([
        'abstract', 'introduction', 'background', 'method', 'methods', 'methodology',
        'materials and methods', 'results', 'result', 'results and discussion',
        'discussion', 'conclusion', 'conclusions', 'references',
        'acknowledgement', 'acknowledgements', 'acknowledgment', 'acknowledgments',
        'author contributions', 'declarations', 'declaration of competing interest',
        'competing interests', 'open access'
    ]);
    if (mainSections.has(normalized)) return 2;
    if (originalLevel <= 2 && !hasMainHeading) return 2;
    return 3;
}

function looksLikeMarkdownSectionHeading(rawHeading) {
    const plain = String(rawHeading || '')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/\s+/g, ' ')
        .trim();
    if (/^\d+(?:\.\d+)*(?:[.)])?\s+\S+/.test(plain)) return true;
    if (/^[IVXLCDM]+\.\s+\S+/i.test(plain)) return true;
    const normalized = plain.toLowerCase().replace(/[^a-z]+/g, ' ').trim();
    return new Set([
        'abstract', 'introduction', 'background', 'method', 'methods', 'methodology',
        'materials and methods', 'results', 'result', 'results and discussion',
        'discussion', 'conclusion', 'conclusions', 'references'
    ]).has(normalized);
}

function renderMarkdownDocument(markdownText, options = {}) {
    const lines = options.normalizeReport === false
        ? normalizeMarkdownText(markdownText, options).split('\n')
        : prepareReportMarkdownLines(markdownText);
    const html = [];
    let paragraphLines = [];
    let listType = '';
    let listStart = 1;
    let listItems = [];

    function flushParagraph() {
        if (!paragraphLines.length) return;
        html.push(`<p>${paragraphLines.map(line => parseInlineMarkdown(line, options)).join('<br>')}</p>`);
        paragraphLines = [];
    }

    function flushList() {
        if (!listItems.length) return;
        const startAttr = listType === 'ol' && listStart > 1 ? ` start="${listStart}"` : '';
        html.push(`<${listType}${startAttr}>${listItems.map(item => `<li>${parseInlineMarkdown(item, options)}</li>`).join('')}</${listType}>`);
        listType = '';
        listStart = 1;
        listItems = [];
    }

    function closeTextBlocks() {
        flushParagraph();
        flushList();
    }

    for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i];
        const trimmed = line.trim();

        if (!trimmed) {
            closeTextBlocks();
            continue;
        }

        if (trimmed.startsWith('$$')) {
            closeTextBlocks();
            const mathLines = [line];
            if (!(trimmed.length > 2 && trimmed.endsWith('$$'))) {
                i += 1;
                while (i < lines.length) {
                    mathLines.push(lines[i]);
                    if (lines[i].trim().endsWith('$$')) break;
                    i += 1;
                }
            }
            const equationNumber = collectTrailingEquationNumber(lines, i);
            if (equationNumber) i = equationNumber.endIndex;
            html.push(renderMarkdownMathBlock(mathLines.join('\n'), '$$', '$$', equationNumber ? equationNumber.label : ''));
            continue;
        }

        if (trimmed.startsWith('\\[')) {
            closeTextBlocks();
            const mathLines = [line];
            if (!trimmed.endsWith('\\]')) {
                i += 1;
                while (i < lines.length) {
                    mathLines.push(lines[i]);
                    if (lines[i].trim().endsWith('\\]')) break;
                    i += 1;
                }
            }
            const equationNumber = collectTrailingEquationNumber(lines, i);
            if (equationNumber) i = equationNumber.endIndex;
            html.push(renderMarkdownMathBlock(mathLines.join('\n'), '\\[', '\\]', equationNumber ? equationNumber.label : ''));
            continue;
        }

        const fenceMatch = trimmed.match(/^```(\S*)?/);
        if (fenceMatch) {
            closeTextBlocks();
            const language = fenceMatch[1] || '';
            const codeLines = [];
            i += 1;
            while (i < lines.length && !lines[i].trim().startsWith('```')) {
                codeLines.push(lines[i]);
                i += 1;
            }
            const languageClass = language ? ` class="language-${escapeAttribute(language)}"` : '';
            html.push(`<pre><code${languageClass}>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
            continue;
        }

        const imageMatch = parseMarkdownImageLine(trimmed);
        if (imageMatch) {
            closeTextBlocks();
            const figure = collectMarkdownFigure(lines, i);
            i = figure.endIndex;
            html.push(renderMarkdownFigure(figure.images, options, figure.caption));
            continue;
        }

        if (isMarkdownTableStart(lines, i)) {
            closeTextBlocks();
            const tableLines = [line, lines[i + 1]];
            i += 2;
            while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
                tableLines.push(lines[i]);
                i += 1;
            }
            i -= 1;
            html.push(renderMarkdownTable(tableLines, options));
            continue;
        }

        const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (headingMatch) {
            closeTextBlocks();
            const level = headingMatch[1].length;
            html.push(`<h${level}>${parseInlineMarkdown(headingMatch[2], options)}</h${level}>`);
            continue;
        }

        if (/^[-*_]{3,}$/.test(trimmed)) {
            closeTextBlocks();
            html.push('<hr>');
            continue;
        }

        const quoteMatch = trimmed.match(/^>\s?(.*)$/);
        if (quoteMatch) {
            closeTextBlocks();
            const quoteLines = [quoteMatch[1]];
            while (i + 1 < lines.length) {
                const nextQuote = lines[i + 1].trim().match(/^>\s?(.*)$/);
                if (!nextQuote) break;
                quoteLines.push(nextQuote[1]);
                i += 1;
            }
            html.push(`<blockquote>${quoteLines.map(line => parseInlineMarkdown(line, options)).join('<br>')}</blockquote>`);
            continue;
        }

        const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
        const orderedMatch = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
        if (unorderedMatch || orderedMatch) {
            flushParagraph();
            const nextType = orderedMatch ? 'ol' : 'ul';
            if (listType && listType !== nextType) flushList();
            if (!listType && orderedMatch) {
                listStart = Number(orderedMatch[1]) || 1;
            }
            listType = nextType;
            listItems.push(orderedMatch ? orderedMatch[2] : unorderedMatch[1]);
            continue;
        }

        flushList();
        paragraphLines.push(line);
    }

    closeTextBlocks();
    return html.join('\n') || '<p>暂无内容</p>';
}

function prepareReportMarkdownLines(markdownText) {
    const lines = normalizeMarkdownText(markdownText).split('\n');
    const topicIndex = lines.findIndex((line, index) =>
        index < 18 && /^主题[:：]\s*\S+/.test(line.trim())
    );

    if (topicIndex === -1) {
        return lines;
    }

    const topic = lines[topicIndex].trim().replace(/^主题[:：]\s*/, '').trim();
    if (!topic) {
        return lines;
    }

    const reportLines = [...lines];
    reportLines.splice(topicIndex, 1);

    const firstContentIndex = reportLines.findIndex(line => line.trim());
    if (firstContentIndex !== -1 && /^#\s+/.test(reportLines[firstContentIndex].trim())) {
        reportLines.splice(firstContentIndex, 1);
    }

    while (reportLines.length && !reportLines[0].trim()) {
        reportLines.shift();
    }

    return [`# ${topic}`, '', ...reportLines];
}

function isMarkdownTableStart(lines, index) {
    const current = lines[index] || '';
    const next = lines[index + 1] || '';
    return current.includes('|') && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(next);
}

function collectTrailingEquationNumber(lines, currentIndex) {
    let index = currentIndex + 1;
    while (index < lines.length && !String(lines[index] || '').trim()) {
        index += 1;
    }
    if (index >= lines.length) return null;
    const label = String(lines[index] || '').trim();
    if (!/^\(\s*\d+(?:[a-zA-Z]|[.\-]\d+)?\s*\)$/.test(label)) {
        return null;
    }
    return {
        label: label.replace(/\s+/g, ''),
        endIndex: index
    };
}

function renderMarkdownMathBlock(rawMath, openDelimiter, closeDelimiter, equationNumber = '') {
    const text = String(rawMath || '').trim();
    let body = text;
    if (body.startsWith(openDelimiter)) {
        body = body.slice(openDelimiter.length);
    }
    if (body.endsWith(closeDelimiter)) {
        body = body.slice(0, -closeDelimiter.length);
    }
    const numberMarkup = equationNumber
        ? `<span class="markdown-equation-number">${escapeHtml(equationNumber)}</span>`
        : '';
    return `<div class="markdown-math-block${equationNumber ? ' has-equation-number' : ''}"><div class="markdown-math-expression">\\[${escapeHtml(body.trim())}\\]</div>${numberMarkup}</div>`;
}

function renderMarkdownTable(tableLines, options = {}) {
    const rows = tableLines.map(splitMarkdownTableRow);
    const headerCells = rows[0] || [];
    const bodyRows = rows.slice(2);

    return `
        <div class="markdown-table-wrap">
            <table>
                <thead>
                    <tr>${headerCells.map(cell => `<th>${parseInlineMarkdown(cell, options)}</th>`).join('')}</tr>
                </thead>
                <tbody>
                    ${bodyRows.map(row => `<tr>${row.map(cell => `<td>${parseInlineMarkdown(cell, options)}</td>`).join('')}</tr>`).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function splitMarkdownTableRow(row) {
    return String(row || '')
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map(cell => cell.trim());
}

function parseInlineMarkdown(text, options = {}) {
    const tokens = [];
    const placeholder = index => `\u0000MDTOKEN${index}\u0000`;
    let value = String(text ?? '');

    function protect(pattern, render) {
        value = value.replace(pattern, (...args) => {
            const token = placeholder(tokens.length);
            tokens.push(render(...args));
            return token;
        });
    }

    protect(/`([^`]+)`/g, (match, code) => `<code>${escapeHtml(code)}</code>`);
    protect(/<sup>(.*?)<\/sup>/gi, (match, content) => `<sup>${escapeHtml(content).trim()}</sup>`);
    protect(/<sub>(.*?)<\/sub>/gi, (match, content) => `<sub>${escapeHtml(content).trim()}</sub>`);
    protect(/\\\((.+?)\\\)/g, (match, formula) => `<span class="markdown-math-inline">\\(${escapeHtml(formula)}\\)</span>`);
    protect(/\$(?!\$)([^$\n]+?)\$/g, (match, formula) => `<span class="markdown-math-inline">\\(${escapeHtml(formula)}\\)</span>`);
    protect(/[⟨<]((?:\*\*)?[0-9\u0305]+(?:\*\*)?)[⟩>]/g, (match, value) => {
        return renderCrystalNotation(value, 'direction');
    });
    protect(/\{((?:\*\*)?[0-9\u0305]+(?:\*\*)?)\}/g, (match, value) => {
        return renderCrystalNotation(value, 'plane');
    });
    protect(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (match, alt, href) => {
        return renderMarkdownImage(href, alt, options, false);
    });
    protect(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
        const safeHref = /^(https?:|mailto:|#|\/|\.)/i.test(href) ? href : '#';
        return `<a href="${escapeAttribute(safeHref)}" target="_blank" rel="noopener noreferrer">${parseInlineMarkdown(label, options)}</a>`;
    });
    protect(/\\([\\`*_{}\[\]()#+\-.!>])/g, (match, escapedChar) => escapeHtml(escapedChar));

    value = escapeHtml(value)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');

    tokens.forEach((token, index) => {
        value = value.replace(escapeHtml(placeholder(index)), token);
    });

    return value;
}

function renderCrystalNotation(value, kind = 'direction') {
    const raw = String(value || '').trim();
    const emphasized = raw.startsWith('**') && raw.endsWith('**');
    const digits = emphasized ? raw.slice(2, -2) : raw;
    const parts = [];
    for (let i = 0; i < digits.length; i += 1) {
        const char = digits[i];
        if (digits[i + 1] === '\u0305') {
            parts.push(`<span class="crystal-overbar">${escapeHtml(char)}</span>`);
            i += 1;
        } else {
            parts.push(escapeHtml(char));
        }
    }
    const open = kind === 'plane' ? '{' : '⟨';
    const close = kind === 'plane' ? '}' : '⟩';
    const body = `${open}${parts.join('')}${close}`;
    const content = emphasized ? `<strong>${body}</strong>` : body;
    return `<span class="crystal-notation crystal-notation-${escapeAttribute(kind)}">${content}</span>`;
}

function typesetMarkdownMath(container, attempt = 0) {
    if (!container) return;
    if (!window.MathJax) {
        renderFallbackMath(container);
        return;
    }
    const runTypeset = () => {
        if (typeof window.MathJax.typesetPromise !== 'function') {
            if (attempt < 20) {
                window.setTimeout(() => typesetMarkdownMath(container, attempt + 1), 150);
            } else {
                renderFallbackMath(container);
            }
            return;
        }
        window.MathJax.typesetPromise([container]).catch(error => {
            console.warn('MathJax typeset failed', error);
            renderFallbackMath(container);
        });
    };
    if (window.MathJax.startup && window.MathJax.startup.promise) {
        window.MathJax.startup.promise.then(runTypeset).catch(() => {});
    } else {
        window.setTimeout(runTypeset, 0);
    }
}

function renderFallbackMath(container) {
    container.querySelectorAll('.markdown-math-block').forEach(node => {
        if (node.dataset.mathFallback === '1') return;
        const expressionNode = node.querySelector('.markdown-math-expression');
        const numberNode = node.querySelector('.markdown-equation-number');
        const formula = stripMathDelimiters((expressionNode || node).textContent || '');
        const fallbackMarkup = `<div class="markdown-math-fallback">${latexToReadableHtml(formula)}</div>`;
        if (expressionNode) {
            expressionNode.innerHTML = fallbackMarkup;
        } else {
            node.innerHTML = `${fallbackMarkup}${numberNode ? numberNode.outerHTML : ''}`;
        }
        node.dataset.mathFallback = '1';
    });
    container.querySelectorAll('.markdown-math-inline').forEach(node => {
        if (node.dataset.mathFallback === '1') return;
        const formula = stripMathDelimiters(node.textContent || '');
        node.innerHTML = latexToReadableHtml(formula);
        node.dataset.mathFallback = '1';
    });
}

function stripMathDelimiters(value) {
    let text = String(value || '').trim();
    const pairs = [
        ['\\[', '\\]'],
        ['\\(', '\\)'],
        ['$$', '$$'],
        ['$', '$']
    ];
    pairs.forEach(([open, close]) => {
        if (text.startsWith(open) && text.endsWith(close)) {
            text = text.slice(open.length, -close.length).trim();
        }
    });
    return text;
}

function latexToReadableHtml(formula) {
    let text = escapeHtml(String(formula || '').trim());
    text = text
        .replace(/\\left|\\right/g, '')
        .replace(/\\,/g, ' ')
        .replace(/\\quad/g, '&nbsp;&nbsp;&nbsp;')
        .replace(/\\operatorname\{([^{}]+)\}/g, '$1')
        .replace(/\\text\{([^{}]+)\}/g, '<span class="math-text">$1</span>')
        .replace(/\\rm\s+/g, '')
        .replace(/\\mathbf\{([^{}]+)\}/g, '<strong>$1</strong>');

    text = replaceLatexFractions(text);

    const symbols = {
        Delta: 'Δ', delta: 'δ', gamma: 'γ', tau: 'τ', zeta: 'ζ',
        alpha: 'α', beta: 'β', omega: 'ω', eta: 'η', theta: 'θ',
        lambda: 'λ', mu: 'μ', sigma: 'σ', epsilon: 'ε',
        approx: '≈', times: '×', cdot: '·', pm: '±',
        leq: '≤', geq: '≥', neq: '≠', infty: '∞',
        to: '→', rightarrow: '→', leftrightarrow: '↔'
    };
    Object.entries(symbols).forEach(([name, value]) => {
        text = text.replace(new RegExp(`\\\\${name}\\b`, 'g'), value);
    });

    text = text
        .replace(/_\{([^{}]+)\}/g, '<sub>$1</sub>')
        .replace(/\^\{([^{}]+)\}/g, '<sup>$1</sup>')
        .replace(/_([A-Za-z0-9Α-Ωα-ω]+)/g, '<sub>$1</sub>')
        .replace(/\^([A-Za-z0-9+\-]+)/g, '<sup>$1</sup>')
        .replace(/\\\\/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    return text || '&nbsp;';
}

function replaceLatexFractions(value) {
    let text = String(value || '');
    const fractionPattern = /\\frac\{([^{}]+)\}\{([^{}]+)\}/g;
    let previous = '';
    while (previous !== text) {
        previous = text;
        text = text.replace(fractionPattern, (_match, numerator, denominator) => (
            `<span class="math-frac"><span>${numerator}</span><span>${denominator}</span></span>`
        ));
    }
    return text;
}

function parseMarkdownImageLine(line) {
    const match = String(line || '').trim().match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$/);
    if (!match) return null;
    return { alt: match[1] || '', href: match[2] || '' };
}

function isFigureCaptionLine(line) {
    const text = String(line || '').trim();
    const normalized = text
        .replace(/<span\b[^>]*>\s*<\/span>/gi, '')
        .replace(/\*\*/g, '')
        .replace(/__/g, '')
        .trim();
    const captionPattern = /^(?:Figure|Fig\.?|图)\s*[\dA-Za-z.-]+(?:\s*\([^)]+\))?\s*(?:[:：.]|。)\s+/i;
    return captionPattern.test(normalized);
}

function collectMarkdownFigure(lines, imageIndex) {
    const images = [];
    let caption = '';
    let index = imageIndex;
    let endIndex = imageIndex;

    while (index < lines.length) {
        while (index < lines.length && !String(lines[index] || '').trim()) {
            index += 1;
        }
        const image = parseMarkdownImageLine(lines[index]);
        if (!image) break;
        images.push(image);
        endIndex = index;
        index += 1;
    }

    while (index < lines.length && !String(lines[index] || '').trim()) {
        index += 1;
    }
    if (index < lines.length && isFigureCaptionLine(lines[index])) {
        caption = String(lines[index] || '').trim();
        endIndex = index;
    }

    return { images, caption, endIndex };
}

function renderMarkdownFigure(images, options = {}, caption = '') {
    const validImages = (images || []).filter(image => image && image.href);
    if (!validImages.length) return '';
    const multipleClass = validImages.length > 1 ? ' is-multiple' : '';
    const imageMarkup = validImages.map(image => renderMarkdownImage(image.href, image.alt, options, false)).join('');
    const captionText = String(caption || '').trim();
    return `
        <figure>
            <div class="markdown-figure-images${multipleClass}">
                ${imageMarkup}
            </div>
            ${captionText ? `<figcaption>${parseInlineMarkdown(captionText, options)}</figcaption>` : ''}
        </figure>
    `;
}

function renderMarkdownImage(href, alt = '', options = {}, block = false, caption = '') {
    const src = resolveMarkdownAssetHref(href, options);
    const altText = String(alt || '').trim();
    const captionText = String(caption || '').trim();
    if (!src) {
        return escapeHtml(captionText || altText || href || '');
    }
    const image = `<img src="${escapeAttribute(src)}" alt="${escapeAttribute(altText)}" width="960" height="720" loading="lazy" decoding="async">`;
    if (!block) return image;
    return `
        <figure>
            ${image}
            ${captionText ? `<figcaption>${parseInlineMarkdown(captionText, options)}</figcaption>` : ''}
        </figure>
    `;
}

function resolveMarkdownAssetHref(href, options = {}) {
    const value = String(href || '').trim();
    if (!value) return '';
    if (/^(https?:|data:|blob:|#)/i.test(value)) return value;
    if (value.startsWith('/')) return value;
    const cleanPath = value.replace(/^\.\/+/, '');
    if (!cleanPath || cleanPath.includes('\u0000')) return '';
    if (options.assetBaseUrl) {
        return `${options.assetBaseUrl}${encodeURIComponent(cleanPath)}`;
    }
    return value;
}

async function handleBrowseCsv() {
    const currentValue = document.getElementById('input-csv').value;

    try {
        showLoading(true, 'browse-csv');
        const response = await fetch('/api/select_csv_file', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ current_csv: currentValue })
        });
        const result = await response.json();

        if (result.cancelled) {
            return;
        }
        if (!response.ok) {
            addLog(`CSV文件选择失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        document.getElementById('input-csv').value = result.csv_path;
        await refreshFileList();
        document.getElementById('search-file-list').value = result.csv_path;
        await previewCSV(result.csv_path, 1);
        showPreviewTab('literature');
        addLog(`已选择本地CSV: ${result.csv_path}`);
    } catch (error) {
        addLog(`CSV文件选择失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'browse-csv');
    }
}

async function handleCsvFilePicked(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        showLoading(true, 'browse-csv');
        const response = await fetch('/api/upload_csv', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (!response.ok) {
            addLog(`CSV文件选择失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        document.getElementById('input-csv').value = result.csv_path;
        await refreshFileList();
        document.getElementById('search-file-list').value = result.csv_path;
        await previewCSV(result.csv_path, 1);
        showPreviewTab('literature');
        addLog(`已选择本地CSV: ${result.csv_path}`);
    } catch (error) {
        addLog(`CSV文件选择失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'browse-csv');
        event.target.value = '';
    }
}

async function handleEnrichCsv(inputCsvOverride = '', buttonId = 'enrich-preview-csv') {
    const inputCsv = inputCsvOverride || document.getElementById('input-csv').value;
    if (!inputCsv) {
        addLog('请先选择一个CSV文件再执行多源补全', 'warning');
        return;
    }
    let selectedSources = getSelectedSources();
    if (selectedSources.length === 0) {
        addLog('请至少选择一个文献数据库再执行多源补全', 'warning');
        return;
    }

    try {
        showLoading(true, buttonId);
        const response = await fetch('/api/enrich_csv', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                input_csv: inputCsv,
                selected_sources: selectedSources,
                source_credentials: getSourceCredentials()
            })
        });
        const result = await response.json();

        if (response.ok) {
            addLog(`多源补全任务已启动，任务ID: ${result.task_id}`);
            startTaskPolling(result.task_id);
        } else {
            addLog(`多源补全启动失败: ${result.error || '未知错误'}`, 'error');
        }
    } catch (error) {
        addLog(`多源补全请求失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, buttonId);
    }
}

async function handleEnrichPreviewCsv() {
    const selectedFile = document.getElementById('preview-csv-select').value || currentCsvPath;
    await handleEnrichCsv(selectedFile, 'enrich-preview-csv');
}

async function handleBrowseOutput() {
    const currentValue = document.getElementById('output-dir').value;

    try {
        showLoading(true, 'browse-output');
        const response = await fetch('/api/select_output_dir', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ current_dir: currentValue })
        });
        const result = await response.json();

        if (result.cancelled) {
            return;
        }
        if (!response.ok) {
            addLog(`选择输出目录失败: ${result.error || '未知错误'}`, 'error');
            return;
        }
        document.getElementById('output-dir').value = result.output_dir;
    } catch (error) {
        addLog(`选择输出目录失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'browse-output');
    }
}

async function loadKnowledgeGraph() {
    const selectedFile = document.getElementById('graph-csv-select').value || document.getElementById('input-csv').value;
    const dataSource = document.getElementById('graph-data-source-select')?.value || 'csv';
    const graphScope = dataSource === 'library' ? 'library' : 'topic';
    const topicSource = dataSource === 'collection' ? 'collection' : 'csv';
    const collectionId = document.getElementById('graph-collection-select')?.value || currentCollectionId || '';
    if (graphScope !== 'library' && topicSource === 'csv' && !selectedFile) {
        addLog('请先选择一个CSV数据集', 'warning');
        showPreviewTab('graph');
        return;
    }
    if (graphScope !== 'library' && topicSource === 'collection' && !collectionId) {
        addLog('请先选择一个文献主题库', 'warning');
        showPreviewTab('graph');
        return;
    }

    try {
        showLoading(true, 'generate-graph-btn');
        const graphMode = document.getElementById('graph-mode-select')?.value || 'hybrid';
        const graphProvider = document.getElementById('graph-llm-provider')?.value || 'openai_compatible';
        const graphModel = document.getElementById('graph-llm-model')?.value || '';
        const inputSource = document.getElementById('graph-input-source-select')?.value || 'abstract';
        const maxChunks = document.getElementById('graph-max-chunks')?.value || '20';
        const collection = currentCollections.find(item => item.collection_id === collectionId);
        const graphSourceLabel = graphScope === 'library'
            ? 'literature_library.sqlite'
            : (topicSource === 'collection' ? (collection?.name || collectionId) : selectedFile);
        addLog(`开始生成${graphScope === 'library' ? '全库' : '主题库'}知识图谱: ${graphSourceLabel}`, 'info', { toast: false });
        addLog(`图谱生成模式: ${formatGraphModeLabel(graphMode)} · ${formatGraphInputSource(inputSource)} · ${graphProvider}${graphModel ? ` · ${graphModel}` : ''}`, 'info', { toast: false });
        const payload = {
            csv: selectedFile,
            graph_scope: graphScope,
            topic_source: topicSource,
            collection_id: collectionId,
            input_source: inputSource,
            max_chunks_per_paper: maxChunks,
            max_nodes: '36',
            max_edges: '90',
            mode: graphMode,
            llm_provider: graphProvider,
            llm_base_url: document.getElementById('graph-llm-base-url')?.value || '',
            ollama_base_url: document.getElementById('graph-llm-base-url')?.value || '',
            llm_api_key: document.getElementById('graph-llm-api-key')?.value || '',
            model: graphModel,
            llm_timeout_sec: '45',
            llm_connect_timeout_sec: '10',
            llm_max_workers: '3',
            llm_max_papers: '30'
        };
        document.getElementById('graph-content').innerHTML = renderGraphLoadingState(graphScope);
        setGraphProgress(2, '准备生成知识图谱...');
        showPreviewTab('graph');
        const response = await fetch('/api/knowledge_graph_task', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            addLog(`知识图谱生成失败: ${result.error || '未知错误'}`, 'error', { toast: false });
            document.getElementById('graph-content').innerHTML = `<p>${escapeHtml(result.error || '知识图谱生成失败')}</p>`;
            showPreviewTab('graph');
            showLoading(false, 'generate-graph-btn');
            setGraphProgress(0);
            return;
        }

        startTaskPolling(result.task_id, 'graph');
    } catch (error) {
        addLog(`知识图谱请求失败: ${error.message}`, 'error', { toast: false });
        document.getElementById('graph-content').innerHTML = `<p>知识图谱请求失败：${escapeHtml(error.message)}</p>`;
        showPreviewTab('graph');
        showLoading(false, 'generate-graph-btn');
        setGraphProgress(0);
    }
}

function setGraphProgress(progress, text = '') {
    const progressContainer = document.getElementById('graph-progress-container');
    const progressBar = document.getElementById('graph-progress-fill');
    const progressText = document.getElementById('graph-progress-text');
    if (!progressContainer || !progressBar || !progressText) return;
    const value = Math.max(0, Math.min(100, Number(progress || 0)));
    progressContainer.style.display = value > 0 && value < 100 ? 'block' : 'none';
    progressBar.style.width = `${value}%`;
    progressText.textContent = text ? `${Math.round(value)}% · ${text}` : `${Math.round(value)}%`;
    updateGraphBuildAnimation(value, text);
}

function renderGraphLoadingState(graphScope) {
    const scopeLabel = graphScope === 'library' ? '全库知识图谱' : '主题库知识图谱';
    const stages = [
        ['fa-database', '读取文献'],
        ['fa-magnifying-glass-chart', '抽取实体'],
        ['fa-share-nodes', '构建关系'],
        ['fa-diagram-project', '计算布局'],
    ];
    return `
        <div class="graph-build-visual" id="graph-build-visual" role="status" aria-live="polite">
            <div class="graph-build-header">
                <div>
                    <span class="graph-build-eyebrow">正在生成</span>
                    <strong>${scopeLabel}</strong>
                </div>
                <span class="graph-build-percent" id="graph-build-percent">2%</span>
            </div>
            <div class="graph-build-network" aria-hidden="true">
                ${stages.map(([icon, label], index) => `
                    ${index ? '<span class="graph-build-link"><i></i></span>' : ''}
                    <span class="graph-build-node" data-graph-build-stage="${index}">
                        <i class="fas ${icon}"></i>
                        <span>${label}</span>
                    </span>
                `).join('')}
            </div>
            <div class="graph-build-progress-track" aria-hidden="true">
                <span id="graph-build-progress-fill"></span>
            </div>
            <div class="graph-build-activity">
                <span class="graph-build-spinner" aria-hidden="true"></span>
                <span id="graph-build-message">准备生成知识图谱...</span>
            </div>
        </div>
    `;
}

function updateGraphBuildAnimation(progress, message = '') {
    const visual = document.getElementById('graph-build-visual');
    if (!visual) return;
    const value = Math.max(0, Math.min(100, Number(progress || 0)));
    const activeStage = value < 12 ? 0 : (value < 55 ? 1 : (value < 85 ? 2 : 3));
    visual.querySelectorAll('[data-graph-build-stage]').forEach((node, index) => {
        node.classList.toggle('is-active', index === activeStage && value < 100);
        node.classList.toggle('is-complete', index < activeStage || value >= 100);
    });
    visual.querySelectorAll('.graph-build-link').forEach((link, index) => {
        link.classList.toggle('is-active', index === activeStage - 1 && value < 100);
        link.classList.toggle('is-complete', index < activeStage - 1 || value >= 100);
    });
    const percent = document.getElementById('graph-build-percent');
    const fill = document.getElementById('graph-build-progress-fill');
    const activity = document.getElementById('graph-build-message');
    if (percent) percent.textContent = `${Math.round(value)}%`;
    if (fill) fill.style.width = `${value}%`;
    if (activity && message) activity.textContent = message;
}

function formatGraphModeLabel(mode) {
    return {
        rule: '规则抽取',
        hybrid: '混合增强',
        llm: '大模型优先'
    }[mode] || mode || '规则抽取';
}

function formatGraphInputSource(source) {
    return {
        abstract: '摘要',
        chunks: '全文片段',
        abstract_chunks: '摘要和全文片段'
    }[source] || source || '摘要';
}

function formatGraphScope(scope) {
    return scope === 'library' ? '全库' : '主题库';
}

function logKnowledgeGraphResult(result) {
    const nodes = result.nodes || [];
    const edges = result.edges || [];
    const triplets = result.triplets || [];
    const tripletCount = Number.isFinite(Number(result.triplet_count))
        ? Number(result.triplet_count)
        : triplets.length;
    const refinements = result.structure_refinements || [];
    const modeLabel = result.llm_enhanced ? '已启用大模型增强' : '未启用大模型，使用规则抽取';
    addLog(`知识图谱生成完成: ${nodes.length} 个节点 · ${edges.length} 条有向边 · ${tripletCount} 个三元组`, 'info', { toast: false });
    addLog(`知识图谱模式: ${formatGraphScope(result.scope)} · ${formatGraphInputSource(result.input_source)} · ${formatGraphModeLabel(result.mode)} · ${modeLabel}`, result.llm_enhanced ? 'info' : 'warning', { toast: false });
    if (result.input_source && result.input_source !== 'abstract') {
        const fallbackText = result.fallback_abstract_count ? `，${result.fallback_abstract_count} 篇使用摘要兜底` : '';
        addLog(`全文证据: 载入 ${result.fulltext_chunk_count || 0} 个全文片段，${result.missing_fulltext_count || 0} 篇未找到全文${fallbackText}`, 'info', { toast: false });
    }
    if (result.graph_source_label) {
        addLog(`图谱数据来源: ${result.graph_source_label}`, 'info', { toast: false });
    }
    if (refinements.length) {
        const inGraphCount = refinements.filter(item => item.in_graph).length;
        addLog(`微观结构细化: 识别 ${refinements.length} 个候选，${inGraphCount} 个进入主图`, 'info', { toast: false });
    }
    if (Array.isArray(result.psp_paths) && result.psp_paths.length) {
        addLog(`关系路径输出: ${result.psp_paths.slice(0, 3).join('；')}`, 'info', { toast: false });
    }
}

function renderKnowledgeGraph(data) {
    const nodes = data.nodes || [];
    const edges = data.edges || [];
    const topTerms = data.top_terms || [];
    const modeLabel = data.llm_enhanced ? '大模型混合增强' : (data.mode === 'llm' ? '大模型模式回退' : '规则抽取');
    const sourceMeta = data.input_source && data.input_source !== 'abstract'
        ? ` · ${formatGraphInputSource(data.input_source)} · ${data.fulltext_chunk_count || 0} 个全文片段`
        : ` · ${formatGraphInputSource(data.input_source || 'abstract')}`;
    const graphSourceLabel = data.graph_source_label || data.dataset || '-';
    document.getElementById('graph-info').textContent = `${formatGraphScope(data.scope)} · ${graphSourceLabel} · ${data.paper_count || 0} 篇文献 · 材料-工艺-组织-性能关系图 · ${modeLabel}${sourceMeta} · ${nodes.length} 个节点 · ${edges.length} 条关系`;

    if (!nodes.length || !edges.length) {
        document.getElementById('graph-content').innerHTML = `
            <div class="graph-empty">
                <strong>未生成可视化关系</strong>
                <p>${escapeHtml(data.message || '当前数据集中可抽取术语或共现关系不足。')}</p>
            </div>
        `;
        return;
    }

    const stableLayoutNodes = nodes.map(node => ({
        ...node,
        x: Number(node.x || 500),
        y: Number(node.y || 310),
        radius: Number(node.radius || graphNodeRadius(node, Math.max(1, ...nodes.map(item => Number(item.count || 0)))))
    }));
    const motionEnabled = getGraphMotionEnabled();
    const layoutNodes = motionEnabled
        ? createMetastableGraphLayout(stableLayoutNodes).nodes
        : stableLayoutNodes;
    const nodeById = new Map(layoutNodes.map(node => [node.id, node]));
    const maxEdgeWeight = Math.max(0.01, ...edges.map(edge => Number(edge.weight || 0)));

    const edgeMarkup = edges.map((edge, index) => {
        const source = nodeById.get(edge.source);
        const target = nodeById.get(edge.target);
        if (!source || !target) return '';
        const normalizedWeight = Number(edge.weight || 0.2) / maxEdgeWeight;
        const width = 1.2 + normalizedWeight * 4.2;
        const opacity = 0.26 + Math.min(0.62, normalizedWeight * 0.62);
        const edgeColor = graphEdgeColor(source.category, target.category);
        const pathData = createGraphEdgePath(source, target, index);
        return `
            <path class="graph-edge${index < 24 ? ' is-flowing' : ''}" data-edge-index="${index}" data-source="${escapeAttribute(edge.source)}" data-target="${escapeAttribute(edge.target)}" data-relation="${escapeAttribute(edge.relation || 'affects')}" d="${escapeAttribute(pathData)}" style="--edge-color:${edgeColor};--edge-order:${index % 18};" stroke-width="${width.toFixed(2)}" opacity="${opacity.toFixed(2)}" marker-end="url(#graphArrow)">
                <title>${escapeHtml(formatTrendTermPlain(edge.source))} → ${escapeHtml(edge.relation || 'affects')} → ${escapeHtml(formatTrendTermPlain(edge.target))} · weight ${escapeHtml(edge.weight)} · freq ${escapeHtml(edge.frequency || '-')}</title>
            </path>
        `;
    }).join('');

    const nodeMarkup = layoutNodes.map((node, index) => {
        const radius = node.radius || 20;
        const labelOffset = radius + 10;
        const paperTitles = getGraphNodePaperDetails(node).slice(0, 3).map(paper => paper.title).join('\n');
        return `
            <g class="graph-node graph-node-${escapeAttribute(node.category)}" data-node-id="${escapeAttribute(node.id)}" transform="translate(${node.x}, ${node.y})" style="--node-order:${index % 24};" tabindex="0" role="button" aria-label="${escapeAttribute(formatTrendTermPlain(node.label))}">
                ${renderGraphNodeShape(node.category, radius)}
                <text y="${labelOffset.toFixed(1)}">${formatSvgTrendTerm(shortGraphLabel(node.label))}</text>
                <title>${escapeHtml(formatTrendTermPlain(node.label))} · ${escapeHtml(graphCategoryLabel(node.category))} · PageRank ${escapeHtml(node.pagerank || 0)}${paperTitles ? `\n${escapeHtml(paperTitles)}` : ''}</title>
            </g>
        `;
    }).join('');

    const pspPaths = normalizePspPathDetails(data.psp_path_details, data.psp_paths || [], nodeById);
    const evidenceNodes = nodes
        .filter(node => Array.isArray(node.papers) && node.papers.length > 0)
        .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
        .slice(0, 6);

    document.getElementById('graph-content').innerHTML = `
        <div class="graph-insight-board">
            <section class="graph-category-strip">
                ${renderGraphCategoryPill('MATERIAL', '材料', data.category_counts || {})}
                ${renderGraphCategoryPill('PROCESS', '工艺', data.category_counts || {})}
                ${renderGraphCategoryPill('STRUCTURE', '组织', data.category_counts || {})}
                ${renderGraphCategoryPill('PROPERTY', '性能', data.category_counts || {})}
            </section>

            <section class="graph-analysis-card graph-frequency-card">
                <div class="graph-card-title">
                    <h4>核心节点</h4>
                    <span>按文献覆盖排序</span>
                </div>
                <div class="graph-term-cloud">
                    ${topTerms.map(item => renderGraphTermButton(item)).join('') || '<p>暂无高频术语。</p>'}
                </div>
            </section>

            <section class="graph-analysis-card graph-keyword-card">
                <div class="graph-card-title">
                    <h4>材料-工艺-组织-性能路径</h4>
                    <span>四层链路</span>
                </div>
                <div class="graph-keyword-list">
                    ${pspPaths.slice(0, 7).map((path, index) => renderPspPathCard(path, index)).join('') || '<p>暂无稳定的材料-工艺-组织-性能路径。</p>'}
                </div>
            </section>

            <section class="graph-analysis-card graph-evidence-card" id="graph-detail-panel">
                <div class="graph-card-title">
                    <h4>文献证据</h4>
                    <span>点击节点后刷新</span>
                </div>
                <div class="graph-evidence-list">
                    ${evidenceNodes.map(node => renderGraphEvidenceSeed(node)).join('') || '<p>暂无代表文献标题。</p>'}
                </div>
            </section>

            <section class="graph-canvas-bottom">
                <div class="graph-card-title">
                    <h4>材料-工艺-组织-性能有向知识图谱</h4>
                    <span id="graph-stability-status">层级稳态</span>
                </div>
                ${renderGraphCanvas(edgeMarkup, nodeMarkup)}
                <div class="graph-publication-output">
                    <h5>论文图注</h5>
                    <p>${escapeHtml(data.caption || '')}</p>
                </div>
            </section>
        </div>
    `;
    initializeKnowledgeGraphInteraction(layoutNodes, edges);
    if (motionEnabled) {
        requestAnimationFrame(() => animateGraphToLayout(stableLayoutNodes, '网络展开中'));
    }
}

function normalizePspPathDetails(pathDetails, fallbackPaths, nodeById) {
    if (Array.isArray(pathDetails) && pathDetails.length) {
        return pathDetails
            .map(path => ({
                nodes: Array.isArray(path.nodes) ? path.nodes.map(item => String(item || '')).filter(Boolean) : [],
                categories: Array.isArray(path.nodes) ? path.nodes.map(item => nodeById.get(String(item || ''))?.category || '') : [],
                relations: Array.isArray(path.relations) ? path.relations.map(item => String(item || 'affects')) : [],
                weight: path.weight ?? '',
                frequency: path.frequency ?? ''
            }))
            .filter(path => path.nodes.length >= 2);
    }
    return (fallbackPaths || [])
        .map(path => String(path || '').split('→').map(part => part.trim()).filter(Boolean))
        .filter(nodes => nodes.length >= 2)
        .map(nodes => ({ nodes, categories: nodes.map(node => nodeById.get(node)?.category || ''), relations: [], weight: '', frequency: '' }));
}

function renderPspPathCard(path, index) {
    const nodes = path.nodes || [];
    const meta = [
        path.weight !== '' ? `权重 ${path.weight}` : '',
        path.frequency !== '' ? `频次 ${path.frequency}` : ''
    ].filter(Boolean).join(' · ');
    return `
        <button type="button" class="graph-psp-path" data-psp-path-index="${escapeAttribute(index)}" data-psp-path-nodes="${escapeAttribute(JSON.stringify(nodes))}">
            <span class="graph-psp-index">${escapeHtml(index + 1)}</span>
            <span class="graph-psp-flow">
                ${nodes.map((node, nodeIndex) => `
                    <span class="graph-psp-node graph-psp-node-${escapeAttribute(path.categories?.[nodeIndex] || '')}">${formatTrendTerm(node)}</span>
                    ${nodeIndex < nodes.length - 1 ? '<span class="graph-psp-arrow">→</span>' : ''}
                `).join('')}
            </span>
            <span class="graph-psp-meta">${escapeHtml(meta || '点击高亮路径')}</span>
        </button>
    `;
}

function createGraphEdgePath(source, target, index = 0) {
    const dx = Number(target.x) - Number(source.x);
    const dy = Number(target.y) - Number(source.y);
    const distance = Math.sqrt(dx * dx + dy * dy) || 1;
    const curve = Math.min(92, Math.max(24, distance * 0.18)) * (index % 2 ? 1 : -1);
    const normalX = -dy / distance;
    const normalY = dx / distance;
    const controlX = (Number(source.x) + Number(target.x)) / 2 + normalX * curve;
    const controlY = (Number(source.y) + Number(target.y)) / 2 + normalY * curve;
    return `M ${Number(source.x).toFixed(1)} ${Number(source.y).toFixed(1)} Q ${controlX.toFixed(1)} ${controlY.toFixed(1)} ${Number(target.x).toFixed(1)} ${Number(target.y).toFixed(1)}`;
}

function graphEdgeColor(sourceCategory, targetCategory) {
    if (sourceCategory === 'MATERIAL') return '#38d9c6';
    if (sourceCategory === 'PROCESS') return '#a78bfa';
    if (targetCategory === 'PROPERTY') return '#fb7185';
    if (targetCategory === 'STRUCTURE') return '#60a5fa';
    return '#94a3b8';
}

function renderGraphNodeShape(category, radius) {
    const size = Number(radius || 18);
    if (category === 'PROCESS') {
        const d = Math.max(12, size * 0.86);
        return `<rect class="graph-node-symbol" x="${(-d).toFixed(1)}" y="${(-d).toFixed(1)}" width="${(d * 2).toFixed(1)}" height="${(d * 2).toFixed(1)}" rx="4" transform="rotate(45)"></rect>`;
    }
    if (category === 'PROPERTY') {
        const points = Array.from({ length: 6 }, (_, index) => {
            const angle = Math.PI / 6 + index * Math.PI / 3;
            return `${(Math.cos(angle) * size).toFixed(1)},${(Math.sin(angle) * size).toFixed(1)}`;
        }).join(' ');
        return `<polygon class="graph-node-symbol" points="${points}"></polygon>`;
    }
    if (category === 'STRUCTURE') {
        return `<circle class="graph-node-symbol" r="${size.toFixed(1)}"></circle>`;
    }
    return `<circle class="graph-node-symbol" r="${size.toFixed(1)}"></circle>`;
}

function renderGraphCanvas(edgeMarkup, nodeMarkup) {
    return `
        <div class="graph-canvas-shell graph-canvas-strip">
            <div class="graph-canvas-legend" aria-label="知识图谱图例">
                <span><i class="legend-dot legend-material"></i>材料</span>
                <span><i class="legend-diamond legend-process"></i>工艺</span>
                <span><i class="legend-dot legend-structure"></i>组织</span>
                <span><i class="legend-hex legend-property"></i>性能</span>
            </div>
            <div class="graph-zoom-controls" aria-label="知识图谱缩放控制">
                <button type="button" id="graph-selection-reset" class="graph-selection-reset" title="取消选中" aria-label="取消选中">取消选中</button>
                <button type="button" id="graph-export-svg" class="graph-export-btn" title="导出 SVG" aria-label="导出 SVG">SVG</button>
                <button type="button" id="graph-export-png" class="graph-export-btn" title="导出 300dpi PNG" aria-label="导出 300dpi PNG">PNG</button>
                <button type="button" id="graph-motion-toggle" title="暂停动态图谱" aria-label="暂停动态图谱" aria-pressed="false"><i class="fas fa-pause"></i></button>
                <button type="button" id="graph-zoom-out" title="缩小" aria-label="缩小"><i class="fas fa-minus"></i></button>
                <button type="button" id="graph-zoom-reset" title="重置视图" aria-label="重置视图">100%</button>
                <button type="button" id="graph-zoom-in" title="放大" aria-label="放大"><i class="fas fa-plus"></i></button>
            </div>
            <svg class="knowledge-graph-svg" viewBox="0 0 1000 620" role="img" aria-label="知识图谱">
                <defs>
                    <marker id="graphArrow" viewBox="0 0 10 10" refX="8.7" refY="5" markerWidth="8" markerHeight="8" orient="auto">
                        <path d="M 0 0 L 10 5 L 0 10 z" fill="#b9c9dc"></path>
                    </marker>
                </defs>
                <rect class="graph-backplate" x="18" y="18" width="964" height="584" rx="18" data-graph-clear="true"></rect>
                <g class="graph-viewport">
                    <g>${edgeMarkup}</g>
                    <g>${nodeMarkup}</g>
                </g>
            </svg>
        </div>
    `;
}

function renderGraphCategoryPill(category, label, counts) {
    return `
        <button type="button" class="graph-category-pill graph-category-${escapeAttribute(category)}" data-category-filter="${escapeAttribute(category)}">
            <span></span>
            <strong>${escapeHtml(label)}</strong>
            <em>${escapeHtml(counts[category] || 0)}</em>
        </button>
    `;
}

function renderGraphTermButton(item) {
    return `
        <button type="button" class="graph-term-chip graph-term-${escapeAttribute(item.category)}" data-term-id="${escapeAttribute(item.term)}">
            <span title="${escapeAttribute(item.term)}">${formatTrendTerm(item.term)}</span>
            <strong>${escapeHtml(item.count)}</strong>
        </button>
    `;
}

function renderGraphKeywordButton(item) {
    return `
        <button type="button" class="graph-keyword-button graph-term-${escapeAttribute(item.category)}" data-term-id="${escapeAttribute(item.term)}">
            <span>${formatTrendTerm(item.term)}</span>
            <strong>${escapeHtml(item.count)}</strong>
        </button>
    `;
}

function graphCategoryLabel(category) {
    return {
        MATERIAL: '材料',
        PROCESS: '工艺',
        STRUCTURE: '组织',
        PROPERTY: '性能',
        material: '材料',
        method: '工艺',
        keyword: '组织',
        property: '性能'
    }[category] || category || '未知类型';
}

function renderGraphEvidenceSeed(node) {
    const title = getGraphNodePaperDetails(node)[0]?.title || '';
    return `
        <button type="button" class="graph-evidence-item" data-term-id="${escapeAttribute(node.id)}">
            <strong>${formatTrendTerm(node.label)}</strong>
            <span>${escapeHtml(title || '暂无代表标题')}</span>
        </button>
    `;
}

function getGraphNodePaperDetails(node) {
    if (Array.isArray(node?.paper_details) && node.paper_details.length > 0) {
        return node.paper_details
            .filter(paper => paper && paper.title)
            .map((paper, index) => ({
                index,
                title: String(paper.title || ''),
                authors: String(paper.authors || ''),
                abstract: String(paper.abstract || ''),
                year: String(paper.year || ''),
                venue: String(paper.venue || ''),
                publicationDate: String(paper.publicationDate || ''),
                citationCount: paper.citationCount ?? '',
                doi: String(paper.doi || ''),
                url: String(paper.url || ''),
                pdf_url: String(paper.pdf_url || ''),
                source: String(paper.source || ''),
                paperId: String(paper.paperId || '')
            }));
    }
    return (node?.papers || []).filter(Boolean).map((title, index) => ({
        index,
        title: String(title),
        authors: '',
        abstract: '',
        year: '',
        venue: '',
        publicationDate: '',
        citationCount: '',
        doi: '',
        url: '',
        pdf_url: '',
        source: '',
        paperId: ''
    }));
}

function renderGraphPaperButton(paper, index) {
    const meta = [paper.year || paper.publicationDate, paper.venue, paper.citationCount !== '' ? `引 ${paper.citationCount}` : '']
        .filter(Boolean)
        .join(' · ');
    return `
        <button type="button" class="graph-paper-item" data-paper-index="${escapeAttribute(index)}">
            <strong>${escapeHtml(paper.title || '未命名文献')}</strong>
            <span>${escapeHtml(meta || paper.authors || '暂无文献元信息')}</span>
        </button>
    `;
}

function renderGraphPaperDetail(paper) {
    if (!paper) {
        return `
            <div class="graph-paper-detail-empty">
                点击上方任一文献，查看作者、期刊、DOI、摘要和原文链接。
            </div>
        `;
    }

    const primaryUrl = getSafeGraphPaperUrl(paper.url);
    const pdfUrl = getSafeGraphPaperUrl(paper.pdf_url);
    const metaItems = [
        paper.authors ? `<div><span>作者</span><strong>${escapeHtml(paper.authors)}</strong></div>` : '',
        paper.venue ? `<div><span>期刊/会议</span><strong>${escapeHtml(paper.venue)}</strong></div>` : '',
        paper.year || paper.publicationDate ? `<div><span>时间</span><strong>${escapeHtml(paper.publicationDate || paper.year)}</strong></div>` : '',
        paper.citationCount !== '' ? `<div><span>引用</span><strong>${escapeHtml(paper.citationCount)}</strong></div>` : '',
        paper.doi ? `<div><span>DOI</span><strong>${escapeHtml(paper.doi)}</strong></div>` : '',
        paper.source ? `<div><span>来源</span><strong>${escapeHtml(paper.source)}</strong></div>` : ''
    ].filter(Boolean).join('');

    return `
        <article class="graph-paper-detail-card">
            <h5>${escapeHtml(paper.title || '未命名文献')}</h5>
            <div class="graph-paper-meta-grid">
                ${metaItems || '<div><span>元信息</span><strong>暂无补充字段</strong></div>'}
            </div>
            <p>${escapeHtml(paper.abstract || '暂无摘要。')}</p>
            <div class="graph-paper-actions">
                ${primaryUrl ? `<a href="${escapeAttribute(primaryUrl)}" target="_blank" rel="noopener noreferrer">打开原文</a>` : ''}
                ${pdfUrl ? `<a href="${escapeAttribute(pdfUrl)}" target="_blank" rel="noopener noreferrer">打开 PDF</a>` : ''}
            </div>
        </article>
    `;
}

function ensureGraphPaperModal() {
    let modal = document.getElementById('graph-paper-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'graph-paper-modal';
    modal.className = 'graph-paper-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="graph-paper-modal-backdrop" data-graph-paper-modal-close></div>
        <section class="graph-paper-modal-panel" role="dialog" aria-modal="true" aria-label="文献详情">
            <button type="button" class="graph-paper-modal-close" data-graph-paper-modal-close aria-label="关闭文献详情">
                <i class="fas fa-times"></i>
            </button>
            <div class="graph-paper-modal-content" id="graph-paper-modal-content"></div>
        </section>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-graph-paper-modal-close]').forEach(item => {
        item.addEventListener('click', closeGraphPaperModal);
    });
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closeGraphPaperModal();
        }
    });
    return modal;
}

function openGraphPaperModal(paper) {
    const modal = ensureGraphPaperModal();
    const content = modal.querySelector('#graph-paper-modal-content');
    if (content) {
        content.innerHTML = renderGraphPaperDetail(paper);
    }
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('graph-paper-modal-open');
    activateManagedModal(modal, modal.querySelector('.graph-paper-modal-close'));
}

function closeGraphPaperModal() {
    const modal = document.getElementById('graph-paper-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('graph-paper-modal-open');
    deactivateManagedModal(modal);
}

function getSafeGraphPaperUrl(url) {
    const value = String(url || '').trim();
    if (!/^https?:\/\//i.test(value)) return '';
    return value;
}

function createMetastableGraphLayout(stableNodes) {
    return {
        nodes: stableNodes.map((node, index) => {
            const angle = index * 2.3999632297;
            const radius = 54 + (index % 6) * 14;
            return {
                ...node,
                x: Math.round(500 + (node.x - 500) * 0.18 + Math.cos(angle) * radius),
                y: Math.round(310 + (node.y - 310) * 0.18 + Math.sin(angle) * radius * 0.62),
            };
        })
    };
}

function getGraphMotionEnabled() {
    const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return !reducedMotion && localStorage.getItem(GRAPH_MOTION_STORAGE_KEY) !== 'off';
}

function computeGraphLayout(nodes, edges, maxNodeCount = 1) {
    const degree = new Map(nodes.map(node => [node.id, 0]));
    edges.forEach(edge => {
        degree.set(edge.source, (degree.get(edge.source) || 0) + Number(edge.weight || 1));
        degree.set(edge.target, (degree.get(edge.target) || 0) + Number(edge.weight || 1));
    });

    const categoryAnchors = {
        material: { x: 320, y: 245 },
        property: { x: 675, y: 245 },
        method: { x: 325, y: 430 },
        keyword: { x: 675, y: 430 }
    };
    const sortedNodes = [...nodes].sort((a, b) => {
        const scoreB = (degree.get(b.id) || 0) + Number(b.count || 0);
        const scoreA = (degree.get(a.id) || 0) + Number(a.count || 0);
        return scoreB - scoreA;
    });
    const center = sortedNodes[0];
    const rest = sortedNodes.slice(1);
    const categoryOrder = { material: 0, property: 1, method: 2, keyword: 3 };
    rest.sort((a, b) => {
        const categoryDiff = (categoryOrder[a.category] ?? 3) - (categoryOrder[b.category] ?? 3);
        if (categoryDiff !== 0) return categoryDiff;
        return (degree.get(b.id) || 0) - (degree.get(a.id) || 0);
    });

    const positioned = [];
    if (center) {
        positioned.push({
            ...center,
            radius: graphNodeRadius(center, maxNodeCount),
            x: 500,
            y: 310,
            vx: 0,
            vy: 0
        });
    }

    rest.forEach((node, index) => {
        const anchor = categoryAnchors[node.category] || categoryAnchors.keyword;
        const categoryIndex = rest.filter(item => item.category === node.category).indexOf(node);
        const categoryCount = Math.max(1, rest.filter(item => item.category === node.category).length);
        const angle = (categoryIndex / categoryCount) * Math.PI * 2 + (index % 2 ? 0.38 : -0.22);
        const spread = 74 + Math.min(60, categoryCount * 6);
        positioned.push({
            ...node,
            radius: graphNodeRadius(node, maxNodeCount),
            x: Math.round(anchor.x + Math.cos(angle) * spread),
            y: Math.round(anchor.y + Math.sin(angle) * spread * 0.72),
            vx: 0,
            vy: 0
        });
    });

    relaxGraphLayout(positioned, edges, degree);
    positioned.forEach(node => {
        node.x = Math.round(node.x);
        node.y = Math.round(node.y);
        delete node.vx;
        delete node.vy;
    });
    return { nodes: positioned };
}

function graphNodeRadius(node, maxNodeCount) {
    return 16 + Math.sqrt(Number(node.count || 1) / Math.max(1, maxNodeCount)) * 15;
}

function relaxGraphLayout(nodes, edges, degree) {
    const nodeById = new Map(nodes.map(node => [node.id, node]));
    const bounds = { minX: 68, maxX: 932, minY: 70, maxY: 545 };
    const categoryAnchors = {
        material: { x: 300, y: 235 },
        property: { x: 700, y: 235 },
        method: { x: 300, y: 430 },
        keyword: { x: 700, y: 430 }
    };

    for (let iteration = 0; iteration < 180; iteration += 1) {
        const alpha = 1 - iteration / 180;

        for (let i = 0; i < nodes.length; i += 1) {
            for (let j = i + 1; j < nodes.length; j += 1) {
                const a = nodes[i];
                const b = nodes[j];
                let dx = b.x - a.x;
                let dy = b.y - a.y;
                let distance = Math.sqrt(dx * dx + dy * dy) || 1;
                const minDistance = a.radius + b.radius + 42;
                const force = Math.min(4.8, (minDistance * minDistance) / (distance * distance)) * alpha;
                dx /= distance;
                dy /= distance;
                a.vx -= dx * force;
                a.vy -= dy * force;
                b.vx += dx * force;
                b.vy += dy * force;
            }
        }

        edges.forEach(edge => {
            const source = nodeById.get(edge.source);
            const target = nodeById.get(edge.target);
            if (!source || !target) return;
            let dx = target.x - source.x;
            let dy = target.y - source.y;
            const distance = Math.sqrt(dx * dx + dy * dy) || 1;
            const desired = 175 + Math.min(70, 9 * Number(edge.weight || 1));
            const force = (distance - desired) * 0.009 * alpha;
            dx /= distance;
            dy /= distance;
            source.vx += dx * force;
            source.vy += dy * force;
            target.vx -= dx * force;
            target.vy -= dy * force;
        });

        nodes.forEach(node => {
            const anchor = categoryAnchors[node.category] || categoryAnchors.keyword;
            const anchorForce = (degree.get(node.id) || 0) > 0 ? 0.004 : 0.01;
            node.vx += (anchor.x - node.x) * anchorForce * alpha;
            node.vy += (anchor.y - node.y) * anchorForce * alpha;
            node.vx += (500 - node.x) * 0.0015 * alpha;
            node.vy += (310 - node.y) * 0.0015 * alpha;

            node.x += node.vx;
            node.y += node.vy;
            node.vx *= 0.72;
            node.vy *= 0.72;
            constrainGraphNode(node, bounds);
        });
    }

    for (let pass = 0; pass < 42; pass += 1) {
        let moved = false;
        for (let i = 0; i < nodes.length; i += 1) {
            for (let j = i + 1; j < nodes.length; j += 1) {
                const a = nodes[i];
                const b = nodes[j];
                let dx = b.x - a.x;
                let dy = b.y - a.y;
                let distance = Math.sqrt(dx * dx + dy * dy) || 1;
                const minDistance = a.radius + b.radius + 34;
                if (distance >= minDistance) continue;
                const push = (minDistance - distance) / 2;
                dx /= distance;
                dy /= distance;
                a.x -= dx * push;
                a.y -= dy * push;
                b.x += dx * push;
                b.y += dy * push;
                constrainGraphNode(a, bounds);
                constrainGraphNode(b, bounds);
                moved = true;
            }
        }
        if (!moved) break;
    }
}

function constrainGraphNode(node, bounds) {
    const padding = node.radius + 26;
    node.x = Math.max(bounds.minX + padding, Math.min(bounds.maxX - padding, node.x));
    node.y = Math.max(bounds.minY + padding, Math.min(bounds.maxY - padding, node.y));
}

function shortGraphLabel(label) {
    const value = String(label || '');
    return value.length > 22 ? `${value.slice(0, 21)}…` : value;
}

function initializeKnowledgeGraphInteraction(nodes, edges) {
    stopGraphRealtimeMotion();
    const motionEnabled = getGraphMotionEnabled();
    graphInteractionState = {
        nodeMap: new Map(nodes.map(node => [node.id, { ...node }])),
        edges,
        selectedNodeId: '',
        draggedNodeId: '',
        dragMoved: false,
        isPanning: false,
        panMoved: false,
        transform: { scale: 1, x: 0, y: 0 },
        motionEnabled,
        motionAnchors: new Map(),
        motionFrameId: 0,
        lastMotionAt: 0,
    };

    const svg = document.querySelector('.knowledge-graph-svg');
    if (!svg) return;

    applyGraphTransform();
    bindGraphZoomControls();
    applyGraphMotionState(motionEnabled);
    svg.addEventListener('wheel', handleGraphWheel, { passive: false });
    svg.addEventListener('pointerdown', handleGraphCanvasPointerDown);
    svg.addEventListener('click', event => {
        const clickedNode = event.target.closest && event.target.closest('.graph-node');
        if (clickedNode || graphInteractionState.panMoved || graphInteractionState.dragMoved) return;
        clearGraphSelection();
    });

    svg.querySelectorAll('.graph-node').forEach(nodeEl => {
        nodeEl.addEventListener('pointerdown', handleGraphNodePointerDown);
        nodeEl.addEventListener('click', event => {
            event.stopPropagation();
            if (graphInteractionState.dragMoved) return;
            selectGraphNode(nodeEl.getAttribute('data-node-id') || '');
        });
        nodeEl.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectGraphNode(nodeEl.getAttribute('data-node-id') || '');
            }
        });
    });

    document.querySelectorAll('.graph-term-chip, .graph-keyword-button, .graph-evidence-item').forEach(button => {
        button.addEventListener('click', () => selectGraphNode(button.getAttribute('data-term-id') || ''));
    });
    document.querySelectorAll('.graph-category-pill').forEach(button => {
        button.addEventListener('click', () => highlightGraphCategory(button.getAttribute('data-category-filter') || ''));
    });
    document.querySelectorAll('.graph-psp-path').forEach(button => {
        button.addEventListener('click', () => {
            try {
                highlightPspPath(JSON.parse(button.getAttribute('data-psp-path-nodes') || '[]'), button);
            } catch (error) {
                addLog(`关系路径解析失败: ${error.message}`, 'error');
            }
        });
    });

    renderGraphNodeDetail('');
}

function handleGraphNodePointerDown(event) {
    event.stopPropagation();
    const nodeEl = event.currentTarget;
    const nodeId = nodeEl.getAttribute('data-node-id') || '';
    const svg = nodeEl.closest('svg');
    const node = graphInteractionState.nodeMap.get(nodeId);
    if (!svg || !node) return;

    event.preventDefault();
    nodeEl.setPointerCapture(event.pointerId);
    graphInteractionState.draggedNodeId = nodeId;
    graphInteractionState.dragMoved = false;
    nodeEl.classList.add('is-dragging');
    svg.classList.add('is-node-dragging');
    const status = document.getElementById('graph-stability-status');
    if (status) {
        status.textContent = '拖拽调整中';
        status.classList.add('is-settling');
    }
    const startPoint = getGraphWorldPoint(svg, event);
    const startX = node.x;
    const startY = node.y;

    const handleMove = moveEvent => {
        const point = getGraphWorldPoint(svg, moveEvent);
        const nextX = Math.max(40, Math.min(960, startX + point.x - startPoint.x));
        const nextY = Math.max(45, Math.min(575, startY + point.y - startPoint.y));
        if (Math.abs(nextX - startX) > 2 || Math.abs(nextY - startY) > 2) {
            graphInteractionState.dragMoved = true;
        }
        node.x = Math.round(nextX);
        node.y = Math.round(nextY);
        updateGraphNodePosition(nodeId);
    };

    const handleUp = upEvent => {
        nodeEl.releasePointerCapture(upEvent.pointerId);
        nodeEl.removeEventListener('pointermove', handleMove);
        nodeEl.removeEventListener('pointerup', handleUp);
        nodeEl.removeEventListener('pointercancel', handleUp);
        const shouldStabilize = graphInteractionState.dragMoved;
        graphInteractionState.draggedNodeId = '';
        nodeEl.classList.remove('is-dragging');
        svg.classList.remove('is-node-dragging');
        if (shouldStabilize) {
            stabilizeGraphAfterDrag(nodeId);
        } else if (status) {
            status.textContent = '动态稳态';
            status.classList.remove('is-settling');
        }
        window.setTimeout(() => {
            graphInteractionState.dragMoved = false;
        }, 0);
    };

    nodeEl.addEventListener('pointermove', handleMove);
    nodeEl.addEventListener('pointerup', handleUp);
    nodeEl.addEventListener('pointercancel', handleUp);
}

function bindGraphZoomControls() {
    document.getElementById('graph-zoom-in')?.addEventListener('click', () => zoomGraphBy(1.18));
    document.getElementById('graph-zoom-out')?.addEventListener('click', () => zoomGraphBy(1 / 1.18));
    document.getElementById('graph-zoom-reset')?.addEventListener('click', resetGraphView);
    document.getElementById('graph-selection-reset')?.addEventListener('click', clearGraphSelection);
    document.getElementById('graph-export-svg')?.addEventListener('click', exportKnowledgeGraphSvg);
    document.getElementById('graph-export-png')?.addEventListener('click', exportKnowledgeGraphPng);
    document.getElementById('graph-motion-toggle')?.addEventListener('click', toggleGraphMotion);
}

function toggleGraphMotion() {
    const enabled = !graphInteractionState.motionEnabled;
    graphInteractionState.motionEnabled = enabled;
    localStorage.setItem(GRAPH_MOTION_STORAGE_KEY, enabled ? 'on' : 'off');
    applyGraphMotionState(enabled);
    if (enabled) {
        captureGraphMotionAnchors();
        startGraphRealtimeMotion();
    } else {
        stopGraphRealtimeMotion();
    }
}

function applyGraphMotionState(enabled) {
    const shell = document.querySelector('.graph-canvas-shell');
    const button = document.getElementById('graph-motion-toggle');
    shell?.classList.toggle('is-motion-paused', !enabled);
    if (!button) return;
    button.setAttribute('aria-pressed', enabled ? 'false' : 'true');
    button.setAttribute('aria-label', enabled ? '暂停动态图谱' : '播放动态图谱');
    button.setAttribute('title', enabled ? '暂停动态图谱' : '播放动态图谱');
    const icon = button.querySelector('i');
    if (icon) icon.className = enabled ? 'fas fa-pause' : 'fas fa-play';
}

function exportKnowledgeGraphSvg() {
    const svg = document.querySelector('.knowledge-graph-svg');
    if (!svg) return;
    const clone = prepareGraphSvgClone(svg);
    const source = new XMLSerializer().serializeToString(clone);
    downloadGraphBlob(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }), 'psp-knowledge-graph.svg');
}

function exportKnowledgeGraphPng() {
    const svg = document.querySelector('.knowledge-graph-svg');
    if (!svg) return;
    const clone = prepareGraphSvgClone(svg);
    const source = new XMLSerializer().serializeToString(clone);
    const image = new Image();
    const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    image.onload = () => {
        const scale = 3.125;
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(1000 * scale);
        canvas.height = Math.round(620 * scale);
        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(pngBlob => {
            if (pngBlob) downloadGraphBlob(pngBlob, 'psp-knowledge-graph-300dpi.png');
        }, 'image/png');
    };
    image.src = url;
}

function prepareGraphSvgClone(svg) {
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const defs = clone.querySelector('defs') || clone.insertBefore(document.createElementNS('http://www.w3.org/2000/svg', 'defs'), clone.firstChild);
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = `
        .graph-backplate{fill:#07111f;stroke:rgba(125,211,252,.24)}
        .graph-edge{stroke:var(--edge-color, rgba(147,197,253,.78));fill:none;stroke-linecap:round}
        .graph-node-symbol{stroke:#e0f2fe;stroke-width:3}
        .graph-node text{fill:#e5efff;font-size:13px;font-weight:800;text-anchor:middle;paint-order:stroke;stroke:rgba(3,7,18,.92);stroke-width:5px;stroke-linejoin:round}
        .graph-node-MATERIAL .graph-node-symbol{fill:#2E6FDF}.graph-node-PROCESS .graph-node-symbol{fill:#7c3aed}.graph-node-STRUCTURE .graph-node-symbol{fill:#2dd4bf}.graph-node-PROPERTY .graph-node-symbol{fill:#f43f5e}
        #graphArrow path{fill:#b9c9dc}
    `;
    defs.appendChild(style);
    return clone;
}

function downloadGraphBlob(blob, filename) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function handleGraphWheel(event) {
    event.preventDefault();
    const svg = event.currentTarget;
    const point = getGraphSvgPoint(svg, event);
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    zoomGraphBy(factor, point);
}

function handleGraphCanvasPointerDown(event) {
    if (event.target.closest && event.target.closest('.graph-node')) return;
    const svg = event.currentTarget;
    event.preventDefault();
    svg.setPointerCapture(event.pointerId);
    graphInteractionState.isPanning = true;
    graphInteractionState.panMoved = false;
    const startPoint = getGraphSvgPoint(svg, event);
    const startTransform = { ...graphInteractionState.transform };

    const handleMove = moveEvent => {
        const point = getGraphSvgPoint(svg, moveEvent);
        const dx = point.x - startPoint.x;
        const dy = point.y - startPoint.y;
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
            graphInteractionState.panMoved = true;
        }
        setGraphTransform({
            ...startTransform,
            x: startTransform.x + dx,
            y: startTransform.y + dy
        });
    };

    const handleUp = upEvent => {
        svg.releasePointerCapture(upEvent.pointerId);
        svg.removeEventListener('pointermove', handleMove);
        svg.removeEventListener('pointerup', handleUp);
        svg.removeEventListener('pointercancel', handleUp);
        const shouldClearSelection = !graphInteractionState.panMoved;
        graphInteractionState.isPanning = false;
        if (shouldClearSelection) {
            clearGraphSelection();
        }
        window.setTimeout(() => {
            graphInteractionState.panMoved = false;
        }, 0);
    };

    svg.addEventListener('pointermove', handleMove);
    svg.addEventListener('pointerup', handleUp);
    svg.addEventListener('pointercancel', handleUp);
}

function zoomGraphBy(factor, centerPoint = { x: 500, y: 310 }) {
    const current = graphInteractionState.transform;
    const nextScale = Math.max(0.45, Math.min(3.2, current.scale * factor));
    const actualFactor = nextScale / current.scale;
    const nextX = centerPoint.x - (centerPoint.x - current.x) * actualFactor;
    const nextY = centerPoint.y - (centerPoint.y - current.y) * actualFactor;
    setGraphTransform({ scale: nextScale, x: nextX, y: nextY });
}

function resetGraphView() {
    setGraphTransform({ scale: 1, x: 0, y: 0 });
}

function setGraphTransform(transform) {
    graphInteractionState.transform = clampGraphTransform(transform);
    applyGraphTransform();
}

function clampGraphTransform(transform) {
    const scale = Math.max(0.45, Math.min(3.2, Number(transform.scale || 1)));
    const limitX = 1000 * Math.max(0, scale - 0.55);
    const limitY = 620 * Math.max(0, scale - 0.55);
    return {
        scale,
        x: Math.max(-limitX, Math.min(limitX, Number(transform.x || 0))),
        y: Math.max(-limitY, Math.min(limitY, Number(transform.y || 0)))
    };
}

function applyGraphTransform() {
    const viewport = document.querySelector('.graph-viewport');
    if (!viewport) return;
    const transform = graphInteractionState.transform;
    viewport.setAttribute('transform', `translate(${transform.x.toFixed(2)} ${transform.y.toFixed(2)}) scale(${transform.scale.toFixed(3)})`);
    const resetButton = document.getElementById('graph-zoom-reset');
    if (resetButton) {
        resetButton.textContent = `${Math.round(transform.scale * 100)}%`;
    }
}

function getGraphSvgPoint(svg, event) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
}

function getGraphWorldPoint(svg, event) {
    const point = getGraphSvgPoint(svg, event);
    const transform = graphInteractionState.transform;
    return {
        x: (point.x - transform.x) / transform.scale,
        y: (point.y - transform.y) / transform.scale
    };
}

function updateGraphNodePosition(nodeId) {
    const node = graphInteractionState.nodeMap.get(nodeId);
    if (!node) return;

    const nodeEl = findGraphNodeElement(nodeId);
    if (nodeEl) {
        nodeEl.setAttribute('transform', `translate(${node.x}, ${node.y})`);
    }

    document.querySelectorAll('.graph-edge').forEach(edgeEl => {
        const sourceId = edgeEl.getAttribute('data-source') || '';
        const targetId = edgeEl.getAttribute('data-target') || '';
        if (sourceId !== nodeId && targetId !== nodeId) return;

        const source = graphInteractionState.nodeMap.get(sourceId);
        const target = graphInteractionState.nodeMap.get(targetId);
        if (!source || !target) return;
        const edgeIndex = Number(edgeEl.getAttribute('data-edge-index') || 0);
        edgeEl.setAttribute('d', createGraphEdgePath(source, target, edgeIndex));
    });
}

function stabilizeGraphAfterDrag(nodeId) {
    const node = graphInteractionState.nodeMap.get(nodeId);
    if (node) {
        graphInteractionState.motionAnchors?.set(nodeId, { x: node.x, y: node.y });
    }
    const status = document.getElementById('graph-stability-status');
    if (status) {
        status.textContent = graphInteractionState.motionEnabled ? '实时动态' : '手动稳态';
        status.classList.remove('is-settling');
    }
}

function captureGraphMotionAnchors(sourceNodes = null) {
    const source = Array.isArray(sourceNodes)
        ? sourceNodes.map(node => [node.id, node])
        : [...graphInteractionState.nodeMap.entries()];
    graphInteractionState.motionAnchors = new Map(
        source.map(([id, node]) => [id, { x: Number(node.x), y: Number(node.y) }])
    );
}

function stopGraphRealtimeMotion() {
    const frameId = Number(graphInteractionState.motionFrameId || 0);
    if (frameId) window.clearTimeout(frameId);
    graphInteractionState.motionFrameId = 0;
}

function renderGraphRealtimeFrame(now) {
    if (!graphInteractionState.motionEnabled) return;
    const svg = document.querySelector('.knowledge-graph-svg');
    if (!svg || !svg.isConnected) {
        stopGraphRealtimeMotion();
        return;
    }

    const rect = svg.getBoundingClientRect();
    const isVisible = !document.hidden
        && rect.bottom > 0
        && rect.top < window.innerHeight
        && rect.right > 0
        && rect.left < window.innerWidth;

    // 约 10 FPS，且仅在图谱进入视口时更新。
    if (isVisible) {
        graphInteractionState.lastMotionAt = now;
        const seconds = now / 1000;
        let index = 0;
        graphInteractionState.nodeMap.forEach((node, nodeId) => {
            if (nodeId === graphInteractionState.draggedNodeId) {
                index += 1;
                return;
            }
            const anchor = graphInteractionState.motionAnchors?.get(nodeId);
            if (!anchor) {
                index += 1;
                return;
            }
            const phase = index * 1.618;
            const amplitude = 2.2 + (index % 4) * 0.65;
            node.x = anchor.x + Math.sin(seconds * (0.42 + (index % 3) * 0.06) + phase) * amplitude;
            node.y = anchor.y + Math.cos(seconds * (0.36 + (index % 5) * 0.035) + phase * 0.83) * amplitude * 0.72;
            const nodeEl = findGraphNodeElement(nodeId);
            nodeEl?.setAttribute('transform', `translate(${node.x.toFixed(2)}, ${node.y.toFixed(2)})`);
            index += 1;
        });

        document.querySelectorAll('.graph-edge').forEach(edgeEl => {
            const source = graphInteractionState.nodeMap.get(edgeEl.getAttribute('data-source') || '');
            const target = graphInteractionState.nodeMap.get(edgeEl.getAttribute('data-target') || '');
            if (!source || !target) return;
            const edgeIndex = Number(edgeEl.getAttribute('data-edge-index') || 0);
            edgeEl.setAttribute('d', createGraphEdgePath(source, target, edgeIndex));
        });
    }
    graphInteractionState.motionFrameId = window.setTimeout(
        () => renderGraphRealtimeFrame(performance.now()),
        100,
    );
}

function startGraphRealtimeMotion(sourceNodes = null) {
    if (!graphInteractionState.motionEnabled) return;
    stopGraphRealtimeMotion();
    if (sourceNodes || !graphInteractionState.motionAnchors?.size) {
        captureGraphMotionAnchors(sourceNodes);
    }
    const status = document.getElementById('graph-stability-status');
    if (status) {
        status.textContent = '实时动态';
        status.classList.remove('is-settling');
    }
    graphInteractionState.lastMotionAt = 0;
    graphInteractionState.motionFrameId = window.setTimeout(
        () => renderGraphRealtimeFrame(performance.now()),
        100,
    );
}

function animateGraphToLayout(targetNodes, statusText = '稳定化中') {
    const targetMap = new Map(targetNodes.map(node => [node.id, node]));
    const startMap = new Map(
        [...graphInteractionState.nodeMap.entries()].map(([id, node]) => [id, { x: node.x, y: node.y }])
    );
    const status = document.getElementById('graph-stability-status');
    if (status) {
        status.textContent = `${statusText}...`;
        status.classList.add('is-settling');
    }
    const viewport = document.querySelector('.graph-viewport');
    viewport?.classList.add('is-entering');
    if (!graphInteractionState.motionEnabled || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
        targetNodes.forEach(node => {
            const current = graphInteractionState.nodeMap.get(node.id);
            if (current) {
                current.x = node.x;
                current.y = node.y;
                updateGraphNodePosition(node.id);
            }
        });
        if (status) {
            status.textContent = '稳态';
            status.classList.remove('is-settling');
        }
        viewport?.classList.remove('is-entering');
        return;
    }

    const duration = 920;
    const startedAt = performance.now();
    const step = now => {
        const progress = Math.min(1, (now - startedAt) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        targetMap.forEach((target, id) => {
            const current = graphInteractionState.nodeMap.get(id);
            const start = startMap.get(id);
            if (!current || !start) return;
            current.x = Math.round(start.x + (target.x - start.x) * eased);
            current.y = Math.round(start.y + (target.y - start.y) * eased);
            updateGraphNodePosition(id);
        });

        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            viewport?.classList.remove('is-entering');
            startGraphRealtimeMotion(targetNodes);
        }
    };
    requestAnimationFrame(step);
}

function selectGraphNode(nodeId) {
    if (!nodeId || !graphInteractionState.nodeMap.has(nodeId)) return;
    graphInteractionState.selectedNodeId = nodeId;
    const neighborIds = getGraphNeighborIds(nodeId);

    document.querySelectorAll('.graph-node').forEach(nodeEl => {
        const currentId = nodeEl.getAttribute('data-node-id') || '';
        const isSelected = currentId === nodeId;
        const isNeighbor = neighborIds.has(currentId);
        nodeEl.classList.toggle('is-selected', isSelected);
        nodeEl.classList.toggle('is-neighbor', isNeighbor);
        nodeEl.classList.toggle('is-dimmed', !isSelected && !isNeighbor);
    });

    document.querySelectorAll('.graph-edge').forEach(edgeEl => {
        const sourceId = edgeEl.getAttribute('data-source') || '';
        const targetId = edgeEl.getAttribute('data-target') || '';
        const isActive = sourceId === nodeId || targetId === nodeId;
        edgeEl.classList.toggle('is-active', isActive);
        edgeEl.classList.toggle('is-dimmed', !isActive);
    });

    document.querySelectorAll('.graph-category-pill').forEach(button => {
        button.classList.remove('is-selected', 'is-muted');
    });
    document.querySelectorAll('.graph-psp-path').forEach(button => {
        button.classList.remove('is-selected', 'is-muted');
    });

    renderGraphNodeDetail(nodeId);
    updateGraphPanelFocus(nodeId);
}

function clearGraphSelection() {
    graphInteractionState.selectedNodeId = '';
    document.querySelectorAll('.graph-node, .graph-edge, .graph-term-chip, .graph-keyword-button, .graph-evidence-item, .graph-category-pill, .graph-psp-path').forEach(element => {
        element.classList.remove('is-selected', 'is-neighbor', 'is-dimmed', 'is-active', 'is-muted');
    });
    renderGraphNodeDetail('');
    resetGraphPanelFocus();
}

function highlightPspPath(pathNodes, sourceButton = null) {
    const nodes = (pathNodes || []).map(item => String(item || '')).filter(node => graphInteractionState.nodeMap.has(node));
    if (nodes.length < 2) return;
    graphInteractionState.selectedNodeId = '';
    const nodeSet = new Set(nodes);
    const segmentSet = new Set(nodes.slice(0, -1).map((node, index) => `${node}\t${nodes[index + 1]}`));

    document.querySelectorAll('.graph-node').forEach(nodeEl => {
        const nodeId = nodeEl.getAttribute('data-node-id') || '';
        const isPathNode = nodeSet.has(nodeId);
        nodeEl.classList.toggle('is-selected', nodeId === nodes[0]);
        nodeEl.classList.toggle('is-neighbor', isPathNode && nodeId !== nodes[0]);
        nodeEl.classList.toggle('is-dimmed', !isPathNode);
    });

    document.querySelectorAll('.graph-edge').forEach(edgeEl => {
        const sourceId = edgeEl.getAttribute('data-source') || '';
        const targetId = edgeEl.getAttribute('data-target') || '';
        const isPathEdge = segmentSet.has(`${sourceId}\t${targetId}`);
        edgeEl.classList.toggle('is-active', isPathEdge);
        edgeEl.classList.toggle('is-dimmed', !isPathEdge);
    });

    document.querySelectorAll('.graph-term-chip, .graph-keyword-button, .graph-evidence-item, .graph-category-pill').forEach(element => {
        element.classList.remove('is-selected');
        element.classList.add('is-muted');
    });
    document.querySelectorAll('.graph-psp-path').forEach(button => {
        const isSelected = button === sourceButton;
        button.classList.toggle('is-selected', isSelected);
        button.classList.toggle('is-muted', !isSelected);
    });
    renderGraphPathDetail(nodes);
}

function highlightGraphCategory(category) {
    if (!category) return;
    clearGraphSelection();
    document.querySelectorAll('.graph-node').forEach(nodeEl => {
        const nodeId = nodeEl.getAttribute('data-node-id') || '';
        const node = graphInteractionState.nodeMap.get(nodeId);
        const isActive = node && node.category === category;
        nodeEl.classList.toggle('is-neighbor', Boolean(isActive));
        nodeEl.classList.toggle('is-dimmed', !isActive);
    });
    document.querySelectorAll('.graph-edge').forEach(edgeEl => {
        const source = graphInteractionState.nodeMap.get(edgeEl.getAttribute('data-source') || '');
        const target = graphInteractionState.nodeMap.get(edgeEl.getAttribute('data-target') || '');
        const isActive = source?.category === category || target?.category === category;
        edgeEl.classList.toggle('is-active', Boolean(isActive));
        edgeEl.classList.toggle('is-dimmed', !isActive);
    });
    document.querySelectorAll('.graph-category-pill').forEach(button => {
        const isSelected = button.getAttribute('data-category-filter') === category;
        button.classList.toggle('is-selected', isSelected);
        button.classList.toggle('is-muted', !isSelected);
    });
    updateGraphCategoryPanelFocus(category);
}

function getGraphNeighborIds(nodeId) {
    const neighbors = new Set();
    graphInteractionState.edges.forEach(edge => {
        if (edge.source === nodeId) neighbors.add(edge.target);
        if (edge.target === nodeId) neighbors.add(edge.source);
    });
    return neighbors;
}

function findGraphNodeElement(nodeId) {
    return [...document.querySelectorAll('.graph-node')]
        .find(nodeEl => (nodeEl.getAttribute('data-node-id') || '') === nodeId) || null;
}

function updateGraphPanelFocus(nodeId) {
    const selectedNode = graphInteractionState.nodeMap.get(nodeId);
    const selectedCategory = selectedNode?.category || '';
    document.querySelectorAll('.graph-term-chip, .graph-keyword-button, .graph-evidence-item').forEach(item => {
        const isSelected = item.getAttribute('data-term-id') === nodeId;
        item.classList.toggle('is-selected', isSelected);
        item.classList.toggle('is-muted', !isSelected);
    });
    document.querySelectorAll('.graph-category-pill').forEach(button => {
        const isSelectedCategory = button.getAttribute('data-category-filter') === selectedCategory;
        button.classList.toggle('is-selected', isSelectedCategory);
        button.classList.toggle('is-muted', !isSelectedCategory);
    });
    document.querySelectorAll('.graph-analysis-card').forEach(card => {
        card.classList.toggle('has-selection', Boolean(nodeId));
    });
}

function updateGraphCategoryPanelFocus(category) {
    document.querySelectorAll('.graph-term-chip, .graph-keyword-button, .graph-evidence-item').forEach(item => {
        const nodeId = item.getAttribute('data-term-id') || '';
        const node = graphInteractionState.nodeMap.get(nodeId);
        const isActive = node?.category === category;
        item.classList.remove('is-selected');
        item.classList.toggle('is-muted', !isActive);
    });
    document.querySelectorAll('.graph-analysis-card').forEach(card => {
        card.classList.toggle('has-selection', Boolean(category));
    });
}

function resetGraphPanelFocus() {
    document.querySelectorAll('.graph-term-chip, .graph-keyword-button, .graph-evidence-item, .graph-category-pill').forEach(item => {
        item.classList.remove('is-selected', 'is-muted');
    });
    document.querySelectorAll('.graph-analysis-card').forEach(card => {
        card.classList.remove('has-selection');
    });
}

function renderGraphNodeDetail(nodeId) {
    const panel = document.getElementById('graph-detail-panel');
    if (!panel) return;
    if (!nodeId) {
        const evidenceNodes = [...graphInteractionState.nodeMap.values()]
            .filter(node => Array.isArray(node.papers) && node.papers.length > 0)
            .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
            .slice(0, 5);
        panel.innerHTML = `
            <div class="graph-card-title">
                <h4>文献证据</h4>
                <span>点击节点后聚焦</span>
            </div>
            <div class="graph-evidence-list">
                ${evidenceNodes.map(node => renderGraphEvidenceSeed(node)).join('') || '<p>暂无代表文献标题。</p>'}
            </div>
        `;
        panel.querySelectorAll('.graph-evidence-item').forEach(button => {
            button.addEventListener('click', () => selectGraphNode(button.getAttribute('data-term-id') || ''));
        });
        return;
    }

    const node = graphInteractionState.nodeMap.get(nodeId);
    if (!node) return;
    const relatedEdges = graphInteractionState.edges
        .filter(edge => edge.source === nodeId || edge.target === nodeId)
        .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0));
    const categoryLabel = {
        MATERIAL: '材料',
        PROCESS: '工艺',
        STRUCTURE: '组织',
        PROPERTY: '性能',
        material: '材料',
        property: '性能',
        method: '工艺',
        keyword: '组织'
    }[node.category] || node.category || '未知类型';
    const paperDetails = getGraphNodePaperDetails(node);

    panel.innerHTML = `
        <div class="graph-card-title">
            <h4>${formatTrendTerm(node.label)}</h4>
            <span>节点详情</span>
        </div>
        <div class="graph-detail-meta">
            <span>${escapeHtml(categoryLabel)}</span>
            <strong>${escapeHtml(paperDetails.length || node.count || 0)} 篇相关文献</strong>
        </div>
        <div class="graph-related-grid">
            ${relatedEdges.slice(0, 8).map(edge => {
                const neighbor = edge.source === nodeId ? edge.target : edge.source;
                return `
                    <button type="button" class="graph-related-node" data-related-node-id="${escapeAttribute(neighbor)}">
                        <span>${formatTrendTerm(neighbor)}</span>
                        <strong>${escapeHtml(edge.weight)}次</strong>
                    </button>
                `;
            }).join('') || '<p>暂无共现节点。</p>'}
        </div>
        <div class="graph-paper-browser">
            <div class="graph-paper-browser-title">
                <h5>全部相关文献</h5>
                <span>点击弹出详情</span>
            </div>
            <div class="graph-paper-list">
                ${paperDetails.map((paper, index) => renderGraphPaperButton(paper, index)).join('') || '<p>暂无相关文献。</p>'}
            </div>
        </div>
    `;
    panel.querySelectorAll('.graph-related-node').forEach(button => {
        button.addEventListener('click', () => {
            selectGraphNode(button.getAttribute('data-related-node-id') || '');
        });
    });
    panel.querySelectorAll('.graph-paper-item').forEach(button => {
        button.addEventListener('click', () => {
            const index = Number(button.getAttribute('data-paper-index') || 0);
            panel.querySelectorAll('.graph-paper-item').forEach(item => {
                item.classList.toggle('is-selected', item === button);
            });
            openGraphPaperModal(paperDetails[index]);
        });
    });
}

function renderGraphPathDetail(pathNodes) {
    const panel = document.getElementById('graph-detail-panel');
    if (!panel) return;
    const nodes = pathNodes
        .map(nodeId => graphInteractionState.nodeMap.get(nodeId))
        .filter(Boolean);
    const nodeIds = nodes.map(node => node.id);
    panel.innerHTML = `
        <div class="graph-card-title">
            <h4>机制链路</h4>
            <span>路径聚焦</span>
        </div>
        <div class="graph-path-detail-flow">
            ${nodes.map((node, index) => `
                <button type="button" class="graph-path-detail-node graph-path-detail-node-${escapeAttribute(node.category || '')}" data-path-node-id="${escapeAttribute(node.id)}">
                    <small>${escapeHtml(graphCategoryLabel(node.category))}</small>
                    <strong>${formatTrendTerm(node.label || node.id)}</strong>
                </button>
                ${index < nodes.length - 1 ? '<span class="graph-path-detail-arrow">→</span>' : ''}
            `).join('')}
        </div>
        <div class="graph-detail-meta">
            <span>操作</span>
            <strong>点击任一节点只刷新下方结果；路径聚焦状态保持不变</strong>
        </div>
        <div class="graph-path-result" id="graph-path-result">
            ${renderGraphPathPaperResults(nodeIds)}
        </div>
    `;
    panel.querySelectorAll('.graph-path-detail-node').forEach(button => {
        button.addEventListener('click', () => {
            const nodeId = button.getAttribute('data-path-node-id') || '';
            panel.querySelectorAll('.graph-path-detail-node').forEach(item => {
                item.classList.toggle('is-selected', item === button);
            });
            const resultPanel = document.getElementById('graph-path-result');
            if (resultPanel) {
                resultPanel.innerHTML = renderGraphPathPaperResults(nodeIds, nodeId);
                bindGraphPathPaperResults(resultPanel);
            }
        });
    });
    bindGraphPathPaperResults(panel.querySelector('#graph-path-result'));
}

function renderGraphPathPaperResults(pathNodeIds, activeNodeId = '') {
    const targetNodeIds = activeNodeId ? [activeNodeId] : pathNodeIds;
    const papers = [];
    const seen = new Set();
    targetNodeIds.forEach(nodeId => {
        const node = graphInteractionState.nodeMap.get(nodeId);
        getGraphNodePaperDetails(node).forEach(paper => {
            const key = paper.doi || paper.paperId || paper.title;
            if (!key || seen.has(key)) return;
            seen.add(key);
            papers.push({
                ...paper,
                evidenceNode: node?.label || node?.id || nodeId,
            });
        });
    });
    const title = activeNodeId
        ? `${graphInteractionState.nodeMap.get(activeNodeId)?.label || activeNodeId} 相关文献`
        : '链路相关文献';
    graphInteractionState.pathResultPapers = papers.slice(0, 12);
    return `
        <div class="graph-paper-browser-title">
            <h5>${formatTrendTerm(title)}</h5>
            <span>${escapeHtml(papers.length)} 篇 · 点击弹出详情</span>
        </div>
        <div class="graph-paper-list graph-path-paper-list">
            ${papers.slice(0, 12).map((paper, index) => renderGraphPaperButton(paper, index)).join('') || '<p>暂无相关文献。</p>'}
        </div>
    `;
}

function bindGraphPathPaperResults(container) {
    if (!container) return;
    const paperItems = [...container.querySelectorAll('.graph-paper-item')];
    paperItems.forEach(button => {
        button.addEventListener('click', () => {
            const index = Number(button.getAttribute('data-paper-index') || 0);
            container.querySelectorAll('.graph-paper-item').forEach(item => {
                item.classList.toggle('is-selected', item === button);
            });
            if (graphInteractionState.pathResultPapers?.[index]) {
                openGraphPaperModal(graphInteractionState.pathResultPapers[index]);
            }
        });
    });
}

async function refreshTrendTopics() {
    try {
        const params = buildTrendFilterParams();
        const response = await fetch(`/api/trends/topics?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            addLog(`加载热点主题失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        trendTopics = result.topics || [];
        fillTrendTopicSelects();
        if (trendTopics.length > 0) {
            await loadSelectedTrend({ switchPreview: false });
        } else {
            document.getElementById('trend-content').innerHTML = '<p>还没有可分析的检索 CSV。</p>';
        }
    } catch (error) {
        addLog(`加载热点主题失败: ${error.message}`, 'error');
    }
}

function buildTrendFilterParams(extra = {}) {
    const params = new URLSearchParams();
    const windowValue = document.getElementById('trend-window-select')?.value || 'all';
    const publicationYears = document.getElementById('trend-publication-window-select')?.value || 'all';
    const sourceMode = document.getElementById('trend-source-select')?.value || 'csv_all';
    const currentCsv = document.getElementById('preview-csv-select')?.value
        || document.getElementById('graph-csv-select')?.value
        || document.getElementById('input-csv')?.value
        || '';
    params.set('window_days', windowValue);
    params.set('publication_years', publicationYears);
    params.set('source_mode', sourceMode);
    if (currentCsv) {
        params.set('current_csv', currentCsv);
    }
    Object.entries(extra).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            params.set(key, value);
        }
    });
    return params;
}

function fillTrendTopicSelects() {
    const selects = Array.from(document.querySelectorAll('.trend-analysis-topic'));

    selects.forEach(select => {
        if (!select) return;
        const currentValue = select.value;
        select.innerHTML = '';

        if (trendTopics.length === 0) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = '暂无历史主题';
            select.appendChild(option);
            return;
        }

        trendTopics.forEach(topic => {
            const option = document.createElement('option');
            option.value = topic.key;
            option.textContent = `${topic.label} · ${topic.entry_count}次 · ${topic.total_papers}篇`;
            select.appendChild(option);
        });

        if (currentValue && trendTopics.some(topic => topic.key === currentValue)) {
            select.value = currentValue;
        }
    });
    updateTrendTopicRowControls();
}

function selectedTrendTopicKeys() {
    const keys = Array.from(document.querySelectorAll('.trend-analysis-topic'))
        .map(select => select.value)
        .filter(Boolean);
    return Array.from(new Set(keys));
}

function addTrendTopicRow() {
    const list = document.getElementById('trend-topic-list');
    if (!list || document.querySelectorAll('.trend-analysis-topic').length >= 2) return;

    const row = document.createElement('div');
    row.className = 'trend-topic-row';
    row.innerHTML = `
        <div class="form-group">
            <label for="trend-topic-select-2">主题 2</label>
            <select id="trend-topic-select-2" name="trend_topic_compare" class="trend-analysis-topic" autocomplete="off"></select>
        </div>
        <button type="button" class="btn btn-light trend-remove-topic-btn" aria-label="移除对比主题">
            <i class="fas fa-times"></i>
        </button>
    `;
    row.querySelector('.trend-remove-topic-btn')?.addEventListener('click', () => {
        row.remove();
        updateTrendTopicRowControls();
    });
    list.appendChild(row);
    fillTrendTopicSelects();

    if (trendTopics.length > 1) {
        const secondSelect = row.querySelector('.trend-analysis-topic');
        if (secondSelect) secondSelect.value = trendTopics[1].key;
    }
    updateTrendTopicRowControls();
}

function updateTrendTopicRowControls() {
    const canAdd = document.querySelectorAll('.trend-analysis-topic').length < 2 && trendTopics.length > 1;
    const addButton = document.getElementById('add-trend-topic-btn');
    if (addButton) addButton.disabled = !canAdd;
}

async function loadSelectedTrend(options = {}) {
    const shouldSwitchPreview = options.switchPreview !== false;
    const topicKey = selectedTrendTopicKeys()[0];
    if (!topicKey) return;

    try {
        showLoading(true, 'load-trend-btn');
        const params = buildTrendFilterParams({ topic: topicKey });
        const response = await fetch(`/api/trends?${params.toString()}`);
        const result = await response.json();

        if (!response.ok) {
            addLog(`加载热点失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        renderTrendSummary(result);
        if (shouldSwitchPreview) {
            showPreviewTab('trend');
        }
    } catch (error) {
        addLog(`加载热点失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'load-trend-btn');
    }
}

async function loadTrendAnalysis(options = {}) {
    const selectedTopics = selectedTrendTopicKeys();
    if (selectedTopics.length <= 1) {
        return loadSelectedTrend(options);
    }
    return loadTrendComparison(selectedTopics[0], selectedTopics[1]);
}

async function loadTrendComparison(topicA, topicB) {
    if (!topicA || !topicB) return;
    if (topicA === topicB) {
        addLog('请选择两个不同主题进行对比', 'warning');
        return;
    }

    try {
        showLoading(true, 'load-trend-btn');
        const params = buildTrendFilterParams({ topic_a: topicA, topic_b: topicB });
        const response = await fetch(`/api/trends/compare?${params.toString()}`);
        const result = await response.json();

        if (!response.ok) {
            addLog(`主题对比失败: ${result.error || '未知错误'}`, 'error');
            return;
        }

        renderTrendComparison(result);
        showPreviewTab('trend');
    } catch (error) {
        addLog(`主题对比失败: ${error.message}`, 'error');
    } finally {
        showLoading(false, 'load-trend-btn');
    }
}

function renderTrendSummary(data) {
    const timeline = data.timeline || [];
    const maxPapers = Math.max(1, ...timeline.map(item => Number(item.paper_count || 0)));
    const dateRange = data.date_range || {};
    trendEvidenceStore = {};

    document.getElementById('trend-info').textContent = `${data.topic_label || data.topic_key} · ${dateRange.start || '-'} 至 ${dateRange.end || '-'}`;
    document.getElementById('trend-content').innerHTML = `
        <div class="trend-dashboard">
            <div class="trend-stat-grid">
                ${renderTrendStat('检索批次', data.entry_count || 0, '次')}
                ${renderTrendStat('唯一文献', data.total_papers || 0, '篇')}
                ${renderTrendStat('首次检索', dateRange.start || '-', '')}
                ${renderTrendStat('最近检索', dateRange.end || '-', '')}
            </div>

            <section class="trend-panel trend-panel-wide">
                <div class="trend-section-title">
                    <h4>检索批次新增文献</h4>
                    <span>${timeline.length} 个历史节点</span>
                </div>
                <div class="trend-timeline">
                    ${timeline.map(item => renderTimelineItem(item, maxPapers)).join('') || '<p>暂无时间线数据。</p>'}
                </div>
            </section>

            <div class="trend-panel-grid">
                ${renderTermPanel(
                    data.hot_keyword_mode === 'rising' ? '近期升温研究词' : '当前高频研究词',
                    data.hot_keywords || [],
                    'score',
                    data.hot_keyword_note || ''
                )}
                ${renderTermPanel(
                    '研究方向簇',
                    data.direction_clusters || [],
                    'count',
                    '材料、工艺与问题在同一篇文献中共同出现',
                    'trend-direction-panel'
                )}
                ${renderTermPanel('反复出现的研究主题', data.recurring_terms || [], 'days')}
                ${renderTermPanel('常见方法', data.top_methods || [], 'count')}
                ${renderTermPanel('材料体系', data.top_materials || [], 'count')}
                ${renderTermPanel(
                    data.author_activity_mode === 'emerging' ? '新增活跃作者' : '当前活跃作者',
                    data.author_activity || [],
                    'count',
                    data.author_activity_mode === 'emerging' ? '近期检索批次中首次出现的作者' : '需至少两个检索批次后识别新增作者'
                )}
                ${renderTermPanel(
                    data.institution_activity_mode === 'emerging' ? '新增活跃机构' : '当前活跃机构',
                    data.institution_activity || [],
                    'count',
                    data.institution_activity_mode === 'emerging' ? '近期检索批次中首次出现的机构' : '需至少两个检索批次后识别新增机构'
                )}
            </div>
        </div>
    `;
}

function renderTrendComparison(result) {
    const topicA = result.topic_a || {};
    const topicB = result.topic_b || {};
    trendEvidenceStore = {};
    document.getElementById('trend-info').textContent = `${topicA.topic_label || '主题 A'} vs ${topicB.topic_label || '主题 B'}`;
    document.getElementById('trend-content').innerHTML = `
        <div class="trend-dashboard">
            <div class="trend-compare-summary">
                ${renderCompareCard('主题 A', topicA)}
                ${renderCompareCard('主题 B', topicB)}
            </div>

            <div class="trend-panel-grid trend-panel-grid-compare">
                ${renderComparisonTermPanel('共同关键词', result.common_keywords || [], 'count_a', 'count_b')}
                ${renderComparisonTermPanel('共同作者', result.common_authors || [], 'count_a', 'count_b')}
                ${renderComparisonTermPanel('共同机构', result.common_institutions || [], 'count_a', 'count_b')}
                ${renderTermPanel(`${topicA.topic_label || '主题 A'} 独有热点`, result.unique_a || [], 'count')}
                ${renderTermPanel(`${topicB.topic_label || '主题 B'} 独有热点`, result.unique_b || [], 'count')}
            </div>
        </div>
    `;
}

function renderTrendStat(label, value, suffix) {
    return `
        <div class="trend-stat">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}${suffix ? `<small>${escapeHtml(suffix)}</small>` : ''}</strong>
        </div>
    `;
}

function renderTimelineItem(item, maxPapers) {
    const count = Number(item.paper_count || 0);
    const width = scaledBarWidth(count, maxPapers, 3, 1.25);
    const keywords = (item.top_keywords || []).map(keyword => keyword.term).slice(0, 4).join(' · ');
    const keywordMarkup = (item.top_keywords || [])
        .map(keyword => formatTrendTerm(keyword.term))
        .slice(0, 4)
        .join(' · ');
    const sourcePath = item.report_path || item.csv_path || '';
    return `
        <div class="trend-timeline-item">
            <div class="trend-timeline-date">${escapeHtml(item.date || '-')}</div>
            <div class="trend-timeline-track">
                <div class="trend-timeline-bar" style="width: ${width}%"></div>
            </div>
            <div class="trend-timeline-meta">
                <strong>${escapeHtml(count)} 篇新增</strong>
                <span title="${escapeAttribute(keywords || sourcePath || '暂无关键词')}">${keywordMarkup || escapeHtml(sourcePath || '暂无关键词')}</span>
            </div>
        </div>
    `;
}

function renderTermPanel(title, items, valueKey, note = '', panelClass = '') {
    const maxValue = Math.max(1, ...items.map(item => Number(item[valueKey] || 0)));
    return `
        <section class="trend-panel ${escapeAttribute(panelClass)}">
            <div class="trend-section-title">
                <h4>${escapeHtml(title)}</h4>
                ${note ? `<span class="trend-section-note" title="${escapeAttribute(note)}">${escapeHtml(note)}</span>` : ''}
            </div>
            <div class="trend-term-list">
                ${items.map(item => renderTermRow(item, valueKey, maxValue)).join('') || '<p>暂无可统计条目。</p>'}
            </div>
        </section>
    `;
}

function renderTermRow(item, valueKey, maxValue) {
    const term = item.term || '';
    const value = item[valueKey];
    const numericValue = Number(value || 0);
    const width = scaledBarWidth(numericValue, maxValue, 3, 1.35);
    const evidenceId = registerTrendEvidence(term, item.evidence || []);
    const valueLabel = item.value_label || numericValue;
    const detail = item.detail || '';
    return `
        <div class="trend-term-item">
            <div class="trend-term-row">
                ${renderTrendTermButton(term, evidenceId)}
                <div class="trend-term-track">
                    <div class="trend-term-bar" style="width: ${width}%"></div>
                </div>
                <div class="trend-term-value">${escapeHtml(valueLabel)}</div>
            </div>
            ${detail ? `<div class="trend-term-detail">${escapeHtml(detail)}</div>` : ''}
        </div>
    `;
}

function registerTrendEvidence(term, evidence) {
    const id = `trend-evidence-${Object.keys(trendEvidenceStore).length + 1}`;
    trendEvidenceStore[id] = {
        term,
        evidence: evidence || [],
    };
    return id;
}

function renderTrendTermButton(term, evidenceId) {
    return `
        <button type="button" class="trend-term-label trend-term-button" data-trend-evidence-id="${escapeAttribute(evidenceId)}" title="${escapeAttribute(term)}">
            ${formatTrendTerm(term)}
        </button>
    `;
}

function renderTrendEvidenceList(evidence) {
    if (!evidence || evidence.length === 0) {
        return '<p class="trend-evidence-empty">暂无可展开的论文依据。</p>';
    }
    return `
        <div class="trend-evidence-list">
            ${evidence.map(item => `
                <article class="trend-evidence-item">
                    <strong>${escapeHtml(item.title || '未命名文献')}</strong>
                    ${item.snippet ? `<p>${escapeHtml(item.snippet)}</p>` : ''}
                    <span>${escapeHtml(item.source_path || '')}${item.date ? ` · ${escapeHtml(item.date)}` : ''}</span>
                </article>
            `).join('')}
        </div>
    `;
}

function handleTrendEvidenceClick(event) {
    const button = event.target.closest('.trend-term-button');
    if (!button) return;
    const evidenceId = button.dataset.trendEvidenceId;
    const payload = trendEvidenceStore[evidenceId];
    if (!payload) return;
    openTrendEvidenceModal(payload.term, payload.evidence || []);
}

function ensureTrendEvidenceModal() {
    let modal = document.getElementById('trend-evidence-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'trend-evidence-modal';
    modal.className = 'trend-evidence-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="trend-evidence-modal-backdrop" data-trend-evidence-close></div>
        <section class="trend-evidence-modal-panel" role="dialog" aria-modal="true" aria-label="热点词依据">
            <button type="button" class="trend-evidence-modal-close" data-trend-evidence-close aria-label="关闭依据弹窗">
                <i class="fas fa-times"></i>
            </button>
            <div class="trend-evidence-modal-content" id="trend-evidence-modal-content"></div>
        </section>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-trend-evidence-close]').forEach(item => {
        item.addEventListener('click', closeTrendEvidenceModal);
    });
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closeTrendEvidenceModal();
        }
    });
    return modal;
}

function openTrendEvidenceModal(term, evidence) {
    const modal = ensureTrendEvidenceModal();
    const content = modal.querySelector('#trend-evidence-modal-content');
    content.innerHTML = `
        <div class="trend-evidence-modal-header">
            <span>热点词依据</span>
            <h3>${formatTrendTerm(term || '-')}</h3>
            <p>${escapeHtml((evidence || []).length)} 篇相关文献</p>
        </div>
        ${renderTrendEvidenceList(evidence || [])}
    `;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('trend-evidence-modal-open');
    activateManagedModal(modal, modal.querySelector('.trend-evidence-modal-close'));
}

function closeTrendEvidenceModal() {
    const modal = document.getElementById('trend-evidence-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('trend-evidence-modal-open');
    deactivateManagedModal(modal);
}

function scaledBarWidth(value, maxValue, minWidth = 3, contrastPower = 1.3) {
    const numericValue = Math.max(0, Number(value || 0));
    const numericMax = Math.max(1, Number(maxValue || 1));
    if (numericValue <= 0) return 0;
    const ratio = Math.min(1, numericValue / numericMax);
    return Math.round(minWidth + Math.pow(ratio, contrastPower) * (100 - minWidth));
}

function renderCompareCard(label, topic) {
    const dateRange = topic.date_range || {};
    return `
        <section class="trend-compare-card">
            <span>${escapeHtml(label)}</span>
            <h4>${escapeHtml(topic.topic_label || topic.topic_key || '-')}</h4>
            <div class="trend-compare-metrics">
                <strong>${escapeHtml(topic.entry_count || 0)}个检索批次</strong>
                <strong>${escapeHtml(topic.total_papers || 0)}篇唯一文献</strong>
                <strong>${escapeHtml(dateRange.start || '-')} - ${escapeHtml(dateRange.end || '-')}</strong>
            </div>
        </section>
    `;
}

function renderComparisonTermPanel(title, items, keyA, keyB) {
    return `
        <section class="trend-panel">
            <div class="trend-section-title">
                <h4>${escapeHtml(title)}</h4>
            </div>
            <div class="trend-term-list">
                ${items.map(item => `
                    <div class="trend-term-item">
                        <div class="trend-common-row">
                            ${renderTrendTermButton(item.term || '', registerTrendEvidence(item.term || '', item.evidence || []))}
                            <span>A ${escapeHtml(item[keyA] || 0)} · B ${escapeHtml(item[keyB] || 0)}</span>
                        </div>
                    </div>
                `).join('') || '<p>暂无共同关键词。</p>'}
            </div>
        </section>
    `;
}

// 清空日志
function clearLog() {
    document.getElementById('log-content').innerHTML = `
        <div class="log-empty-state">
            <span class="writing-loader writing-loader-large" aria-hidden="true">
                <span class="writing-paper">
                    <span></span>
                    <span></span>
                    <span></span>
                </span>
                <span class="writing-pencil"></span>
            </span>
        </div>
    `;
}

function shouldRecordRunLog(message) {
    return RUN_LOG_MESSAGE_RE.test(String(message || ''));
}

function shouldNotifyLog(message, type = 'info', options = {}) {
    if (options.toast === false) return false;
    if (options.toast === true) return true;
    if (type === 'error' || type === 'warning') return true;
    return ACTION_NOTIFICATION_RE.test(String(message || ''));
}

function ensureToastContainer() {
    let container = document.getElementById('toast-container');
    if (container) return container;

    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    container.setAttribute('aria-atomic', 'false');
    document.body.appendChild(container);
    return container;
}

function getToastIcon(type = 'info') {
    if (type === 'error') return 'fa-circle-exclamation';
    if (type === 'warning') return 'fa-triangle-exclamation';
    if (type === 'success') return 'fa-circle-check';
    return 'fa-circle-info';
}

function dismissToast(toast) {
    if (!toast) return;
    toast.classList.remove('is-visible');
    toast.classList.add('is-hiding');
    window.setTimeout(() => {
        toast.remove();
    }, 220);
}

function notifyUser(message, type = 'info', options = {}) {
    const text = String(message || '').trim();
    if (!text) return;

    const container = ensureToastContainer();
    let normalizedType = ['info', 'success', 'warning', 'error'].includes(type) ? type : 'info';
    if (
        normalizedType === 'info'
        && /(完成|成功|已创建|已删除|已加入|已上传|已选择|状态已|缓存已|已清空|已回退)/.test(text)
    ) {
        normalizedType = 'success';
    }
    const toast = document.createElement('div');
    toast.className = `toast-message toast-${normalizedType}`;
    toast.setAttribute('role', normalizedType === 'error' ? 'alert' : 'status');
    toast.innerHTML = `
        <i class="fas ${getToastIcon(normalizedType)} toast-icon" aria-hidden="true"></i>
        <span class="toast-text">${escapeHtml(text)}</span>
        <button type="button" class="toast-close" aria-label="关闭提示">
            <i class="fas fa-times" aria-hidden="true"></i>
        </button>
    `;

    container.appendChild(toast);
    const maxToasts = Number(options.maxToasts || 5);
    while (container.children.length > maxToasts) {
        dismissToast(container.firstElementChild);
    }

    toast.querySelector('.toast-close')?.addEventListener('click', () => dismissToast(toast));
    requestAnimationFrame(() => toast.classList.add('is-visible'));

    const duration = Number(options.duration || (normalizedType === 'error' ? 5200 : 3200));
    if (duration > 0) {
        window.setTimeout(() => dismissToast(toast), duration);
    }
}

// 添加运行日志：只记录文献检索、日报/综述生成和一键流程
function addLog(message, type = 'info', options = {}) {
    if (shouldNotifyLog(message, type, options)) {
        notifyUser(message, type, options);
    }

    if (!options.force && !shouldRecordRunLog(message)) {
        return;
    }

    const logContent = document.getElementById('log-content');
    const timestamp = new Date().toLocaleTimeString();
    
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry log-${type}`;
    logEntry.innerHTML = `[${timestamp}] ${escapeHtml(message)}`;
    
    // 如果是第一条日志，清除占位符
    if (logContent.querySelector('p') || logContent.querySelector('.log-empty-state')) {
        logContent.innerHTML = '';
    }
    
    logContent.appendChild(logEntry);
    while (logContent.children.length > MAX_RUN_LOG_ENTRIES) {
        logContent.removeChild(logContent.firstElementChild);
    }
    logContent.scrollTop = logContent.scrollHeight;
}

// 显示/隐藏加载状态
function showLoading(show, buttonId) {
    const button = document.getElementById(buttonId);
    if (!button) return;
    button.dataset.loading = show ? 'true' : 'false';
    if (show) {
        button.disabled = true;
        if (buttonId === 'generate-btn') {
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 生成中...';
        } else {
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 处理中...';
        }
    } else {
        button.disabled = false;
        // 恢复按钮原始文本（需要根据按钮类型调整）
        if (buttonId === 'search-btn') {
            button.innerHTML = '<i class="fas fa-search"></i> 开始检索';
        } else if (buttonId === 'generate-btn') {
            button.innerHTML = '<i class="fas fa-file-alt"></i> 生成综述';
        } else if (buttonId === 'browse-csv') {
            button.innerHTML = '<i class="fas fa-folder-open"></i> 浏览';
        } else if (buttonId === 'enrich-preview-csv') {
            button.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> 多源补全';
        } else if (buttonId === 'browse-output') {
            button.innerHTML = '<i class="fas fa-folder-open"></i> 浏览';
        } else if (buttonId === 'open-report-location') {
            button.innerHTML = '<i class="fas fa-folder-open"></i> 浏览';
        } else if (buttonId === 'generate-graph-btn') {
            button.innerHTML = '<i class="fas fa-circle-nodes"></i> 生成图谱';
        } else if (buttonId === 'load-trend-btn') {
            button.innerHTML = '<i class="fas fa-chart-area"></i> 分析热点';
        }
    }
}

// 启动任务轮询
function startTaskPolling(taskId, progressType = 'search') {
    const shouldLogTask = RUN_LOG_TASK_RE.test(taskId);
    const taskLogOptions = { force: shouldLogTask, toast: progressType !== 'graph' && progressType !== 'report' };
    // 显示进度条容器；综述生成只使用按钮状态，不显示进度条。
    const progressPrefix = progressType === 'report' ? 'report' : (progressType === 'graph' ? 'graph' : 'search');
    const progressContainer = document.getElementById(`${progressPrefix}-progress-container`);
    const progressBar = document.getElementById(`${progressPrefix}-progress-fill`);
    const progressText = document.getElementById(`${progressPrefix}-progress-text`);
    
    if (progressContainer && progressType !== 'report') {
        progressContainer.style.display = 'block';
        progressBar.style.width = '0%';
        progressText.textContent = '0%';
    }
    
    taskLogOffsets[taskId] = 0;
    let polling = false;
    tasks[taskId] = setInterval(async () => {
        // A slow response must not start another poll for the same task. Overlapping
        // polls used to duplicate logs and completion rendering, which could freeze
        // the literature page on slow machines.
        if (polling) return;
        polling = true;
        try {
            const since = taskLogOffsets[taskId] || 0;
            const response = await fetch(`/api/task/${taskId}?since=${since}`);
            const task = await response.json();
            
            if (response.ok) {
                const newLogs = Array.isArray(task.logs) ? task.logs : [];
                newLogs.forEach(log => addLog(log.message, 'info', taskLogOptions));
                taskLogOffsets[taskId] = Number.isFinite(Number(task.log_count))
                    ? Number(task.log_count)
                    : since + newLogs.length;
                
                // 更新进度条
                if (progressType !== 'report' && progressBar && progressText) {
                    const progress = Number.isFinite(Number(task.progress))
                        ? Math.min(100, Number(task.progress))
                        : Math.min(100, (taskLogOffsets[taskId] || 0) * 10);
                    const latestLog = newLogs.length
                        ? newLogs[newLogs.length - 1].message
                        : '';
                    if (progressType === 'graph') {
                        setGraphProgress(progress, latestLog);
                    } else {
                        progressBar.style.width = `${progress}%`;
                        progressText.textContent = `${Math.round(progress)}%`;
                    }
                }
                
                // 更新状态指示器
                updateStatusIndicator(task.status);
                
                // 如果任务完成或失败，停止轮询
                if (task.status === 'completed' || task.status === 'failed') {
                    clearInterval(tasks[taskId]);
                    delete tasks[taskId];
                    delete taskLogOffsets[taskId];
                    
                    if (progressContainer) {
                        progressContainer.style.display = 'none';
                    }
                    if (progressType === 'graph') {
                        showLoading(false, 'generate-graph-btn');
                    } else if (progressType === 'report') {
                        showLoading(false, 'generate-btn');
                        syncReportGenerateButton();
                    }
                    
                    if (task.status === 'completed') {
                        addLog(`任务 ${taskId} 已完成`, 'info', taskLogOptions);
                        if (progressType === 'graph') {
                            if (task.result && Array.isArray(task.result.nodes)) {
                                updateGraphBuildAnimation(100, '图谱构建完成，正在加载可视化...');
                                currentGraphData = task.result;
                                renderKnowledgeGraph(task.result);
                                logKnowledgeGraphResult(task.result);
                                showPreviewTab('graph');
                            }
                            return;
                        }
                        let resultCsvPath = task.result && task.result.csv_path ? task.result.csv_path : '';
                        if (progressType === 'search') {
                            if (resultCsvPath) {
                                document.getElementById('input-csv').value = resultCsvPath;
                                currentCsvPath = resultCsvPath;
                            }
                            addLog(
                                resultCsvPath
                                    ? `检索结果已保存：${resultCsvPath}`
                                    : '检索完成，但没有返回可预览的文献。',
                                'info',
                                taskLogOptions,
                            );
                            if (resultCsvPath) {
                                await refreshFileList({
                                    activatePreview: false,
                                    preferredCsv: resultCsvPath,
                                    previewCsv: false,
                                });
                                await previewCSV(resultCsvPath, 1);
                            }
                            return;
                        }
                        // 先刷新列表，随后只预览一次检索结果。
                        if (resultCsvPath) {
                            document.getElementById('input-csv').value = resultCsvPath;
                        }
                        // 刷新文件列表
                        await refreshFileList({
                            activatePreview: false,
                            preferredCsv: resultCsvPath,
                            previewCsv: !resultCsvPath,
                        });
                        if (resultCsvPath) {
                            document.getElementById('input-csv').value = resultCsvPath;
                            document.getElementById('search-file-list').value = resultCsvPath;
                            document.getElementById('preview-csv-select').value = resultCsvPath;
                            document.getElementById('graph-csv-select').value = resultCsvPath;
                            await previewCSV(resultCsvPath, 1);
                        }
                        if (task.result && task.result.report_files && task.result.report_files.length > 0) {
                            const reportPath = task.result.report_files[0];
                            const reportFileList = document.getElementById('report-file-list');
                            if (![...reportFileList.options].some(option => option.value === reportPath)) {
                                const option = document.createElement('option');
                                option.value = reportPath;
                                option.textContent = reportPath;
                                reportFileList.prepend(option);
                            }
                            reportFileList.value = reportPath;
                            showReportReadyState(reportPath);
                            showPreviewTab('report');
                        }
                    } else {
                        addLog(`任务 ${taskId} 失败: ${task.error}`, 'error', taskLogOptions);
                        if (progressType === 'graph') {
                            document.getElementById('graph-content').innerHTML = `<p>知识图谱生成失败：${escapeHtml(task.error || '未知错误')}</p>`;
                            showPreviewTab('graph');
                        }
                    }
                }
            } else {
                if (progressContainer) {
                    progressContainer.style.display = 'none';
                }
                if (progressType === 'graph') {
                    showLoading(false, 'generate-graph-btn');
                } else if (progressType === 'report') {
                    showLoading(false, 'generate-btn');
                }
                addLog(`获取任务状态失败: ${task.error}`, 'error', taskLogOptions);
                clearInterval(tasks[taskId]);
                delete tasks[taskId];
                delete taskLogOffsets[taskId];
            }
        } catch (error) {
            if (progressContainer) {
                progressContainer.style.display = 'none';
            }
            if (progressType === 'graph') {
                showLoading(false, 'generate-graph-btn');
            } else if (progressType === 'report') {
                showLoading(false, 'generate-btn');
            }
            addLog(`轮询任务状态失败: ${error.message}`, 'error', taskLogOptions);
            clearInterval(tasks[taskId]);
            delete tasks[taskId];
            delete taskLogOffsets[taskId];
        } finally {
            polling = false;
        }
    }, 1000); // 每秒轮询一次
}

// 更新状态指示器
function updateStatusIndicator(status) {
    const statusIndicator = document.getElementById('status-indicator');
    if (!statusIndicator) return;

    statusIndicator.classList.toggle('is-running', status === 'running');
    statusIndicator.classList.toggle('is-complete', status === 'completed');
    statusIndicator.classList.toggle('is-failed', status === 'failed');
    
    switch (status) {
        case 'running':
            break;
        case 'completed':
            break;
        case 'failed':
            break;
        default:
            break;
    }
}

// 转义HTML特殊字符
function escapeHtml(text) {
    const value = String(text ?? '');
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    
    return value.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function escapeAttribute(text) {
    return escapeHtml(text).replace(/`/g, '&#096;');
}

function escapeRegExp(text) {
    return String(text ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getLibraryHighlightTerms(query) {
    return Array.from(new Set(
        String(query || '')
            .split(/\s+/)
            .map(item => item.trim())
            .filter(Boolean)
            .sort((a, b) => b.length - a.length)
    ));
}

function hasAsciiLetter(text) {
    return /[A-Za-z]/.test(String(text ?? ''));
}

function isAsciiLetter(text) {
    return /^[A-Za-z]$/.test(String(text ?? ''));
}

function isLibraryTermBoundaryMatch(value, index, matchedText) {
    if (!hasAsciiLetter(matchedText)) return true;
    const before = index > 0 ? value[index - 1] : '';
    const after = index + matchedText.length < value.length ? value[index + matchedText.length] : '';
    return !isAsciiLetter(before) && !isAsciiLetter(after);
}

function highlightLibraryText(text, query) {
    const value = String(text ?? '');
    const terms = getLibraryHighlightTerms(query);
    if (!value || terms.length === 0) {
        return escapeHtml(value);
    }

    const pattern = terms.map(escapeRegExp).join('|');
    if (!pattern) {
        return escapeHtml(value);
    }

    const matcher = new RegExp(`(${pattern})`, 'gi');
    let lastIndex = 0;
    let result = '';
    let match;

    while ((match = matcher.exec(value)) !== null) {
        const index = match.index;
        const matchedText = match[0];
        if (!isLibraryTermBoundaryMatch(value, index, matchedText)) {
            continue;
        }
        result += escapeHtml(value.slice(lastIndex, index));
        result += `<mark class="library-highlight">${escapeHtml(matchedText)}</mark>`;
        lastIndex = index + matchedText.length;
    }

    result += escapeHtml(value.slice(lastIndex));
    return result;
}

const CHEMICAL_ELEMENT_SYMBOLS = new Set([
    'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si',
    'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni',
    'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb',
    'Mo', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs',
    'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm',
    'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Pb', 'Bi'
]);

function formatTrendTerm(term) {
    const parts = getTrendFormulaParts(term);
    if (!parts) return escapeHtml(term);
    return parts.map(part => (
        part.subscript
            ? `<sub>${escapeHtml(part.text)}</sub>`
            : escapeHtml(part.text)
    )).join('');
}

function formatTrendTermPlain(term) {
    const parts = getTrendFormulaParts(term);
    if (!parts) return String(term ?? '');
    const subscriptDigits = {
        '0': '₀',
        '1': '₁',
        '2': '₂',
        '3': '₃',
        '4': '₄',
        '5': '₅',
        '6': '₆',
        '7': '₇',
        '8': '₈',
        '9': '₉',
        '.': '.',
    };
    return parts.map(part => (
        part.subscript
            ? part.text.replace(/[0-9.]/g, char => subscriptDigits[char] || char)
            : part.text
    )).join('');
}

function formatSvgTrendTerm(term) {
    const parts = getTrendFormulaParts(term);
    if (!parts) return escapeHtml(term);
    return parts.map(part => (
        part.subscript
            ? `<tspan class="formula-subscript" baseline-shift="sub">${escapeHtml(part.text)}</tspan>`
            : escapeHtml(part.text)
    )).join('');
}

function getTrendFormulaParts(term) {
    const value = String(term ?? '').trim();
    if (!value) return null;

    const alphaParts = value.match(/[A-Za-z]+/g) || [];
    if (!/\d/.test(value) || /[^A-Za-z0-9+\-().]/.test(value) || alphaParts.length === 0) {
        return null;
    }

    const normalizedParts = alphaParts.map(normalizeFormulaLetters);
    if (normalizedParts.some(part => !part)) {
        return null;
    }

    const normalized = value.replace(/[A-Za-z]+/g, token => normalizeFormulaLetters(token));
    const parts = [];
    let cursor = 0;
    const digitRe = /([A-Za-z)])(\d+(?:\.\d+)?)/g;
    let match;
    while ((match = digitRe.exec(normalized)) !== null) {
        const prefixEnd = match.index + match[1].length;
        if (prefixEnd > cursor) {
            parts.push({ text: normalized.slice(cursor, prefixEnd), subscript: false });
        }
        parts.push({ text: match[2], subscript: true });
        cursor = prefixEnd + match[2].length;
    }
    if (cursor < normalized.length) {
        parts.push({ text: normalized.slice(cursor), subscript: false });
    }
    return parts.length ? parts : null;
}

function normalizeFormulaLetters(token) {
    let normalized = '';
    let index = 0;
    while (index < token.length) {
        const two = toElementCase(token.slice(index, index + 2));
        if (two.length === 2 && CHEMICAL_ELEMENT_SYMBOLS.has(two)) {
            normalized += two;
            index += 2;
            continue;
        }

        const one = toElementCase(token.slice(index, index + 1));
        if (CHEMICAL_ELEMENT_SYMBOLS.has(one)) {
            normalized += one;
            index += 1;
            continue;
        }

        return '';
    }
    return normalized;
}

function toElementCase(value) {
    return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

function doiToUrl(doi) {
    const value = String(doi || '').trim();
    if (!value) return '';
    if (/^https?:\/\//i.test(value)) return value;
    return `https://doi.org/${value}`;
}

function getCheckedValues(selector) {
    return Array.from(document.querySelectorAll(selector))
        .filter(input => input.checked)
        .map(input => input.value)
        .filter(Boolean);
}

function setCheckboxes(selector, checked) {
    document.querySelectorAll(selector).forEach(input => {
        input.checked = checked;
    });
}

async function importCsvRows(rowIndices = null) {
    if (!currentCsvPath) {
        addLog('请先选择 CSV 文件。', 'error');
        return;
    }
    const payload = { path: currentCsvPath };
    if (Array.isArray(rowIndices)) {
        payload.row_indices = rowIndices.map(value => Number(value)).filter(value => Number.isInteger(value) && value >= 0);
        if (payload.row_indices.length === 0) {
            addLog('请先选择要入库的文献。', 'error');
            return;
        }
    }
    try {
        const response = await fetch('/api/library/import_csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'CSV 入库失败');
        }
        addLog(`CSV 入库完成：处理 ${result.imported || 0} 篇，新增 ${result.inserted || 0} 篇，更新 ${result.updated || 0} 篇。`);
        selectedCsvRows.clear();
        await loadLibraryPapers(currentLibraryPage || 1);
    } catch (error) {
        addLog(`CSV 入库失败：${error.message}`, 'error');
    }
}

function importSelectedCsvRows() {
    const rows = getCheckedValues('.csv-paper-checkbox');
    importCsvRows(rows);
}

function importAllCsvRows() {
    importCsvRows(null);
}

function importSingleCsvRow(rowIndex) {
    importCsvRows([rowIndex]);
}

function toggleAllCsvRows(checkbox) {
    setCheckboxes('.csv-paper-checkbox', Boolean(checkbox?.checked));
}

function getCollectionTypeLabel(type) {
    const labels = {
        material: '材料',
        method: '方法',
        project: '项目',
        custom: '其它'
    };
    return labels[type] || labels.custom;
}

function getCollectionTypeClass(type) {
    const normalized = ['material', 'method', 'project', 'custom'].includes(type) ? type : 'custom';
    return `collection-type-badge collection-type-${normalized}`;
}

async function loadLibraryCollections(renderDetail = false) {
    const list = document.getElementById('collections-list');
    if (list) {
        list.innerHTML = '<p>正在读取文献主题库...</p>';
    }
    try {
        const response = await fetch('/api/library/collections');
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '文献主题库读取失败');
        }
        currentCollections = result.data || [];
        if (!currentCollectionId && currentCollections.length > 0) {
            currentCollectionId = currentCollections[0].collection_id;
        }
        renderCollectionsList();
        renderGraphCollectionOptions();
        renderReportCollectionOptions();
        updateGraphScopeControls();
        scheduleReportSourceSummary();
        if (renderDetail) {
            if (currentCollectionId) {
                await loadCollectionDetail(currentCollectionId);
            } else {
                renderCollectionEmptyState();
            }
        }
    } catch (error) {
        if (list) {
            list.innerHTML = `<p>读取文献主题库失败：${escapeHtml(error.message)}</p>`;
        }
        renderCollectionEmptyState(error.message);
    }
}

function renderReportCollectionOptions() {
    const select = document.getElementById('report-collection-select');
    if (!select) return;
    const preferred = select.value || reportSettingsState.report_collection_id || currentCollectionId;
    if (!currentCollections.length) {
        select.innerHTML = '<option value="">暂无文献主题库</option>';
        return;
    }
    select.innerHTML = currentCollections.map(collection => `
        <option value="${escapeAttribute(collection.collection_id)}">
            ${escapeHtml(collection.name)} (${escapeHtml(collection.paper_count || 0)}篇)
        </option>
    `).join('');
    const nextValue = currentCollections.some(item => item.collection_id === preferred)
        ? preferred
        : currentCollections[0].collection_id;
    select.value = nextValue;
    reportSettingsState.report_collection_id = nextValue;
}

function renderCollectionsList() {
    const list = document.getElementById('collections-list');
    const info = document.getElementById('collections-info');
    if (info) {
        info.textContent = `文献主题库 ${currentCollections.length} 个 · 支持手动加入与关键词规则归类`;
    }
    if (!list) return;
    if (currentCollections.length === 0) {
        list.innerHTML = '<p>暂无文献主题库。</p>';
        return;
    }
    list.innerHTML = currentCollections.map(collection => `
        <button type="button"
                class="collection-list-item${collection.collection_id === currentCollectionId ? ' active' : ''}"
                data-collection-id="${escapeAttribute(collection.collection_id)}"
                onclick="selectLibraryCollection(this.dataset.collectionId)">
            <span class="${getCollectionTypeClass(collection.collection_type)}">${escapeHtml(getCollectionTypeLabel(collection.collection_type))}</span>
            <strong>${escapeHtml(collection.name)}</strong>
            <small>${escapeHtml(collection.paper_count || 0)} 篇</small>
        </button>
    `).join('');
}

function renderCollectionEmptyState(message = '') {
    const detail = document.getElementById('collections-detail');
    if (!detail) return;
    detail.innerHTML = `<p>${escapeHtml(message || '选择或创建一个文献主题库。')}</p>`;
}

async function selectLibraryCollection(collectionId) {
    currentCollectionId = collectionId || '';
    const graphCollectionSelect = document.getElementById('graph-collection-select');
    if (graphCollectionSelect && currentCollectionId) {
        graphCollectionSelect.value = currentCollectionId;
    }
    updateGraphScopeControls();
    renderCollectionsList();
    if (currentCollectionId) {
        await loadCollectionDetail(currentCollectionId);
    }
}

async function createLibraryCollection() {
    const nameInput = document.getElementById('collection-name');
    const typeInput = document.getElementById('collection-type');
    const includeInput = document.getElementById('collection-include-keywords');
    const excludeInput = document.getElementById('collection-exclude-keywords');
    const name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
        addLog('文献主题库名称不能为空。', 'error');
        nameInput?.focus();
        return;
    }
    const payload = {
        name,
        collection_type: typeInput ? typeInput.value : 'custom',
        rules: {
            include_keywords: includeInput ? includeInput.value : '',
            exclude_keywords: excludeInput ? excludeInput.value : ''
        }
    };
    try {
        const response = await fetch('/api/library/collections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '文献主题库创建失败');
        }
        currentCollectionId = result.collection_id;
        if (nameInput) nameInput.value = '';
        if (includeInput) includeInput.value = '';
        if (excludeInput) excludeInput.value = '';
        addLog(`文献主题库已创建：${name}`);
        await loadLibraryCollections(true);
        await loadLibraryPapers(currentLibraryPage || 1);
    } catch (error) {
        addLog(`文献主题库创建失败：${error.message}`, 'error');
    }
}

async function loadCollectionDetail(collectionId) {
    const detail = document.getElementById('collections-detail');
    if (detail) {
        detail.innerHTML = '<p>正在读取文献主题库文献...</p>';
    }
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(collectionId)}/papers`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '文献主题库文献读取失败');
        }
        renderCollectionDetail(result.collection, result.data || []);
    } catch (error) {
        renderCollectionEmptyState(error.message);
    }
}

function renderCollectionDetail(collection, papers) {
    const detail = document.getElementById('collections-detail');
    if (!detail || !collection) return;
    const rules = collection.rules || {};
    const includeKeywords = (rules.include_keywords || []).join(', ') || '-';
    const excludeKeywords = (rules.exclude_keywords || []).join(', ') || '-';
    detail.innerHTML = `
        <div class="collection-detail-header">
            <div>
                <span class="${getCollectionTypeClass(collection.collection_type)}">${escapeHtml(getCollectionTypeLabel(collection.collection_type))}</span>
                <strong>${escapeHtml(collection.name)}</strong>
                <small>包含：${escapeHtml(includeKeywords)} · 排除：${escapeHtml(excludeKeywords)}</small>
            </div>
            <div class="collection-header-actions">
                <button type="button" class="btn btn-secondary" onclick="classifyLibraryCollection('${escapeAttribute(collection.collection_id)}')">
                    <i class="fas fa-filter"></i> 自动归类
                </button>
                <button type="button" class="btn btn-secondary danger-action" onclick="deleteLibraryCollection('${escapeAttribute(collection.collection_id)}')">
                    <i class="fas fa-trash"></i> 删除文献主题库
                </button>
            </div>
        </div>
        <div class="bulk-action-bar">
            <label class="bulk-select-control">
                <input type="checkbox" name="select_all_collection_papers" aria-label="选择全部主题库文献" onchange="toggleAllCollectionPapers(this)">
                <span>选择本页</span>
            </label>
            <button type="button" class="btn btn-secondary" onclick="batchParsePaperMds('.collection-paper-checkbox')">批量解析 MD</button>
            <button type="button" class="btn btn-secondary danger-action" onclick="batchDeletePaperPdfs('.collection-paper-checkbox')">批量删除 PDF</button>
            <button type="button" class="btn btn-secondary danger-action" onclick="batchDeletePaperMds('.collection-paper-checkbox')">批量删除解析 MD</button>
            <button type="button" class="btn btn-secondary" onclick="removeSelectedCollectionPapers()">批量移除</button>
        </div>
        ${papers.length ? `
            <div class="literature-table collection-literature-table">
                <div class="literature-table-head">
                    <div>选择 / 编号</div>
                    <div>标题</div>
                    <div>期刊</div>
                    <div>引用</div>
                    <div>发表时间</div>
                </div>
                <div class="collection-paper-list">
                    ${papers.map((paper, index) => renderCollectionPaperItem(paper, index)).join('')}
                </div>
            </div>
        ` : '<p>暂无文献。可从文献数据库手动加入，或配置关键词后自动归类。</p>'}
    `;
}

function renderCollectionPaperItem(paper, itemIndex = 0) {
    const url = paper.doi ? doiToUrl(paper.doi) : (paper.url || '');
    const title = paper.title || '未命名文献';
    const titleHtml = url
        ? `<a href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>`
        : escapeHtml(title);
    const identityKey = paper.identity_key || '';
    const journal = paper.venue || '期刊信息缺失';
    const citationCount = paper.citationCount !== '' && paper.citationCount !== null ? paper.citationCount : '-';
    const publicationDate = paper.publicationDate || paper.year || '时间缺失';
    const authors = paper.authors || '作者信息缺失';
    const abstractText = String(paper.abstract || '暂无摘要').replace(/^abstract\s*[:：.]?\s*/i, '');
    const doi = paper.doi ? `<span>DOI：${escapeHtml(paper.doi)}</span>` : '';
    const itemNumber = itemIndex + 1;
    const pdfStatus = paper.download_status || 'not_downloaded';
    const pdfSource = paper.pdf_source || '';
    const pdfStatusClass = getPdfStatusClass(pdfStatus);
    const pdfStatusTitle = paper.download_error ? ` title="${escapeAttribute(paper.download_error)}"` : '';
    const parseStatus = paper.parse_status || 'not_parsed';
    const parseStatusClass = getParseStatusClass(parseStatus);
    const parseStatusTitle = paper.parse_error ? ` title="${escapeAttribute(paper.parse_error)}"` : '';
    const chunkCount = Number(paper.chunk_count || 0);
    const pageCount = Number(paper.page_count || 0);
    const parseEngine = getParseEngineLabel(paper.parse_engine);
    const parseQualityHtml = buildParseQualityHtml(paper);
    const viewPdf = pdfStatus === 'downloaded'
        ? `<a class="pdf-action-link" href="${escapeAttribute(buildPaperPdfUrl(identityKey))}" target="_blank" rel="noopener noreferrer">查看 PDF</a>`
        : '';
    const parseFullText = pdfStatus === 'downloaded'
        ? `<button type="button" class="pdf-action-button" data-identity-key="${escapeAttribute(identityKey)}" onclick="parseLibraryPdf(this.dataset.identityKey, this, ${parseStatus === 'parsed' ? 'true' : 'false'})">${parseStatus === 'parsed' ? '重新解析 MD' : '解析 MD'}</button>`
        : '';
    const uploadPdf = identityKey
        ? `<button type="button" class="pdf-action-button" data-identity-key="${escapeAttribute(identityKey)}" onclick="triggerLibraryPdfUpload(this.dataset.identityKey)">上传 PDF</button>`
        : '';
    const viewFullText = parseStatus === 'parsed'
        ? `<a class="pdf-action-link" href="${escapeAttribute(buildPaperFullTextViewUrl(identityKey))}" target="_blank" rel="noopener noreferrer">查看 MD</a>`
        : '';
    const deleteFullText = parseStatus === 'parsed' || parseStatus === 'failed'
        ? `<button type="button" class="pdf-action-button danger-action" data-identity-key="${escapeAttribute(identityKey)}" onclick="deletePaperMd(this.dataset.identityKey, this)">删除解析 MD</button>`
        : '';
    return `
        <div class="literature-item collection-paper-item">
            <div class="literature-row-top">
                <div class="literature-number">
                    <input type="checkbox" name="collection_paper_ids" class="collection-paper-checkbox" value="${escapeAttribute(identityKey)}" aria-label="选择文献主题库文献">
                    <span class="literature-index">${escapeHtml(itemNumber)}</span>
                </div>
                <div class="literature-title">${titleHtml}</div>
                <div class="literature-journal">${escapeHtml(journal)}</div>
                <div class="literature-citations">${escapeHtml(citationCount)}</div>
                <div class="literature-date">${escapeHtml(publicationDate)}</div>
            </div>
            <div class="literature-authors">${escapeHtml(authors)}</div>
            <div class="literature-abstract collapsed">
                <span class="abstract-label">Abstract</span> ${escapeHtml(abstractText)}
            </div>
            <button type="button" class="toggle-abstract" onclick="toggleAbstract(this)">展开摘要</button>
            <div class="literature-actions collection-paper-actions">
                ${doi}
                <span class="pdf-status pdf-status-${pdfStatusClass}"${pdfStatusTitle}>${getPdfStatusLabel(pdfStatus, pdfSource)}</span>
                <span class="pdf-status pdf-status-${parseStatusClass}"${parseStatusTitle}>${getParseStatusLabel(parseStatus)}</span>
                ${pageCount ? `<span>页数：${escapeHtml(pageCount)}</span>` : ''}
                ${chunkCount ? `<span>片段：${escapeHtml(chunkCount)}</span>` : ''}
                ${parseEngine ? `<span>引擎：${escapeHtml(parseEngine)}</span>` : ''}
                ${parseQualityHtml}
                ${uploadPdf}
                ${viewPdf}
                ${parseFullText}
                ${viewFullText}
                ${deleteFullText}
                <button type="button" class="pdf-action-button danger-action" data-identity-key="${escapeAttribute(identityKey)}" onclick="removeSingleCollectionPaper(this.dataset.identityKey)">移除</button>
            </div>
        </div>
    `;
}

async function classifyLibraryCollection(collectionId) {
    if (!collectionId) return;
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(collectionId)}/classify`, {
            method: 'POST'
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '自动归类失败');
        }
        addLog(`自动归类完成：匹配 ${result.matched || 0} 篇，新增 ${result.added || 0} 篇。`);
        await loadLibraryCollections(false);
        await loadCollectionDetail(collectionId);
    } catch (error) {
        addLog(`自动归类失败：${error.message}`, 'error');
    }
}

function toggleAllCollectionPapers(checkbox) {
    setCheckboxes('.collection-paper-checkbox', Boolean(checkbox?.checked));
}

async function deleteLibraryCollection(collectionId) {
    if (!collectionId) return;
    const collection = currentCollections.find(item => item.collection_id === collectionId);
    const name = collection ? collection.name : collectionId;
    const confirmed = await requestDangerConfirm({
        title: '删除文献主题库？',
        message: '将删除该主题库的配置与关联列表，文献数据库中的原始文献不会被删除。',
        target: `文献主题库：${name}`,
        confirmText: '确认删除',
        meta: [
            { icon: 'fas fa-database', text: '保留文献数据库' },
            { icon: 'fas fa-trash', text: '删除主题库', danger: true }
        ]
    });
    if (!confirmed) {
        return;
    }
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(collectionId)}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '删除文献主题库失败');
        }
        addLog(`文献主题库已删除：${name}`);
        currentCollectionId = '';
        await loadLibraryCollections(true);
        await loadLibraryPapers(currentLibraryPage || 1);
    } catch (error) {
        addLog(`删除文献主题库失败：${error.message}`, 'error');
    }
}

async function removeCollectionPapers(identityKeys) {
    const keys = Array.isArray(identityKeys) ? identityKeys.filter(Boolean) : [];
    if (!currentCollectionId || keys.length === 0) {
        addLog('请先选择要移除的文献主题库文献。', 'error');
        return;
    }
    const confirmed = await requestDangerConfirm({
        title: '移除主题库文献？',
        message: `将从当前文献主题库移除 ${keys.length} 篇文献，文献数据库中的记录不会被删除。`,
        target: `${keys.length} 篇已选文献`,
        confirmText: '确认移除',
        meta: [
            { icon: 'fas fa-folder-minus', text: '移出当前主题库', danger: true },
            { icon: 'fas fa-database', text: '保留文献数据库' }
        ]
    });
    if (!confirmed) {
        return;
    }
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(currentCollectionId)}/papers/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity_keys: keys })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '移除文献失败');
        }
        addLog(`文献主题库文献移除完成：${result.removed || 0} 篇。`);
        await loadLibraryCollections(false);
        await loadCollectionDetail(currentCollectionId);
    } catch (error) {
        addLog(`移除文献失败：${error.message}`, 'error');
    }
}

function removeSelectedCollectionPapers() {
    removeCollectionPapers(getCheckedValues('.collection-paper-checkbox'));
}

function removeSingleCollectionPaper(identityKey) {
    removeCollectionPapers([identityKey]);
}

function renderCollectionPicker(identityKey) {
    if (!identityKey || currentCollections.length === 0) return '';
    const options = currentCollections.map(collection => (
        `<button type="button"
                 class="collection-choice-option"
                 data-identity-key="${escapeAttribute(identityKey)}"
                 data-collection-id="${escapeAttribute(collection.collection_id)}"
                 onclick="addLibraryPaperToSelectedCollection(this)">
            ${escapeHtml(collection.name)}
        </button>`
    )).join('');
    return `
        <span class="collection-action-group collection-chooser">
            <button type="button"
                    class="pdf-action-button collection-chooser-trigger"
                    data-identity-key="${escapeAttribute(identityKey)}"
                    aria-expanded="false"
                    onclick="toggleCollectionChooser(this, event)">
                加入文献主题库
            </button>
            <span class="collection-choice-menu" role="menu" hidden>
                ${options}
            </span>
        </span>
    `;
}

function closeCollectionChoosers(exceptChooser = null) {
    document.querySelectorAll('.collection-chooser').forEach(chooser => {
        if (exceptChooser && chooser === exceptChooser) return;
        const menu = chooser.querySelector('.collection-choice-menu');
        const trigger = chooser.querySelector('.collection-chooser-trigger');
        if (menu) {
            menu.hidden = true;
        }
        if (trigger) {
            trigger.setAttribute('aria-expanded', 'false');
        }
    });
}

function toggleCollectionChooser(button, event = null) {
    if (event) {
        event.stopPropagation();
    }
    const chooser = button?.closest('.collection-chooser');
    const menu = chooser?.querySelector('.collection-choice-menu');
    if (!chooser || !menu) return;
    const nextOpen = menu.hidden;
    closeCollectionChoosers(chooser);
    menu.hidden = !nextOpen;
    button.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
}

async function addLibraryPaperToSelectedCollection(button) {
    const identityKey = button?.dataset?.identityKey || '';
    const picker = button?.parentElement?.querySelector('.collection-picker');
    const collectionId = button?.dataset?.collectionId || (picker ? picker.value : '');
    if (!identityKey || !collectionId) return;
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(collectionId)}/papers`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity_key: identityKey, match_source: 'manual' })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '加入文献主题库失败');
        }
        closeCollectionChoosers();
        const collection = currentCollections.find(item => item.collection_id === collectionId);
        addLog(`已加入文献主题库：${collection ? collection.name : collectionId}`);
        if (currentCollectionId === collectionId) {
            await loadCollectionDetail(collectionId);
        }
        await loadLibraryCollections(false);
    } catch (error) {
        addLog(`加入文献主题库失败：${error.message}`, 'error');
    }
}

function handleLibrarySearch() {
    const input = document.getElementById('library-search-input');
    currentLibraryQuery = input ? input.value.trim() : '';
    updateWorkspaceUrl({ preview: 'library', library_q: currentLibraryQuery, library_page: '1' }, false);
    loadLibraryPapers(1, false);
}

function getSelectedLibraryPaperIds() {
    return getCheckedValues('.library-paper-checkbox');
}

async function refreshLibraryQaSessions(selectedSessionId = '') {
    const listNode = document.getElementById('library-qa-session-list');
    if (!listNode) return;
    const params = new URLSearchParams();
    if (currentQaPaper?.identity_key) {
        params.set('identity_key', currentQaPaper.identity_key);
    }
    try {
        const response = await fetch(`/api/library/qa/sessions${params.toString() ? `?${params.toString()}` : ''}`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '读取问答会话失败');
        const sessions = result.data || [];
        if (!sessions.length) {
            listNode.innerHTML = '<p>暂无问答会话。</p>';
            currentQaSessionId = '';
            return;
        }
        currentQaSessionId = selectedSessionId || currentQaSessionId;
        listNode.innerHTML = sessions.map(session => {
            const active = (selectedSessionId && session.session_id === selectedSessionId) || (!selectedSessionId && session.session_id === currentQaSessionId);
            return `
                <button type="button" class="library-qa-session-item${active ? ' active' : ''}" onclick="loadLibraryQaSession('${escapeAttribute(session.session_id)}')">
                    <strong>${escapeHtml(session.title || '问答会话')}</strong>
                    <span>${escapeHtml(formatLibraryTimestamp(session.updated_at || session.created_at || ''))}</span>
                </button>
            `;
        }).join('');
    } catch (error) {
        listNode.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function renderLibraryQaEvidence(citations = []) {
    const node = document.getElementById('library-qa-evidence-body');
    if (!node) return;
    if (!Array.isArray(citations) || !citations.length) {
        node.innerHTML = '<p>回答中的引用会在这里展开。</p>';
        return;
    }
    node.innerHTML = citations.map(citation => {
        const pageLabel = citation.page_start
            ? (citation.page_end && citation.page_end !== citation.page_start ? `p.${citation.page_start}-${citation.page_end}` : `p.${citation.page_start}`)
            : '页码未知';
        return `
            <article class="library-qa-evidence-card" data-citation-order="${escapeAttribute(citation.citation_order)}">
                <strong>[${escapeHtml(citation.citation_order)}] ${escapeHtml(citation.section_title || '未标注章节')} / ${escapeHtml(pageLabel)}</strong>
                <p>${escapeHtml(citation.quoted_text || '')}</p>
                <div class="library-qa-evidence-actions">
                    <a class="pdf-action-link" href="${escapeAttribute(buildPaperFullTextViewUrl(citation.identity_key))}" target="_blank" rel="noopener noreferrer">打开 MD</a>
                    <a class="pdf-action-link" href="${escapeAttribute(buildPaperPdfUrl(citation.identity_key))}" target="_blank" rel="noopener noreferrer">打开 PDF</a>
                </div>
            </article>
        `;
    }).join('');
}

function renderQaMessageContent(message = '', citations = []) {
    const citationMap = new Map((citations || []).map(item => [Number(item.citation_order), item]));
    const text = String(message || '');
    const parts = [];
    let lastIndex = 0;
    const pattern = /\[(\d+)\]/g;
    let match;
    while ((match = pattern.exec(text)) !== null) {
        const start = match.index;
        const end = pattern.lastIndex;
        if (start > lastIndex) {
            parts.push(escapeHtml(text.slice(lastIndex, start)));
        }
        const order = Number(match[1]);
        if (citationMap.has(order)) {
            parts.push(`<button type="button" class="library-qa-inline-citation" data-citation-order="${escapeAttribute(order)}" onclick="focusQaCitation(${escapeAttribute(order)})">[${escapeHtml(order)}]</button>`);
        } else {
            parts.push(escapeHtml(match[0]));
        }
        lastIndex = end;
    }
    if (lastIndex < text.length) {
        parts.push(escapeHtml(text.slice(lastIndex)));
    }
    return parts.join('');
}

function focusQaCitation(citationOrder) {
    const order = Number(citationOrder || 0);
    if (!order) return;
    const target = document.querySelector(`.library-qa-evidence-card[data-citation-order="${CSS.escape(String(order))}"]`);
    document.querySelectorAll('.library-qa-evidence-card').forEach(node => node.classList.remove('is-highlighted'));
    if (target) {
        target.classList.add('is-highlighted');
        target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function renderLibraryQaAnswerFromSession(session) {
    const answerNode = document.getElementById('library-qa-answer-body');
    if (!answerNode) return;
    const messages = Array.isArray(session?.messages) ? session.messages : [];
    if (!messages.length) {
        answerNode.innerHTML = '<p>选择一篇已解析文献后，在这里提问。</p>';
        renderLibraryQaEvidence([]);
        return;
    }
    const html = messages.map(message => {
        const citations = Array.isArray(message.citations) ? message.citations : [];
        const citedOrders = citations.map(item => `[${item.citation_order}]`).join(' ');
        const contentHtml = message.role === 'assistant'
            ? renderQaMessageContent(message.content || '', citations)
            : escapeHtml(message.content || '');
        return `
            <div class="library-qa-message library-qa-message-${escapeAttribute(message.role)}">
                <span class="library-qa-message-role">${escapeHtml(message.role === 'user' ? 'Q' : 'A')}</span>
                <div class="library-qa-message-content">
                    <p>${contentHtml}</p>
                    ${citedOrders ? `<div class="library-qa-message-citations">${escapeHtml(citedOrders)}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
    answerNode.innerHTML = html;
    const assistantMessage = [...messages].reverse().find(item => item.role === 'assistant');
    renderLibraryQaEvidence(assistantMessage?.citations || []);
}

async function loadLibraryQaSession(sessionId) {
    if (!sessionId) return;
    try {
        const response = await fetch(`/api/library/qa/sessions/${encodeURIComponent(sessionId)}`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '读取问答会话失败');
        currentQaSessionId = sessionId;
        renderLibraryQaAnswerFromSession(result);
        await refreshLibraryQaSessions(sessionId);
    } catch (error) {
        const answerNode = document.getElementById('library-qa-answer-body');
        if (answerNode) {
            answerNode.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
        }
    }
}

function updateLibraryQaContext(papers = []) {
    const contextNode = document.getElementById('library-qa-context');
    const modelMetaNode = document.getElementById('library-qa-model-meta');
    const askButton = document.getElementById('library-qa-ask-btn');
    const selectedKeys = getCheckedValues('.library-paper-checkbox');
    const selectedPapers = (papers || []).filter(item => selectedKeys.includes(item.identity_key));
    currentQaPaper = selectedPapers.length === 1 ? selectedPapers[0] : null;
    const modelName = (document.getElementById('model')?.value || '').trim();
    const provider = (document.getElementById('llm-provider')?.value || 'ollama').trim();
    if (modelMetaNode) {
        modelMetaNode.textContent = modelName ? `${provider} / ${modelName}` : provider;
    }
    if (!contextNode || !askButton) return;
    if (selectedPapers.length === 0) {
        contextNode.textContent = '请先在下方文献数据库中勾选 1 篇已解析文献。';
        askButton.disabled = true;
        return;
    }
    if (selectedPapers.length > 1) {
        contextNode.textContent = '当前版本仅支持单篇问答，请只勾选 1 篇文献。';
        askButton.disabled = true;
        return;
    }
    const paper = selectedPapers[0];
    if (paper.parse_status !== 'parsed') {
        contextNode.textContent = `${paper.title || paper.identity_key} 尚未解析全文，请先解析 MD。`;
        askButton.disabled = true;
        return;
    }
    contextNode.textContent = `当前文献：${paper.title || paper.identity_key} · 状态：已解析 · 片段：${paper.chunk_count || 0} · 页码覆盖：${formatCoveragePercent(paper.page_mapping_coverage || 0)} · 质量：${getParseQualityLabel(paper.parse_quality || '')}`;
    askButton.disabled = false;
}

async function ensureLibraryQaSession(identityKey, title = '') {
    const response = await fetch('/api/library/qa/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scope_type: 'current_paper',
            identity_key: identityKey,
            title: title || ''
        })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '创建问答会话失败');
    return result;
}

async function handleLibraryQaAsk() {
    const questionInput = document.getElementById('library-qa-question');
    const answerNode = document.getElementById('library-qa-answer-body');
    const question = questionInput ? questionInput.value.trim() : '';
    if (!question) {
        addLog('请输入问题。', 'warning');
        return;
    }
    if (!currentQaPaper || currentQaPaper.parse_status !== 'parsed') {
        addLog('请先选择 1 篇已解析文献。', 'warning');
        return;
    }
    const provider = document.getElementById('llm-provider')?.value || 'ollama';
    const baseUrl = document.getElementById('ollama-base-url')?.value || '';
    const apiKey = document.getElementById('llm-api-key')?.value || '';
    const model = document.getElementById('model')?.value || '';
    if (!String(baseUrl).trim() || !String(model).trim()) {
        addLog('请先在报告配置中填写模型服务地址和模型名称。', 'warning');
        return;
    }
    if (provider === 'openai_compatible' && !String(apiKey).trim()) {
        addLog('当前选择了远程大模型接口，请先填写访问密钥。', 'warning');
        return;
    }
    try {
        if (answerNode) {
            answerNode.innerHTML = '<p>正在生成问答，请稍候...</p>';
        }
        let sessionId = currentQaSessionId;
        if (!sessionId) {
            const session = await ensureLibraryQaSession(currentQaPaper.identity_key, `问答：${(currentQaPaper.title || currentQaPaper.identity_key).slice(0, 40)}`);
            sessionId = session.session_id;
            currentQaSessionId = sessionId;
        }
        const response = await fetch(`/api/library/qa/sessions/${encodeURIComponent(sessionId)}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                llm_provider: provider,
                ollama_base_url: baseUrl,
                llm_base_url: baseUrl,
                llm_api_key: apiKey,
                model,
                temperature: 0,
                top_p: 0.9,
                num_predict: 1800,
                top_k: 8,
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '问答生成失败');
        if (questionInput) questionInput.value = '';
        renderLibraryQaAnswerFromSession(result.session);
        await refreshLibraryQaSessions(sessionId);
        addLog('单篇文献问答完成。', 'info');
    } catch (error) {
        if (answerNode) {
            answerNode.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
        }
        addLog(`单篇文献问答失败：${error.message}`, 'error');
    }
}

function renderLibraryFulltextResults(result = null, errorMessage = '') {
    const panel = document.getElementById('library-fulltext-results');
    if (!panel) return;
    if (errorMessage) {
        panel.hidden = false;
        panel.innerHTML = `<div class="library-fulltext-panel is-error"><p>${escapeHtml(errorMessage)}</p></div>`;
        return;
    }
    if (!result || !Array.isArray(result.results) || result.results.length === 0) {
        if (result && result.query) {
            panel.hidden = false;
            panel.innerHTML = `
                <div class="library-fulltext-panel">
                    <div class="library-fulltext-header">
                        <strong>全文检索结果</strong>
                        <span>关键词：${escapeHtml(result.query)}</span>
                    </div>
                    <p>没有命中片段。已纳入 ${escapeHtml(result.included_papers || 0)} 篇已解析文献，排除 ${escapeHtml(result.excluded_unparsed || 0)} 篇未解析文献。</p>
                </div>
            `;
        } else {
            panel.hidden = true;
            panel.innerHTML = '';
        }
        return;
    }
    panel.hidden = false;
    const cards = result.results.map(item => {
        const pageLabel = item.page_start
            ? (item.page_end && item.page_end !== item.page_start ? `p.${item.page_start}-${item.page_end}` : `p.${item.page_start}`)
            : '页码未知';
        const meta = [
            item.section_title ? `章节：${escapeHtml(item.section_title)}` : '',
            pageLabel ? `页码：${escapeHtml(pageLabel)}` : '',
            item.chunk_type ? `类型：${escapeHtml(item.chunk_type)}` : ''
        ].filter(Boolean).join(' · ');
        return `
            <article class="library-fulltext-result-card">
                <div class="library-fulltext-result-top">
                    <div>
                        <strong>${escapeHtml(item.title || '未命名文献')}</strong>
                        <span>${escapeHtml(item.authors || '')}</span>
                    </div>
                    <a class="pdf-action-link" href="${escapeAttribute(buildPaperFullTextViewUrl(item.identity_key))}" target="_blank" rel="noopener noreferrer">查看 MD</a>
                </div>
                <div class="library-fulltext-result-meta">${meta}</div>
                <p class="library-fulltext-result-snippet">${escapeHtml(item.snippet || item.chunk_text || '')}</p>
            </article>
        `;
    }).join('');
    panel.innerHTML = `
        <div class="library-fulltext-panel">
            <div class="library-fulltext-header">
                <strong>全文检索结果</strong>
                <span>关键词：${escapeHtml(result.query || '')} · 命中 ${escapeHtml(result.total || 0)} 个片段 · 纳入 ${escapeHtml(result.included_papers || 0)} 篇已解析文献 · 排除 ${escapeHtml(result.excluded_unparsed || 0)} 篇未解析文献</span>
            </div>
            <div class="library-fulltext-result-list">${cards}</div>
        </div>
    `;
}

async function handleLibraryFulltextSearch() {
    const queryInput = document.getElementById('library-fulltext-query');
    const scopeInput = document.getElementById('library-fulltext-scope');
    currentLibraryFulltextQuery = queryInput ? queryInput.value.trim() : '';
    currentLibraryFulltextScope = scopeInput ? (scopeInput.value || 'selected_papers') : 'selected_papers';
    if (!currentLibraryFulltextQuery) {
        renderLibraryFulltextResults(null, '请输入全文检索关键词。');
        return;
    }
    const params = new URLSearchParams({
        q: currentLibraryFulltextQuery,
        scope_type: currentLibraryFulltextScope,
        limit: '12',
    });
    if (currentLibraryFulltextScope === 'selected_papers') {
        const selected = getSelectedLibraryPaperIds();
        if (!selected.length) {
            renderLibraryFulltextResults(null, '请先勾选文献，或将范围切换为“全部全文”。');
            return;
        }
        params.set('identity_keys', selected.join(','));
    }
    renderLibraryFulltextResults({ query: currentLibraryFulltextQuery, results: [] }, '正在检索全文片段...');
    try {
        const response = await fetch(`/api/library/search/fulltext?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '全文检索失败');
        }
        renderLibraryFulltextResults(result);
        addLog(`全文检索完成：${result.total || 0} 个片段。`, 'info');
    } catch (error) {
        renderLibraryFulltextResults(null, `全文检索失败：${error.message}`);
        addLog(`全文检索失败：${error.message}`, 'error');
    }
}

function openLibraryMetadataModal() {
    const modal = document.getElementById('library-metadata-modal');
    const form = document.getElementById('library-metadata-form');
    if (!modal || !form) return;
    form.reset();
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('library-metadata-modal-open');
    window.setTimeout(() => form.elements.title?.focus(), 0);
}

function closeLibraryMetadataModal() {
    const modal = document.getElementById('library-metadata-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('library-metadata-modal-open');
    deactivateManagedModal(modal);
    document.querySelectorAll('body > [inert]').forEach(element => {
        element.inert = false;
    });
}

async function handleLibraryMetadataFilePicked(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const button = document.getElementById('library-import-metadata-btn');
    const originalHtml = button?.innerHTML || '';
    const formData = new FormData();
    formData.append('file', file);
    if (button) {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> 正在导入';
    }
    addLog(`开始导入元数据文件：${file.name}`, 'info');
    try {
        const response = await fetch('/api/library/import_metadata_file', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '元数据文件入库失败');
        }
        addLog(
            `元数据文件入库完成：处理 ${result.imported || 0} 篇，新增 ${result.inserted || 0} 篇，更新 ${result.updated || 0} 篇${result.skipped ? `，跳过 ${result.skipped} 条无题目记录` : ''}。`
        );
        await loadLibraryPapers(1, true);
    } catch (error) {
        addLog(`元数据文件入库失败：${error.message}`, 'error');
    } finally {
        event.target.value = '';
        if (button) {
            button.disabled = false;
            button.innerHTML = originalHtml;
        }
    }
}

async function submitManualLibraryPaper(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const submitButton = document.getElementById('library-metadata-submit');
    const originalHtml = submitButton?.innerHTML || '';
    const formData = new FormData(form);
    const pdfFile = formData.get('pdf_file');
    const hasPdf = pdfFile && typeof pdfFile === 'object' && Number(pdfFile.size || 0) > 0;
    formData.delete('pdf_file');
    const payload = Object.fromEntries(
        Array.from(formData.entries()).map(([key, value]) => [key, String(value).trim()])
    );
    let metadataSaved = false;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> 正在保存';
    }
    try {
        const response = await fetch('/api/library/papers/manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '单篇元数据入库失败');
        }
        metadataSaved = true;
        if (hasPdf) {
            if (!result.identity_key) {
                throw new Error('文献已入库，但未返回 PDF 关联标识');
            }
            if (submitButton) {
                submitButton.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> 正在上传 PDF';
            }
            const pdfFormData = new FormData();
            pdfFormData.append('file', pdfFile);
            const pdfResponse = await fetch(
                `/api/library/papers/${encodeURIComponent(result.identity_key)}/upload_pdf`,
                { method: 'POST', body: pdfFormData }
            );
            const pdfResult = await pdfResponse.json();
            if (!pdfResponse.ok) {
                throw new Error(pdfResult.error || 'PDF 上传失败');
            }
        }
        closeLibraryMetadataModal();
        addLog(
            hasPdf
                ? `单篇文献与 PDF 已入库：${payload.title}`
                : `${result.inserted ? '单篇文献已新增入库' : '单篇文献元数据已更新'}：${payload.title}`
        );
        await loadLibraryPapers(1, true);
    } catch (error) {
        if (metadataSaved) {
            addLog(`元数据已入库，但 PDF 上传失败：${error.message}`, 'error');
            await loadLibraryPapers(1, true);
        } else {
            addLog(`单篇元数据入库失败：${error.message}`, 'error');
        }
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = originalHtml;
        }
    }
}

async function loadLibraryPapers(page = 1, syncUrl = true) {
    currentLibraryPage = Math.max(1, page);
    if (syncUrl) {
        updateWorkspaceUrl({ preview: 'library', library_q: currentLibraryQuery, library_page: String(currentLibraryPage) });
    }
    const params = new URLSearchParams({
        page: String(currentLibraryPage),
        per_page: '20',
        q: currentLibraryQuery,
        sort_by: 'last_seen_at',
        sort_dir: 'desc'
    });

    const content = document.getElementById('library-content');
    const info = document.getElementById('library-info');
    if (content) {
        content.innerHTML = '<p>正在读取文献数据库...</p>';
    }

    try {
        const [summaryResponse, papersResponse, collectionsResponse] = await Promise.all([
            fetch('/api/library/summary'),
            fetch(`/api/library/papers?${params.toString()}`),
            fetch('/api/library/collections')
        ]);
        const summary = await summaryResponse.json();
        const result = await papersResponse.json();
        const collectionsResult = await collectionsResponse.json();
        if (!summaryResponse.ok) {
            throw new Error(summary.error || '文献数据库统计读取失败');
        }
        if (!papersResponse.ok) {
            throw new Error(result.error || '文献数据库列表读取失败');
        }
        const lastPage = Math.max(1, Number(result.total_pages || 1));
        if (currentLibraryPage > lastPage) {
            await loadLibraryPapers(lastPage, true);
            return;
        }
        if (collectionsResponse.ok) {
            currentCollections = collectionsResult.data || [];
            if (!currentCollectionId && currentCollections.length > 0) {
                currentCollectionId = currentCollections[0].collection_id;
            }
            renderGraphCollectionOptions();
            updateGraphScopeControls();
        }

        if (info) {
            if (summary.exists) {
                info.textContent = `数据库已同步 · 共 ${summary.papers || 0} 篇文献`;
            } else {
                info.textContent = '尚未创建持续文献数据库，请先执行一次检索或多源补全。';
            }
        }
        renderLibraryGlobalSummary(summary);
        renderLibraryPapers(result, summary);
    } catch (error) {
        if (content) {
            content.innerHTML = `<p>读取文献数据库失败：${escapeHtml(error.message)}</p>`;
        }
        renderLibraryGlobalSummary(null);
        const pagination = document.getElementById('library-pagination');
        if (pagination) {
            pagination.style.display = 'none';
        }
    }
}

function renderLibraryGlobalSummary(summary) {
    const panel = document.getElementById('library-global-summary');
    if (!panel) return;
    if (!summary || !summary.exists) {
        panel.innerHTML = '';
        return;
    }
    panel.innerHTML = `
        <div class="library-command-strip" aria-label="全库统计">
            <div class="library-command-title">
                <span>数据库概览</span>
                <strong>文献数据库</strong>
            </div>
            <div class="library-command-metrics">
                ${renderLibraryMetric('总文献', summary.papers || 0, '篇')}
                ${renderLibraryMetric('DOI', summary.with_doi || 0, '篇')}
                ${renderLibraryMetric('摘要', summary.with_abstract || 0, '篇')}
                ${renderLibraryMetric('已解析', summary.fulltext_parsed || 0, '篇')}
                ${renderLibraryMetric('最近更新', formatLibraryTimestamp(summary.latest_seen_at).slice(0, 10), '')}
            </div>
        </div>
    `;
}

function renderLibraryPapers(result, summary) {
    const content = document.getElementById('library-content');
    if (!content) return;
    const papers = result.data || [];
    if (!summary.exists) {
        content.innerHTML = '<p>尚未创建持续文献数据库，请先执行一次检索或多源补全。</p>';
        renderLibraryPagination(result);
        return;
    }
    if (papers.length === 0) {
        content.innerHTML = `${renderLibraryResultSummary(result)}<p>没有匹配的文献。</p>`;
        renderLibraryPagination(result);
        return;
    }
    const bulkCollectionOptions = currentCollections.map(collection => (
        `<button type="button"
                 class="collection-choice-option"
                 data-collection-id="${escapeAttribute(collection.collection_id)}"
                 onclick="addSelectedLibraryPapersToCollection(this)">
            ${escapeHtml(collection.name)}
        </button>`
    )).join('');
    const bulkCollectionAction = currentCollections.length > 0 ? `
        <span class="bulk-collection-action collection-chooser">
            <button type="button"
                    class="btn btn-secondary collection-chooser-trigger"
                    aria-expanded="false"
                    onclick="toggleCollectionChooser(this, event)">
                加入文献主题库
            </button>
            <span class="collection-choice-menu" role="menu" hidden>
                ${bulkCollectionOptions}
            </span>
        </span>
    ` : '';

    const html = `
        ${renderLibraryResultSummary(result)}
        <div class="bulk-action-bar">
            <label class="bulk-select-control">
                <input type="checkbox" name="select_all_library_papers" aria-label="选择全部文献" onchange="toggleAllLibraryPapers(this)">
                <span>选择本页</span>
            </label>
            <button type="button" class="btn btn-secondary" onclick="batchParsePaperMds('.library-paper-checkbox')">批量解析 MD</button>
            <button type="button" class="btn btn-secondary danger-action" onclick="batchDeletePaperPdfs('.library-paper-checkbox')">批量删除 PDF</button>
            <button type="button" class="btn btn-secondary danger-action" onclick="batchDeletePaperMds('.library-paper-checkbox')">批量删除解析 MD</button>
            <button type="button" class="btn btn-secondary danger-action" onclick="deleteSelectedLibraryPapers()">批量删除文献</button>
            ${bulkCollectionAction}
        </div>
        <div class="literature-table library-table">
            <div class="literature-table-head">
                <div>选择</div>
                <div>标题</div>
                <div>期刊</div>
                <div>引用</div>
                <div>更新</div>
            </div>
            ${papers.map((paper, index) => renderLibraryPaperItem(paper, result, index)).join('')}
        </div>
    `;
    content.innerHTML = html;
    renderLibraryPagination(result);
}

function renderLibraryResultSummary(result) {
    const activeQuery = String(result.q || currentLibraryQuery || '').trim();
    const hasSearch = Boolean(activeQuery);
    const queryLabel = hasSearch ? `搜索：${activeQuery}` : '-';
    const queryHtml = hasSearch ? highlightLibraryText(queryLabel, activeQuery) : escapeHtml(queryLabel);
    const total = hasSearch ? (result.total || 0) : 0;
    const withDoi = hasSearch ? (result.with_doi || 0) : 0;
    const withAbstract = hasSearch ? (result.with_abstract || 0) : 0;
    const pageCount = hasSearch ? (result.page_count || 0) : 0;
    return `
        <div class="library-result-panel" aria-label="当前搜索结果统计">
            <div class="library-result-title">
                <span>Search Result</span>
                <strong>${queryHtml}</strong>
            </div>
            <div class="library-result-metrics">
                ${renderLibraryMetric('匹配文献', total, '篇')}
                ${renderLibraryMetric('匹配 DOI', withDoi, '篇')}
                ${renderLibraryMetric('匹配摘要', withAbstract, '篇')}
                ${renderLibraryMetric('当前页', pageCount, '篇')}
            </div>
        </div>
    `;
}

function renderLibraryMetric(label, value, suffix) {
    return `
        <div class="library-metric">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}${suffix ? `<small>${escapeHtml(suffix)}</small>` : ''}</strong>
        </div>
    `;
}

function formatLibraryTimestamp(value) {
    const text = String(value || '').trim();
    if (!text) return '-';
    return text.replace('T', ' ').slice(0, 16);
}

function getPdfStatusLabel(status, source = '') {
    const value = String(status || 'not_downloaded');
    const normalizedSource = String(source || '').trim();
    if (value === 'downloaded') {
        return normalizedSource === 'upload' ? '已上传' : '已有 PDF';
    }
    if (value === 'failed') return '上传失败';
    return '未上传';
}

function getPdfStatusClass(status) {
    const value = String(status || 'not_downloaded');
    if (value === 'downloaded') return 'downloaded';
    if (value === 'failed') return 'failed';
    return 'pending';
}

function getParseStatusLabel(status) {
    const value = String(status || 'not_parsed');
    if (value === 'parsed') return '已解析';
    if (value === 'failed') return '解析失败';
    return '未解析';
}

function getParseStatusClass(status) {
    const value = String(status || 'not_parsed');
    if (value === 'parsed') return 'downloaded';
    if (value === 'failed') return 'failed';
    return 'pending';
}

function getParseEngineLabel(engine) {
    const value = String(engine || '').toLowerCase();
    if (value === 'marker') return 'Marker';
    return value || '';
}

function getParseQualityLabel(value) {
    const quality = String(value || '').trim().toLowerCase();
    if (quality === 'good') return '质量良好';
    if (quality === 'warning') return '质量警告';
    if (quality === 'poor') return '质量较差';
    return '质量未知';
}

function getParseQualityClass(value) {
    const quality = String(value || '').trim().toLowerCase();
    if (quality === 'good') return 'quality-good';
    if (quality === 'warning') return 'quality-warning';
    if (quality === 'poor') return 'quality-poor';
    return 'quality-unknown';
}

function formatCoveragePercent(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number) || number <= 0) return '0%';
    return `${Math.round(number * 100)}%`;
}

function buildParseQualityHtml(paper) {
    const quality = String(paper.parse_quality || '').trim();
    if (!quality && !paper.page_mapping_coverage && !paper.quality_warning_summary) return '';
    const coverage = formatCoveragePercent(paper.page_mapping_coverage || 0);
    const warningSummary = String(paper.quality_warning_summary || '').trim();
    const warningAttr = warningSummary ? ` title="${escapeAttribute(warningSummary)}"` : '';
    const warningBadge = warningSummary
        ? `<span class="pdf-status parse-quality-note"${warningAttr}>${escapeHtml(warningSummary)}</span>`
        : '';
    return [
        quality ? `<span class="pdf-status parse-quality-badge ${getParseQualityClass(quality)}">${escapeHtml(getParseQualityLabel(quality))}</span>` : '',
        `<span class="parse-quality-metric">页码覆盖：${escapeHtml(coverage)}</span>`,
        warningBadge
    ].filter(Boolean).join('');
}

function buildFullTextQualityMeta(result) {
    const qualityItems = [];
    const quality = String(result.parse_quality || '').trim();
    if (quality) {
        qualityItems.push(`质量：${getParseQualityLabel(quality)}`);
    }
    const coverage = Number(result.page_mapping_coverage || 0);
    if (Number.isFinite(coverage) && coverage > 0) {
        qualityItems.push(`页码覆盖：${formatCoveragePercent(coverage)}`);
    }
    const warnings = Array.isArray(result.quality_warnings) ? result.quality_warnings.filter(Boolean) : [];
    if (warnings.length) {
        qualityItems.push(`提示：${warnings.join('；')}`);
    }
    return qualityItems.map(item => `<span class="fulltext-quality-item">${escapeHtml(item)}</span>`).join('');
}

function buildPaperPdfUrl(identityKey) {
    return `/api/library/papers/${encodeURIComponent(identityKey)}/pdf`;
}

function buildPaperFullTextViewUrl(identityKey) {
    return `/library/papers/${encodeURIComponent(identityKey)}/fulltext_view`;
}

function setPdfButtonLoading(button, loading, label = '处理 PDF') {
    if (!button) return;
    button.disabled = loading;
    button.classList.toggle('is-loading', loading);
    button.textContent = loading ? '处理中...' : label;
}

async function refreshPdfLinkedViews() {
    await loadLibraryPapers(currentLibraryPage || 1);
    if (currentCollectionId) {
        await loadCollectionDetail(currentCollectionId);
    }
}

const paperParseProgress = {
    busy: false,
    startedAt: 0,
    timer: null,
    cancelRequested: false,
    abortController: null,
    activeStageIndex: 0
};

const PARSE_STAGE_DEFS = [
    { id: 'prepare', label: '环境预检', detail: '确认本地 PDF、Marker CLI 和模型加载状态' },
    { id: 'submit', label: '提交任务', detail: '向后端提交 Marker 解析请求' },
    { id: 'marker', label: 'Marker 解析', detail: '本地 Marker 正在转换 PDF 为 Markdown' },
    { id: 'chunk', label: '切块入库', detail: '按章节和段落切块，并写入 SQLite' },
    { id: 'done', label: '完成', detail: '刷新文献状态和可预览内容' }
];

function ensureParseProgressModal() {
    let modal = document.getElementById('paper-parse-progress-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'paper-parse-progress-modal';
    modal.className = 'paper-parse-progress-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="paper-parse-progress-backdrop"></div>
        <section class="paper-parse-progress-panel" role="dialog" aria-modal="true" aria-label="PDF 解析过程" tabindex="-1">
            <header class="paper-parse-progress-header">
                <div>
                    <span>Marker Markdown</span>
                    <strong id="paper-parse-progress-title">正在解析 PDF</strong>
                </div>
                <div class="paper-parse-progress-actions">
                    <button type="button" class="paper-parse-progress-cancel" id="paper-parse-progress-cancel" onclick="cancelParseProgressTask()">取消任务</button>
                    <button type="button" class="paper-parse-progress-close" id="paper-parse-progress-close" onclick="closeParseProgressModal()" disabled>关闭</button>
                </div>
            </header>
            <div class="paper-parse-progress-status" role="status" aria-live="polite" aria-atomic="true">
                <div>
                    <span id="paper-parse-progress-count">0 / 0</span>
                    <strong id="paper-parse-progress-state">准备中</strong>
                </div>
                <div>
                    <span>耗时</span>
                    <strong id="paper-parse-progress-elapsed">00:00</strong>
                </div>
                <div>
                    <span>成功</span>
                    <strong id="paper-parse-progress-success">0</strong>
                </div>
                <div>
                    <span>失败</span>
                    <strong id="paper-parse-progress-failed">0</strong>
                </div>
            </div>
            <div class="paper-parse-progress-stages" id="paper-parse-progress-stages">
                ${renderParseStageItems()}
            </div>
            <div class="paper-parse-progress-bar" aria-hidden="true">
                <span id="paper-parse-progress-fill"></span>
            </div>
            <div class="paper-parse-progress-activity">
                <span class="paper-parse-progress-spinner" aria-hidden="true"></span>
                <div>
                    <strong id="paper-parse-progress-stage-title">准备中</strong>
                    <span id="paper-parse-progress-stage-detail">正在初始化解析任务...</span>
                </div>
            </div>
            <div class="paper-parse-progress-current" id="paper-parse-progress-current">等待开始...</div>
            <ol class="paper-parse-progress-log" id="paper-parse-progress-log"></ol>
        </section>
    `;
    document.body.appendChild(modal);
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open') && !paperParseProgress.busy) {
            closeParseProgressModal();
        }
    });
    return modal;
}

function renderParseStageItems() {
    return PARSE_STAGE_DEFS.map((stage, index) => `
        <div class="paper-parse-stage" data-parse-stage="${escapeAttribute(stage.id)}">
            <span>${index + 1}</span>
            <strong>${escapeHtml(stage.label)}</strong>
        </div>
    `).join('');
}

function setParseProgressStage(stageId = 'prepare', detail = '') {
    const modal = ensureParseProgressModal();
    const stageIndex = PARSE_STAGE_DEFS.findIndex(stage => stage.id === stageId);
    const safeIndex = stageIndex === -1 ? paperParseProgress.activeStageIndex || 0 : stageIndex;
    if (stageIndex !== -1) {
        paperParseProgress.activeStageIndex = safeIndex;
    }
    const activeStage = PARSE_STAGE_DEFS[safeIndex] || PARSE_STAGE_DEFS[0];
    const terminal = ['done', 'failed', 'cancelled'].includes(stageId);

    modal.querySelectorAll('.paper-parse-stage').forEach((node, index) => {
        node.classList.toggle('is-done', terminal ? stageId === 'done' || index < safeIndex : index < safeIndex);
        node.classList.toggle('is-active', !terminal && index === safeIndex);
        node.classList.toggle('is-pending', !terminal && index > safeIndex);
        node.classList.toggle('is-failed', stageId === 'failed' && index === safeIndex);
        node.classList.toggle('is-cancelled', stageId === 'cancelled' && index === safeIndex);
    });

    const titleNode = modal.querySelector('#paper-parse-progress-stage-title');
    const detailNode = modal.querySelector('#paper-parse-progress-stage-detail');
    const spinnerNode = modal.querySelector('.paper-parse-progress-spinner');
    if (titleNode) {
        if (stageId === 'failed') titleNode.textContent = '解析失败';
        else if (stageId === 'cancelled') titleNode.textContent = '任务已取消';
        else titleNode.textContent = activeStage.label;
    }
    if (detailNode) {
        if (stageId === 'failed') detailNode.textContent = detail || '请查看下方日志中的失败原因。';
        else if (stageId === 'cancelled') detailNode.textContent = detail || '已停止提交后续解析任务。';
        else detailNode.textContent = detail || activeStage.detail;
    }
    if (spinnerNode) {
        spinnerNode.classList.toggle('is-stopped', terminal);
        spinnerNode.classList.toggle('is-error', stageId === 'failed');
        spinnerNode.classList.toggle('is-warning', stageId === 'cancelled');
    }
}

function formatParseElapsed(seconds) {
    const total = Math.max(0, Math.floor(seconds || 0));
    const minutes = String(Math.floor(total / 60)).padStart(2, '0');
    const rest = String(total % 60).padStart(2, '0');
    return `${minutes}:${rest}`;
}

function openParseProgressModal(total = 1) {
    const modal = ensureParseProgressModal();
    paperParseProgress.busy = true;
    paperParseProgress.startedAt = Date.now();
    paperParseProgress.cancelRequested = false;
    paperParseProgress.abortController = null;
    paperParseProgress.activeStageIndex = 0;
    const closeButton = modal.querySelector('#paper-parse-progress-close');
    const cancelButton = modal.querySelector('#paper-parse-progress-cancel');
    const logNode = modal.querySelector('#paper-parse-progress-log');
    if (closeButton) closeButton.disabled = true;
    if (cancelButton) cancelButton.disabled = false;
    if (logNode) logNode.innerHTML = '';
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('paper-parse-modal-open');
    activateManagedModal(modal, cancelButton);
    updateParseProgressModal({ total, current: 0, success: 0, failed: 0, state: '准备中', title: '正在解析 PDF', stage: 'prepare' });
    appendParseProgressLog('已锁定页面操作，开始准备解析任务。');
    clearInterval(paperParseProgress.timer);
    paperParseProgress.timer = setInterval(() => {
        const elapsed = document.getElementById('paper-parse-progress-elapsed');
        if (elapsed) elapsed.textContent = formatParseElapsed((Date.now() - paperParseProgress.startedAt) / 1000);
    }, 1000);
    return modal;
}

function updateParseProgressModal({ total, current, success, failed, state, title, currentTitle, stage, stageDetail } = {}) {
    const modal = ensureParseProgressModal();
    const safeTotal = Math.max(1, Number(total || 1));
    const safeCurrent = Math.max(0, Math.min(safeTotal, Number(current || 0)));
    const titleNode = modal.querySelector('#paper-parse-progress-title');
    const countNode = modal.querySelector('#paper-parse-progress-count');
    const stateNode = modal.querySelector('#paper-parse-progress-state');
    const successNode = modal.querySelector('#paper-parse-progress-success');
    const failedNode = modal.querySelector('#paper-parse-progress-failed');
    const fillNode = modal.querySelector('#paper-parse-progress-fill');
    const currentNode = modal.querySelector('#paper-parse-progress-current');
    if (titleNode && title) titleNode.textContent = title;
    if (countNode) countNode.textContent = `${safeCurrent} / ${safeTotal}`;
    if (stateNode && state) stateNode.textContent = state;
    if (successNode && success !== undefined) successNode.textContent = String(success);
    if (failedNode && failed !== undefined) failedNode.textContent = String(failed);
    if (fillNode) fillNode.style.width = `${Math.round((safeCurrent / safeTotal) * 100)}%`;
    if (currentNode && currentTitle !== undefined) currentNode.textContent = currentTitle || '等待下一篇...';
    if (stage) setParseProgressStage(stage, stageDetail || '');
}

function appendParseProgressLog(message, type = 'info') {
    const logNode = document.getElementById('paper-parse-progress-log');
    if (!logNode) return;
    const item = document.createElement('li');
    item.className = `paper-parse-log-${type}`;
    item.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    logNode.appendChild(item);
    logNode.scrollTop = logNode.scrollHeight;
}

function isParseAbortError(error) {
    return paperParseProgress.cancelRequested || error?.name === 'AbortError';
}

function finishParseProgressModal({ total = 1, current = total, success = 0, failed = 0, cancelled = false } = {}) {
    paperParseProgress.busy = false;
    paperParseProgress.abortController = null;
    clearInterval(paperParseProgress.timer);
    paperParseProgress.timer = null;
    updateParseProgressModal({
        total,
        current,
        success,
        failed,
        state: cancelled ? '已取消' : (failed ? '完成，有失败' : '完成'),
        title: cancelled ? '解析任务已取消' : '解析任务完成',
        currentTitle: cancelled ? '已停止后续解析。当前后端进程如已启动，可能会自然结束。' : (failed ? '部分 PDF 解析失败，请查看日志。' : '全部 PDF 已解析完成。'),
        stage: cancelled ? 'cancelled' : (failed ? 'failed' : 'done')
    });
    appendParseProgressLog(
        cancelled ? `任务已取消：成功 ${success} 篇，失败 ${failed} 篇。` : (failed ? `任务结束：成功 ${success} 篇，失败 ${failed} 篇。` : `任务结束：成功 ${success} 篇。`),
        cancelled || failed ? 'warning' : 'success'
    );
    const closeButton = document.getElementById('paper-parse-progress-close');
    const cancelButton = document.getElementById('paper-parse-progress-cancel');
    if (closeButton) closeButton.disabled = false;
    if (cancelButton) cancelButton.disabled = true;
}

function cancelParseProgressTask() {
    if (!paperParseProgress.busy) return;
    paperParseProgress.cancelRequested = true;
    const cancelButton = document.getElementById('paper-parse-progress-cancel');
    if (cancelButton) cancelButton.disabled = true;
    appendParseProgressLog('已请求取消任务，正在中断当前请求并停止后续队列。', 'warning');
    updateParseProgressModal({ state: '正在取消', currentTitle: '正在取消当前解析请求...', stage: 'cancelled' });
    if (paperParseProgress.abortController) {
        paperParseProgress.abortController.abort();
    }
}

function closeParseProgressModal() {
    if (paperParseProgress.busy) return;
    const modal = document.getElementById('paper-parse-progress-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('paper-parse-modal-open');
    deactivateManagedModal(modal);
}

function getPaperTitleForIdentity(identityKey, selector = '.library-paper-checkbox, .collection-paper-checkbox') {
    const checkboxes = Array.from(document.querySelectorAll(selector));
    const checkbox = checkboxes.find(item => item.value === identityKey);
    const row = checkbox?.closest('.literature-item');
    return row?.querySelector('.literature-title')?.textContent?.trim() || identityKey;
}

function getCheckedPaperItems(selector) {
    return getCheckedValues(selector).map(identityKey => ({
        identityKey,
        title: getPaperTitleForIdentity(identityKey, selector)
    }));
}

let paperParseConfirmResolver = null;

function ensurePaperParseConfirmModal() {
    let modal = document.getElementById('paper-parse-confirm-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'paper-parse-confirm-modal';
    modal.className = 'paper-parse-confirm-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="paper-parse-confirm-backdrop" data-parse-confirm-cancel></div>
        <section class="paper-parse-confirm-panel" role="dialog" aria-modal="true" aria-label="确认 PDF 解析" tabindex="-1">
            <header class="paper-parse-confirm-header">
                <div class="paper-parse-confirm-icon" aria-hidden="true">
                    <i class="fas fa-file-lines"></i>
                </div>
                <div>
                    <span>Marker Markdown</span>
                    <strong id="paper-parse-confirm-title">确认解析 PDF？</strong>
                </div>
            </header>
            <div class="paper-parse-confirm-body">
                <p id="paper-parse-confirm-message"></p>
                <div class="paper-parse-confirm-target" id="paper-parse-confirm-target"></div>
                <div class="paper-parse-confirm-meta" id="paper-parse-confirm-meta"></div>
            </div>
            <footer class="paper-parse-confirm-actions">
                <button type="button" class="paper-parse-confirm-secondary" data-parse-confirm-cancel>取消</button>
                <button type="button" class="paper-parse-confirm-primary" id="paper-parse-confirm-submit">开始解析</button>
            </footer>
        </section>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-parse-confirm-cancel]').forEach(item => {
        item.addEventListener('click', () => closePaperParseConfirmModal(false));
    });
    modal.querySelector('#paper-parse-confirm-submit')?.addEventListener('click', () => closePaperParseConfirmModal(true));
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closePaperParseConfirmModal(false);
        }
    });
    return modal;
}

function closePaperParseConfirmModal(confirmed = false) {
    const modal = document.getElementById('paper-parse-confirm-modal');
    if (modal) {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('paper-parse-confirm-open');
    if (modal) deactivateManagedModal(modal);
    if (paperParseConfirmResolver) {
        const resolver = paperParseConfirmResolver;
        paperParseConfirmResolver = null;
        resolver(Boolean(confirmed));
    }
}

function requestPaperMdParseConfirm(title = '', options = {}) {
    const count = Number(options.count || 1);
    const force = Boolean(options.force);
    const batch = Boolean(options.batch) || count > 1;
    const modal = ensurePaperParseConfirmModal();
    const titleNode = modal.querySelector('#paper-parse-confirm-title');
    const messageNode = modal.querySelector('#paper-parse-confirm-message');
    const targetNode = modal.querySelector('#paper-parse-confirm-target');
    const metaNode = modal.querySelector('#paper-parse-confirm-meta');
    const submitNode = modal.querySelector('#paper-parse-confirm-submit');

    if (paperParseConfirmResolver) {
        paperParseConfirmResolver(false);
        paperParseConfirmResolver = null;
    }

    if (titleNode) {
        titleNode.textContent = batch ? '确认批量解析 PDF？' : (force ? '确认重新解析 PDF？' : '确认解析 PDF？');
    }
    if (messageNode) {
        messageNode.textContent = batch
            ? `即将提交 ${count} 篇文献到本地 Marker，生成 Markdown 全文并写入 SQLite。`
            : '即将使用本地 Marker 解析这篇文献的 PDF，生成 Markdown 全文并写入 SQLite。';
    }
    if (targetNode) {
        targetNode.textContent = batch ? `${count} 篇已选文献` : String(title || '该文献').trim();
    }
    if (metaNode) {
        metaNode.innerHTML = [
            '<span><i class="fas fa-computer"></i> 本地 Marker</span>',
            '<span><i class="fas fa-clock"></i> 可能耗时数分钟</span>',
            force ? '<span class="is-warning"><i class="fas fa-rotate"></i> 覆盖现有 MD</span>' : '',
            batch ? '<span class="is-warning"><i class="fas fa-layer-group"></i> 批量队列</span>' : ''
        ].filter(Boolean).join('');
    }
    if (submitNode) {
        submitNode.textContent = batch ? '开始批量解析' : (force ? '重新解析' : '开始解析');
    }

    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('paper-parse-confirm-open');
    activateManagedModal(modal, submitNode);
    return new Promise(resolve => {
        paperParseConfirmResolver = resolve;
    });
}

let dangerConfirmResolver = null;

function renderDangerConfirmMeta(meta = []) {
    return meta.map(item => {
        if (!item) return '';
        if (typeof item === 'string') {
            return `<span>${escapeHtml(item)}</span>`;
        }
        const icon = item.icon ? `<i class="${escapeAttribute(item.icon)}"></i> ` : '';
        const className = item.danger ? ' class="is-danger"' : (item.warning ? ' class="is-warning"' : '');
        return `<span${className}>${icon}${escapeHtml(item.text || '')}</span>`;
    }).filter(Boolean).join('');
}

function ensureDangerConfirmModal() {
    let modal = document.getElementById('danger-confirm-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'danger-confirm-modal';
    modal.className = 'paper-parse-confirm-modal danger-confirm-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="paper-parse-confirm-backdrop" data-danger-confirm-cancel></div>
        <section class="paper-parse-confirm-panel" role="dialog" aria-modal="true" aria-label="确认危险操作" tabindex="-1">
            <header class="paper-parse-confirm-header">
                <div class="paper-parse-confirm-icon" aria-hidden="true">
                    <i class="fas fa-triangle-exclamation"></i>
                </div>
                <div>
                    <span>危险操作确认</span>
                    <strong id="danger-confirm-title">确认执行？</strong>
                </div>
            </header>
            <div class="paper-parse-confirm-body">
                <p id="danger-confirm-message"></p>
                <div class="paper-parse-confirm-target" id="danger-confirm-target"></div>
                <div class="paper-parse-confirm-meta" id="danger-confirm-meta"></div>
            </div>
            <footer class="paper-parse-confirm-actions">
                <button type="button" class="paper-parse-confirm-secondary" id="danger-confirm-cancel" data-danger-confirm-cancel>取消</button>
                <button type="button" class="paper-parse-confirm-primary" id="danger-confirm-submit">确认删除</button>
            </footer>
        </section>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-danger-confirm-cancel]').forEach(item => {
        item.addEventListener('click', () => closeDangerConfirmModal(false));
    });
    modal.querySelector('#danger-confirm-submit')?.addEventListener('click', () => closeDangerConfirmModal(true));
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closeDangerConfirmModal(false);
        }
    });
    return modal;
}

function closeDangerConfirmModal(confirmed = false) {
    const modal = document.getElementById('danger-confirm-modal');
    if (modal) {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('danger-confirm-open');
    if (modal) deactivateManagedModal(modal);
    if (dangerConfirmResolver) {
        const resolver = dangerConfirmResolver;
        dangerConfirmResolver = null;
        resolver(Boolean(confirmed));
    }
}

function requestDangerConfirm(options = {}) {
    const modal = ensureDangerConfirmModal();
    const titleNode = modal.querySelector('#danger-confirm-title');
    const messageNode = modal.querySelector('#danger-confirm-message');
    const targetNode = modal.querySelector('#danger-confirm-target');
    const metaNode = modal.querySelector('#danger-confirm-meta');
    const submitNode = modal.querySelector('#danger-confirm-submit');
    const cancelNode = modal.querySelector('#danger-confirm-cancel');

    if (dangerConfirmResolver) {
        dangerConfirmResolver(false);
        dangerConfirmResolver = null;
    }

    if (titleNode) titleNode.textContent = options.title || '确认执行危险操作？';
    if (messageNode) messageNode.textContent = options.message || '该操作执行后可能无法恢复，请确认后继续。';
    if (targetNode) targetNode.textContent = String(options.target || '当前选择').trim();
    if (metaNode) metaNode.innerHTML = renderDangerConfirmMeta(options.meta || []);
    if (submitNode) submitNode.textContent = options.confirmText || '确认删除';
    if (cancelNode) cancelNode.textContent = options.cancelText || '取消';

    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('danger-confirm-open');
    activateManagedModal(modal, cancelNode);
    return new Promise(resolve => {
        dangerConfirmResolver = resolve;
    });
}

async function parseLibraryPdf(identityKey, button = null, force = false) {
    if (!identityKey) return;
    const title = getPaperTitleForIdentity(identityKey);
    if (!(await requestPaperMdParseConfirm(title, { force }))) {
        addLog('已取消 PDF 解析。', 'warning');
        return;
    }
    const originalLabel = button ? button.textContent : 'Marker 解析 MD';
    if (button) {
        button.disabled = true;
        button.classList.add('is-loading');
        button.textContent = 'Marker 解析中...';
    }
    addLog('Marker 正在解析 PDF 并生成 Markdown...');
    openParseProgressModal(1);
    updateParseProgressModal({
        total: 1,
        current: 0,
        success: 0,
        failed: 0,
        state: '环境预检',
        currentTitle: `${title} · 正在预热 Marker；如果模型缓存缺失，会在这里提前失败。`,
        stage: 'prepare'
    });
    appendParseProgressLog(`环境预检：${title}`);
    try {
        paperParseProgress.abortController = new AbortController();
        updateParseProgressModal({
            total: 1,
            current: 0,
            success: 0,
            failed: 0,
            state: 'Marker 解析中',
            currentTitle: `${title} · 本地 Marker 正在生成 Markdown，较大的 PDF 可能需要数分钟。`,
            stage: 'marker'
        });
        appendParseProgressLog(`预检通过，已提交到 Marker：${title}`);
        const result = await requestPaperMdParse(identityKey, force, paperParseProgress.abortController.signal);
        updateParseProgressModal({ total: 1, current: 1, success: 1, failed: 0, state: '切块入库', currentTitle: title, stage: 'chunk' });
        appendParseProgressLog(`解析成功：${result.fulltext?.chunk_count || 0} 个 Markdown 片段。`, 'success');
        if (result.fulltext?.page_mapping_coverage || result.fulltext?.parse_quality) {
            appendParseProgressLog(`页码覆盖 ${formatCoveragePercent(result.fulltext?.page_mapping_coverage || 0)} · ${getParseQualityLabel(result.fulltext?.parse_quality || '')}`, 'info');
        }
        updateParseProgressModal({ total: 1, current: 1, success: 1, failed: 0, state: '写入完成', currentTitle: title, stage: 'done' });
        addLog(`Marker 解析完成：${result.fulltext?.chunk_count || 0} 个 Markdown 片段。`);
        finishParseProgressModal({ total: 1, success: 1, failed: 0 });
    } catch (error) {
        if (isParseAbortError(error)) {
            updateParseProgressModal({ total: 1, current: 0, success: 0, failed: 0, state: '已取消', currentTitle: title, stage: 'cancelled' });
            appendParseProgressLog('解析任务已取消。', 'warning');
            addLog('解析任务已取消。', 'warning');
            finishParseProgressModal({ total: 1, current: 0, success: 0, failed: 0, cancelled: true });
            return;
        }
        updateParseProgressModal({ total: 1, current: 1, success: 0, failed: 1, state: '解析失败', currentTitle: title, stage: 'failed', stageDetail: error.message });
        appendParseProgressLog(`解析失败：${error.message}`, 'error');
        addLog(`Marker 解析失败：${error.message}`, 'error');
        finishParseProgressModal({ total: 1, success: 0, failed: 1 });
    } finally {
        if (button) {
            button.disabled = false;
            button.classList.remove('is-loading');
            button.textContent = originalLabel;
        }
        await refreshPdfLinkedViews();
    }
}

function ensureFullTextModal() {
    let modal = document.getElementById('paper-fulltext-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'paper-fulltext-modal';
    modal.className = 'paper-fulltext-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
        <div class="paper-fulltext-backdrop" data-fulltext-close></div>
        <section class="paper-fulltext-panel" role="dialog" aria-modal="true" aria-label="Markdown 全文" tabindex="-1">
            <header class="paper-fulltext-header">
                <div>
                    <span>Markdown</span>
                    <strong id="paper-fulltext-title">Markdown 全文</strong>
                </div>
                <button type="button" class="paper-fulltext-close" data-fulltext-close aria-label="关闭全文窗口">
                    <i class="fas fa-times"></i>
                </button>
            </header>
            <div class="paper-fulltext-meta" id="paper-fulltext-meta"></div>
            <div class="paper-fulltext-toolbar" id="paper-fulltext-toolbar">
                <div class="paper-fulltext-toolbar-group">
                    <button type="button" class="pdf-action-button" id="paper-fulltext-edit-toggle">修改</button>
                    <button type="button" class="pdf-action-button" id="paper-fulltext-save" hidden>保存</button>
                    <button type="button" class="pdf-action-button" id="paper-fulltext-cancel" hidden>取消</button>
                    <span class="paper-fulltext-mode-badge is-render" id="paper-fulltext-mode-badge">渲染视图</span>
                </div>
                <div class="paper-fulltext-toolbar-group">
                    <button type="button" class="pdf-action-button" id="paper-fulltext-font-decrease" aria-label="缩小字体">A-</button>
                    <button type="button" class="pdf-action-button" id="paper-fulltext-font-reset" aria-label="重置字体">100%</button>
                    <button type="button" class="pdf-action-button" id="paper-fulltext-font-increase" aria-label="放大字体">A+</button>
                </div>
            </div>
            <div class="paper-fulltext-status" id="paper-fulltext-status" role="status" aria-live="polite" aria-atomic="true" hidden></div>
            <article class="paper-fulltext-body markdown-preview" id="paper-fulltext-body"></article>
        </section>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-fulltext-close]').forEach(item => {
        item.addEventListener('click', closeFullTextModal);
    });
    modal.querySelector('#paper-fulltext-edit-toggle')?.addEventListener('click', () => setFullTextModalMode('edit'));
    modal.querySelector('#paper-fulltext-cancel')?.addEventListener('click', cancelFullTextModalEdit);
    modal.querySelector('#paper-fulltext-save')?.addEventListener('click', saveFullTextModalContent);
    modal.querySelector('#paper-fulltext-font-decrease')?.addEventListener('click', () => adjustFullTextFontScale(-FULLTEXT_FONT_SCALE_STEP));
    modal.querySelector('#paper-fulltext-font-reset')?.addEventListener('click', () => setFullTextFontScale(1));
    modal.querySelector('#paper-fulltext-font-increase')?.addEventListener('click', () => adjustFullTextFontScale(FULLTEXT_FONT_SCALE_STEP));
    document.addEventListener('keydown', event => {
        trapManagedModalFocus(event, modal);
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            if (fullTextModalState.mode === 'edit') {
                closeFullTextModal();
                return;
            }
            closeFullTextModal();
        }
    });
    applyFullTextFontScale();
    return modal;
}

function getFullTextModalNodes() {
    const modal = ensureFullTextModal();
    return {
        modal,
        titleNode: modal.querySelector('#paper-fulltext-title'),
        metaNode: modal.querySelector('#paper-fulltext-meta'),
        bodyNode: modal.querySelector('#paper-fulltext-body'),
        statusNode: modal.querySelector('#paper-fulltext-status'),
        editToggleNode: modal.querySelector('#paper-fulltext-edit-toggle'),
        saveNode: modal.querySelector('#paper-fulltext-save'),
        cancelNode: modal.querySelector('#paper-fulltext-cancel'),
        modeBadgeNode: modal.querySelector('#paper-fulltext-mode-badge'),
        fontResetNode: modal.querySelector('#paper-fulltext-font-reset'),
    };
}

function buildFullTextMetaHtml(result) {
    const metaItems = [
        result.authors ? `作者：${result.authors}` : '',
        result.venue ? `期刊：${result.venue}` : '',
        result.doi ? `DOI：${result.doi}` : '',
        result.page_count ? `页数：${result.page_count}` : '',
        result.chunk_count ? `片段：${result.chunk_count}` : '',
        result.char_count ? `字符：${result.char_count}` : '',
        result.parse_engine ? `引擎：${getParseEngineLabel(result.parse_engine)}` : '',
        result.parsed_at ? `解析：${formatLibraryTimestamp(result.parsed_at)}` : ''
    ].filter(Boolean);
    const qualityHtml = buildFullTextQualityMeta(result);
    const metaHtml = metaItems.map(item => `<span>${escapeHtml(item)}</span>`).join('');
    return qualityHtml ? `${metaHtml}${metaHtml ? '' : ''}${qualityHtml}` : metaHtml;
}

function setFullTextStatus(message = '', tone = '') {
    const { statusNode } = getFullTextModalNodes();
    if (!statusNode) return;
    const text = String(message || '').trim();
    if (!text) {
        statusNode.hidden = true;
        statusNode.textContent = '';
        statusNode.className = 'paper-fulltext-status';
        return;
    }
    statusNode.hidden = false;
    statusNode.textContent = text;
    statusNode.className = `paper-fulltext-status${tone ? ` is-${tone}` : ''}`;
}

function applyFullTextFontScale() {
    const scale = clampFullTextFontScale(fullTextModalState.fontScale || 1);
    fullTextModalState.fontScale = scale;
    const modal = document.getElementById('paper-fulltext-modal');
    if (modal) {
        modal.style.setProperty('--paper-fulltext-font-scale', String(scale));
        modal.querySelector('.paper-fulltext-panel')?.style.setProperty('--paper-fulltext-font-scale', String(scale));
    }
    const fontResetNode = document.getElementById('paper-fulltext-font-reset');
    if (fontResetNode) {
        fontResetNode.textContent = `${Math.round(scale * 100)}%`;
    }
    const fullTextPageRoot = document.getElementById('fulltext-page-root');
    if (fullTextPageRoot) {
        const layoutScale = Math.min(1.7, Math.max(0.82, scale));
        fullTextPageRoot.style.setProperty('--paper-fulltext-font-scale', String(scale));
        fullTextPageRoot.style.setProperty('--paper-fulltext-body-font-size', `calc(1.1rem * ${scale})`);
        fullTextPageRoot.style.setProperty('--paper-fulltext-body-line-height', '1.78');
        fullTextPageRoot.style.setProperty('--paper-fulltext-layout-scale', String(layoutScale));
        fullTextPageRoot.style.setProperty('--paper-fulltext-page-width', `${Math.round(1280 * layoutScale)}px`);
        fullTextPageRoot.style.setProperty('--paper-fulltext-figure-width', `${Math.round(1180 * layoutScale)}px`);
        fullTextPageRoot.style.setProperty('--paper-fulltext-body-padding-x', `${Math.round(44 * layoutScale)}px`);
        fullTextPageRoot.style.setProperty('--paper-fulltext-body-padding-y', `${Math.round(28 * layoutScale)}px`);
    }
    const fullTextPageResetNode = document.getElementById('fulltext-page-font-reset');
    if (fullTextPageResetNode) {
        fullTextPageResetNode.textContent = `${Math.round(scale * 100)}%`;
    }
}

function setFullTextFontScale(value) {
    fullTextModalState.fontScale = setStoredFullTextFontScale(value);
    applyFullTextFontScale();
}

function adjustFullTextFontScale(delta) {
    setFullTextFontScale((fullTextModalState.fontScale || 1) + delta);
}

function renderFullTextModalBody() {
    const { bodyNode, modeBadgeNode, editToggleNode, saveNode, cancelNode, modal } = getFullTextModalNodes();
    if (!bodyNode || !modal) return;
    modal.classList.toggle('is-editing', fullTextModalState.mode === 'edit');
    if (modeBadgeNode) {
        const isEditingMode = fullTextModalState.mode === 'edit';
        modeBadgeNode.textContent = isEditingMode ? '源码编辑' : '渲染视图';
        modeBadgeNode.className = `paper-fulltext-mode-badge ${isEditingMode ? 'is-edit' : 'is-render'}`;
    }
    if (editToggleNode) editToggleNode.hidden = fullTextModalState.mode === 'edit';
    if (saveNode) {
        saveNode.hidden = fullTextModalState.mode !== 'edit';
        saveNode.disabled = !!fullTextModalState.saving;
        saveNode.textContent = fullTextModalState.saving ? '保存中...' : '保存';
    }
    if (cancelNode) {
        cancelNode.hidden = fullTextModalState.mode !== 'edit';
        cancelNode.disabled = !!fullTextModalState.saving;
    }
    if (editToggleNode) editToggleNode.disabled = !!fullTextModalState.saving || !fullTextModalState.data;

    if (fullTextModalState.mode === 'edit') {
        bodyNode.classList.remove('markdown-preview');
        bodyNode.innerHTML = `<textarea id="paper-fulltext-editor" name="paper_fulltext" class="paper-fulltext-editor" aria-label="Markdown 全文源码" spellcheck="false" autocomplete="off"></textarea>`;
        const editor = bodyNode.querySelector('#paper-fulltext-editor');
        if (editor) {
            editor.value = fullTextModalState.draftText || fullTextModalState.sourceText || '';
            editor.addEventListener('input', () => {
                fullTextModalState.draftText = editor.value;
                fullTextModalState.dirty = editor.value !== fullTextModalState.sourceText;
            });
        }
        return;
    }

    bodyNode.classList.add('markdown-preview');
    bodyNode.innerHTML = renderMarkdownDocument(fullTextModalState.sourceText || '全文为空。', {
        normalizeReport: false,
        normalizeHeadings: false,
        assetBaseUrl: fullTextModalState.assetBaseUrl || ''
    });
    demoteFullTextBodyH1(bodyNode);
    typesetMarkdownMath(bodyNode);
}

function demoteFullTextBodyH1(container) {
    container?.querySelectorAll('h1').forEach(heading => {
        const replacement = document.createElement('h2');
        Array.from(heading.attributes).forEach(attribute => replacement.setAttribute(attribute.name, attribute.value));
        replacement.innerHTML = heading.innerHTML;
        heading.replaceWith(replacement);
    });
}

function syncFullTextModalFromResult(result, fallbackTitle = '') {
    const { titleNode, metaNode } = getFullTextModalNodes();
    fullTextModalState.data = result;
    fullTextModalState.sourceText = String(result.full_text || '');
    fullTextModalState.draftText = fullTextModalState.sourceText;
    fullTextModalState.dirty = false;
    fullTextModalState.assetBaseUrl = `/api/library/papers/${encodeURIComponent(result.identity_key || fullTextModalState.identityKey)}/fulltext_asset?path=`;
    if (titleNode) titleNode.textContent = result.title || fallbackTitle || 'Markdown 全文';
    if (metaNode) metaNode.innerHTML = buildFullTextMetaHtml(result);
    renderFullTextModalBody();
}

function setFullTextModalMode(mode) {
    const nextMode = mode === 'edit' ? 'edit' : 'render';
    if (nextMode === 'edit' && !fullTextModalState.data) return;
    fullTextModalState.mode = nextMode;
    if (nextMode === 'edit') {
        fullTextModalState.draftText = fullTextModalState.sourceText;
        setFullTextStatus('已切换到 Markdown 源码编辑模式。保存后会切回渲染状态。', 'info');
    } else if (fullTextModalState.notice) {
        setFullTextStatus(fullTextModalState.notice, 'success');
    } else {
        setFullTextStatus('当前显示为渲染状态。', 'info');
    }
    renderFullTextModalBody();
}

function cancelFullTextModalEdit() {
    if (fullTextModalState.saving) return;
    fullTextModalState.draftText = fullTextModalState.sourceText;
    fullTextModalState.dirty = false;
    fullTextModalState.notice = '';
    setFullTextStatus('已取消修改，恢复到上次保存内容。', 'info');
    setFullTextModalMode('render');
}

async function saveFullTextModalContent() {
    if (!fullTextModalState.identityKey || fullTextModalState.saving) return;
    const { bodyNode } = getFullTextModalNodes();
    const editor = bodyNode ? bodyNode.querySelector('#paper-fulltext-editor') : null;
    const draftText = editor ? editor.value : fullTextModalState.draftText;
    if (!String(draftText || '').trim()) {
        setFullTextStatus('Markdown 内容不能为空。', 'error');
        return;
    }
    fullTextModalState.saving = true;
    fullTextModalState.draftText = draftText;
    setFullTextStatus('正在保存 Markdown，并切回渲染状态...', 'info');
    renderFullTextModalBody();
    try {
        const response = await fetch(`/api/library/papers/${encodeURIComponent(fullTextModalState.identityKey)}/fulltext`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ full_text: draftText })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '保存全文失败');
        }
        fullTextModalState.notice = `保存完成，当前显示渲染状态 · ${result.chunk_count || 0} 个片段`;
        fullTextModalState.dirty = false;
        fullTextModalState.mode = 'render';
        syncFullTextModalFromResult(result, result.title || 'Markdown 全文');
        setFullTextStatus(fullTextModalState.notice, 'success');
        addLog(`Markdown 已保存：${result.title || fullTextModalState.identityKey}`);
        await refreshPdfLinkedViews();
    } catch (error) {
        setFullTextStatus(`保存失败：${error.message}`, 'error');
        fullTextModalState.mode = 'edit';
        renderFullTextModalBody();
    } finally {
        fullTextModalState.saving = false;
        renderFullTextModalBody();
    }
}

function openFullTextModalShell(title = 'Markdown 全文') {
    const { modal, titleNode, metaNode, bodyNode } = getFullTextModalNodes();
    fullTextModalState.mode = 'render';
    fullTextModalState.saving = false;
    fullTextModalState.notice = '';
    fullTextModalState.sourceText = '';
    fullTextModalState.draftText = '';
    fullTextModalState.dirty = false;
    fullTextModalState.data = null;
    fullTextModalState.assetBaseUrl = '';
    renderMarkdownTitle(titleNode, title);
    if (metaNode) metaNode.innerHTML = '';
    if (bodyNode) {
        bodyNode.classList.add('markdown-preview');
        bodyNode.textContent = '正在读取 Markdown 全文...';
    }
    setFullTextStatus('正在读取 Markdown 全文...', 'info');
    applyFullTextFontScale();
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('paper-fulltext-modal-open');
    activateManagedModal(modal, modal.querySelector('.paper-fulltext-close'));
    return modal;
}

async function closeFullTextModal() {
    const modal = document.getElementById('paper-fulltext-modal');
    if (!modal) return;
    if (isFullTextDirty()) {
        const discard = await requestDangerConfirm({
            title: '放弃未保存的 Markdown 修改？',
            message: '关闭后，本次尚未保存的全文修改将无法恢复。',
            target: fullTextModalState.data?.title || '当前 Markdown 全文',
            confirmText: '放弃修改',
            cancelText: '继续编辑',
            meta: [{ icon: 'fas fa-file-pen', text: '存在未保存内容', danger: true }],
        });
        if (!discard) return;
    }
    fullTextModalState.dirty = false;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('paper-fulltext-modal-open');
    deactivateManagedModal(modal);
}

function renderMarkdownTitle(titleNode, title = '') {
    if (!titleNode) return;
    titleNode.textContent = plainTextMarkdownTitle(title);
}

function plainTextMarkdownTitle(title = '') {
    return String(title || 'Markdown 全文')
        .replace(/\\\((.+?)\\\)/g, '$1')
        .replace(/\$(?!\$)([^$\n]+?)\$/g, '$1');
}

async function viewPaperFullText(identityKey, fallbackTitle = '') {
    if (!identityKey) return;
    window.open(buildPaperFullTextViewUrl(identityKey), '_blank', 'noopener,noreferrer');
}

function getFullTextViewPageNodes() {
    return {
        rootNode: document.getElementById('fulltext-page-root'),
        titleNode: document.getElementById('fulltext-page-title'),
        metaNode: document.getElementById('fulltext-page-meta'),
        statusNode: document.getElementById('fulltext-page-status'),
        bodyNode: document.getElementById('fulltext-page-body'),
        decreaseNode: document.getElementById('fulltext-page-font-decrease'),
        resetNode: document.getElementById('fulltext-page-font-reset'),
        increaseNode: document.getElementById('fulltext-page-font-increase'),
        editToggleNode: document.getElementById('fulltext-page-edit-toggle'),
        saveNode: document.getElementById('fulltext-page-save'),
        cancelNode: document.getElementById('fulltext-page-cancel'),
        modeBadgeNode: document.getElementById('fulltext-page-mode-badge'),
    };
}

function setFullTextViewPageStatus(message = '', tone = 'info') {
    const { statusNode } = getFullTextViewPageNodes();
    if (!statusNode) return;
    const text = String(message || '').trim();
    if (!text) {
        statusNode.hidden = true;
        statusNode.textContent = '';
        statusNode.className = 'fulltext-page-status';
        return;
    }
    statusNode.hidden = false;
    statusNode.textContent = text;
    statusNode.className = `fulltext-page-status is-${tone || 'info'}`;
}

function bindFullTextViewPageControls() {
    const { decreaseNode, resetNode, increaseNode, editToggleNode, saveNode, cancelNode } = getFullTextViewPageNodes();
    decreaseNode?.addEventListener('click', () => adjustFullTextFontScale(-FULLTEXT_FONT_SCALE_STEP));
    resetNode?.addEventListener('click', () => setFullTextFontScale(1));
    increaseNode?.addEventListener('click', () => adjustFullTextFontScale(FULLTEXT_FONT_SCALE_STEP));
    editToggleNode?.addEventListener('click', () => setFullTextViewPageMode('edit'));
    saveNode?.addEventListener('click', saveFullTextViewPageContent);
    cancelNode?.addEventListener('click', cancelFullTextViewPageEdit);
}

function captureFullTextViewPagePosition() {
    const { bodyNode } = getFullTextViewPageNodes();
    if (!bodyNode) return null;
    const toolbar = document.querySelector('.fulltext-page-toolbar');
    const toolbarHeight = toolbar ? toolbar.getBoundingClientRect().height : 0;
    const anchorY = window.scrollY + toolbarHeight + 16;
    const bodyTop = window.scrollY + bodyNode.getBoundingClientRect().top;
    const bodyHeight = Math.max(1, bodyNode.offsetHeight || bodyNode.scrollHeight || 1);
    return Math.min(1, Math.max(0, (anchorY - bodyTop) / bodyHeight));
}

function restoreFullTextViewPagePosition(ratio) {
    if (!Number.isFinite(ratio)) return;
    const { bodyNode } = getFullTextViewPageNodes();
    if (!bodyNode) return;
    const toolbar = document.querySelector('.fulltext-page-toolbar');
    const toolbarHeight = toolbar ? toolbar.getBoundingClientRect().height : 0;
    const bodyTop = window.scrollY + bodyNode.getBoundingClientRect().top;
    const bodyHeight = Math.max(1, bodyNode.offsetHeight || bodyNode.scrollHeight || 1);
    const targetY = Math.max(0, bodyTop + bodyHeight * ratio - toolbarHeight - 16);
    window.scrollTo({ top: targetY, behavior: 'auto' });
}

function getFullTextCaretPositionForRatio(text, ratio) {
    const source = String(text || '');
    if (!source) return 0;
    const normalizedRatio = Number.isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : 0;
    const lines = source.split('\n');
    const targetLine = Math.min(lines.length - 1, Math.max(0, Math.floor(lines.length * normalizedRatio)));
    let position = 0;
    for (let index = 0; index < targetLine; index += 1) {
        position += lines[index].length + 1;
    }
    return Math.min(source.length, position);
}

function resizeFullTextPageEditor(editor) {
    if (!editor) return;
    const scrollY = window.scrollY;
    const minHeight = Math.max(320, window.innerHeight - 220);
    editor.style.height = `${Math.max(minHeight, editor.scrollHeight + 4)}px`;
    if (Math.abs(window.scrollY - scrollY) > 1) {
        window.scrollTo({ top: scrollY, behavior: 'auto' });
    }
}

function renderFullTextViewPageBody() {
    const { rootNode, bodyNode, editToggleNode, saveNode, cancelNode, modeBadgeNode } = getFullTextViewPageNodes();
    if (!bodyNode) return;
    const isEditing = fullTextModalState.mode === 'edit';
    const restoreRatio = fullTextModalState.fullTextViewScrollRatio;
    rootNode?.classList.toggle('is-editing', isEditing);
    bodyNode.classList.toggle('is-editing', isEditing);
    if (modeBadgeNode) {
        modeBadgeNode.textContent = isEditing ? '源码编辑' : '渲染视图';
        modeBadgeNode.className = `paper-fulltext-mode-badge ${isEditing ? 'is-edit' : 'is-render'}`;
    }
    if (editToggleNode) {
        editToggleNode.hidden = isEditing;
        editToggleNode.disabled = !!fullTextModalState.saving || !fullTextModalState.data;
    }
    if (saveNode) {
        saveNode.hidden = !isEditing;
        saveNode.disabled = !!fullTextModalState.saving;
        saveNode.textContent = fullTextModalState.saving ? '保存中...' : '保存';
    }
    if (cancelNode) {
        cancelNode.hidden = !isEditing;
        cancelNode.disabled = !!fullTextModalState.saving;
    }

    if (isEditing) {
        bodyNode.classList.remove('markdown-preview');
        bodyNode.innerHTML = `<textarea id="fulltext-page-editor" name="fulltext_page_source" class="fulltext-page-editor" aria-label="Markdown 全文源码" spellcheck="false" autocomplete="off"></textarea>`;
        const editor = bodyNode.querySelector('#fulltext-page-editor');
        if (editor) {
            editor.value = fullTextModalState.draftText || fullTextModalState.sourceText || '';
            resizeFullTextPageEditor(editor);
            editor.addEventListener('input', () => {
                fullTextModalState.draftText = editor.value;
                fullTextModalState.dirty = editor.value !== fullTextModalState.sourceText;
                resizeFullTextPageEditor(editor);
            });
            window.setTimeout(() => {
                resizeFullTextPageEditor(editor);
                editor.scrollTop = 0;
                restoreFullTextViewPagePosition(restoreRatio);
            }, 0);
        }
        return;
    }

    bodyNode.classList.add('markdown-preview');
    bodyNode.innerHTML = renderMarkdownDocument(fullTextModalState.sourceText || '全文为空。', {
        normalizeReport: false,
        normalizeHeadings: false,
        assetBaseUrl: fullTextModalState.assetBaseUrl || ''
    });
    demoteFullTextBodyH1(bodyNode);
    typesetMarkdownMath(bodyNode);
    window.setTimeout(() => restoreFullTextViewPagePosition(restoreRatio), 0);
}

function renderFullTextViewPage(result) {
    const { titleNode, metaNode } = getFullTextViewPageNodes();
    fullTextModalState.data = result;
    fullTextModalState.sourceText = String(result.full_text || '');
    fullTextModalState.draftText = fullTextModalState.sourceText;
    fullTextModalState.dirty = false;
    fullTextModalState.assetBaseUrl = `/api/library/papers/${encodeURIComponent(result.identity_key || fullTextModalState.identityKey)}/fulltext_asset?path=`;
    fullTextModalState.mode = 'render';
    fullTextModalState.saving = false;
    if (titleNode) {
        const pageTitle = result.title || 'Markdown 全文';
        renderMarkdownTitle(titleNode, pageTitle);
        document.title = `${plainTextMarkdownTitle(pageTitle)} - LiterNexus`;
    }
    if (metaNode) {
        metaNode.innerHTML = buildFullTextMetaHtml(result);
    }
    renderFullTextViewPageBody();
    setFullTextViewPageStatus('当前显示为独立阅读页。', 'success');
}

function setFullTextViewPageMode(mode) {
    if (fullTextModalState.saving) return;
    const nextMode = mode === 'edit' ? 'edit' : 'render';
    if (nextMode === 'edit' && !fullTextModalState.data) return;
    fullTextModalState.fullTextViewScrollRatio = captureFullTextViewPagePosition();
    fullTextModalState.mode = nextMode;
    if (nextMode === 'edit') {
        fullTextModalState.draftText = fullTextModalState.sourceText;
        setFullTextViewPageStatus('已切换到 Markdown 源码编辑模式。保存后会切回渲染状态。', 'info');
    } else {
        setFullTextViewPageStatus('当前显示为独立阅读页。', 'success');
    }
    renderFullTextViewPageBody();
}

function cancelFullTextViewPageEdit() {
    if (fullTextModalState.saving) return;
    fullTextModalState.draftText = fullTextModalState.sourceText;
    fullTextModalState.dirty = false;
    setFullTextViewPageStatus('已取消修改，恢复到上次保存内容。', 'info');
    setFullTextViewPageMode('render');
}

async function saveFullTextViewPageContent() {
    if (!fullTextModalState.identityKey || fullTextModalState.saving) return;
    const { bodyNode } = getFullTextViewPageNodes();
    const editor = bodyNode ? bodyNode.querySelector('#fulltext-page-editor') : null;
    const draftText = editor ? editor.value : fullTextModalState.draftText;
    if (!String(draftText || '').trim()) {
        setFullTextViewPageStatus('Markdown 内容不能为空。', 'error');
        return;
    }
    fullTextModalState.fullTextViewScrollRatio = captureFullTextViewPagePosition();
    fullTextModalState.saving = true;
    fullTextModalState.draftText = draftText;
    setFullTextViewPageStatus('正在保存 Markdown，并切回渲染状态...', 'info');
    renderFullTextViewPageBody();
    try {
        const response = await fetch(`/api/library/papers/${encodeURIComponent(fullTextModalState.identityKey)}/fulltext`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ full_text: draftText })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '保存全文失败');
        }
        renderFullTextViewPage(result);
        fullTextModalState.dirty = false;
        setFullTextViewPageStatus(`保存完成，当前显示渲染状态 · ${result.chunk_count || 0} 个片段`, 'success');
    } catch (error) {
        fullTextModalState.mode = 'edit';
        setFullTextViewPageStatus(`保存失败：${error.message}`, 'error');
        renderFullTextViewPageBody();
    } finally {
        fullTextModalState.saving = false;
        renderFullTextViewPageBody();
    }
}

async function loadFullTextViewPage() {
    const config = window.LITERNEXUS_FULLTEXT_VIEW || window.SCHOLARFLOW_FULLTEXT_VIEW || {};
    const identityKey = config.identityKey || '';
    const { bodyNode } = getFullTextViewPageNodes();
    if (!identityKey) {
        if (bodyNode) bodyNode.textContent = '缺少文献标识。';
        setFullTextViewPageStatus('缺少文献标识。', 'error');
        return;
    }
    fullTextModalState.identityKey = identityKey;
    if (bodyNode) bodyNode.textContent = '';
    setFullTextViewPageStatus('正在读取 Markdown 全文...', 'info');
    try {
        const response = await fetch(`/api/library/papers/${encodeURIComponent(identityKey)}/fulltext`, {
            cache: 'no-store'
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '读取全文失败');
        }
        renderFullTextViewPage(result);
    } catch (error) {
        if (bodyNode) {
            bodyNode.classList.remove('markdown-preview');
            bodyNode.textContent = `读取全文失败：${error.message}`;
        }
        setFullTextViewPageStatus(`读取全文失败：${error.message}`, 'error');
    }
}

function initializeFullTextViewPage() {
    initializeThemeToggle();
    bindFullTextViewPageControls();
    applyFullTextFontScale();
    loadFullTextViewPage();
}

async function deletePaperPdf(identityKey, context = 'library', button = null) {
    if (!identityKey) return;
    const title = getPaperTitleForIdentity(identityKey);
    const confirmed = await requestDangerConfirm({
        title: '删除本地 PDF？',
        message: '将删除该文献关联的本地 PDF，并把下载状态回退为未上传。',
        target: title,
        confirmText: '删除 PDF',
        meta: [
            { icon: 'fas fa-file-pdf', text: '删除本地 PDF', danger: true },
            { icon: 'fas fa-rotate-left', text: '状态回退为未上传', warning: true }
        ]
    });
    if (!confirmed) {
        return;
    }
    if (button) {
        button.disabled = true;
        button.textContent = '删除中...';
    }
    try {
        const result = await requestPaperPdfDelete(identityKey);
        addLog(result.deleted_file ? 'PDF 已删除，状态已回退为未上传。' : 'PDF 状态已回退为未上传。');
        if (result.delete_error) {
            addLog(`PDF 文件删除提示：${result.delete_error}`, 'warning');
        }
        await refreshPdfLinkedViews();
    } catch (error) {
        addLog(`删除 PDF 失败：${error.message}`, 'error');
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = '删除 PDF';
        }
    }
}

async function requestPaperMdParse(identityKey, force = false, signal = undefined) {
    const query = force ? '?force=1' : '';
    const response = await fetch(`/api/library/papers/${encodeURIComponent(identityKey)}/parse_pdf${query}`, {
        method: 'POST',
        signal
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.error || 'Marker 解析失败');
    }
    return result;
}

async function requestPaperPdfDelete(identityKey) {
    const response = await fetch(`/api/library/papers/${encodeURIComponent(identityKey)}/delete_pdf`, {
        method: 'POST'
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.error || '删除 PDF 失败');
    }
    return result;
}

async function requestPaperMdDelete(identityKey) {
    const response = await fetch(`/api/library/papers/${encodeURIComponent(identityKey)}/delete_md`, {
        method: 'POST'
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.error || '删除 MD 失败');
    }
    return result;
}

async function deletePaperMd(identityKey, button = null) {
    if (!identityKey) return;
    const title = getPaperTitleForIdentity(identityKey);
    const confirmed = await requestDangerConfirm({
        title: '删除解析 Markdown？',
        message: '将删除该文献的本地 Markdown 缓存，并清空全文解析状态。',
        target: title,
        confirmText: '删除解析 MD',
        meta: [
            { icon: 'fas fa-file-lines', text: '删除 Markdown 缓存', danger: true },
            { icon: 'fas fa-rotate-left', text: '清空解析状态', warning: true }
        ]
    });
    if (!confirmed) {
        return;
    }
    const originalLabel = button ? button.textContent : '删除解析 MD';
    if (button) {
        button.disabled = true;
        button.textContent = '删除中...';
    }
    try {
        const result = await requestPaperMdDelete(identityKey);
        addLog(result.deleted_files ? 'MD 缓存已删除，解析状态已清空。' : 'MD 解析状态已清空。');
        if (result.delete_error) {
            addLog(`MD 文件删除提示：${result.delete_error}`, 'warning');
        }
        await refreshPdfLinkedViews();
    } catch (error) {
        addLog(`删除解析 MD 失败：${error.message}`, 'error');
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalLabel;
        }
    }
}

async function runSelectedPaperBatch(selector, label, worker, options = {}) {
    const keys = getCheckedValues(selector);
    if (keys.length === 0) {
        addLog('请先选择要处理的文献。', 'error');
        return;
    }
    if (options.confirmMessage) {
        const confirmed = await requestDangerConfirm({
            title: options.confirmTitle || `${label}？`,
            message: options.confirmMessage(keys.length),
            target: options.confirmTarget ? options.confirmTarget(keys.length) : `${keys.length} 篇已选文献`,
            confirmText: options.confirmText || '确认执行',
            meta: options.confirmMeta ? options.confirmMeta(keys.length) : []
        });
        if (!confirmed) {
            return;
        }
    }
    let success = 0;
    let failed = 0;
    addLog(`${label}开始：${keys.length} 篇。`);
    for (const key of keys) {
        try {
            await worker(key);
            success += 1;
        } catch (error) {
            failed += 1;
            addLog(`${label}失败：${key} · ${error.message}`, 'error');
        }
    }
    addLog(`${label}完成：成功 ${success} 篇，失败 ${failed} 篇。`, failed ? 'warning' : 'info');
    await refreshPdfLinkedViews();
}

async function runPaperParseBatch(selector = '.library-paper-checkbox') {
    const items = getCheckedPaperItems(selector);
    if (items.length === 0) {
        addLog('请先选择要解析的文献。', 'error');
        return;
    }
    if (!(await requestPaperMdParseConfirm('', { count: items.length, batch: true }))) {
        addLog('已取消批量 PDF 解析。', 'warning');
        return;
    }
    let success = 0;
    let failed = 0;
    openParseProgressModal(items.length);
    addLog(`批量解析 MD 开始：${items.length} 篇。`);
    for (let index = 0; index < items.length; index += 1) {
        if (paperParseProgress.cancelRequested) {
            appendParseProgressLog('已取消，停止提交剩余解析任务。', 'warning');
            break;
        }
        const item = items[index];
        updateParseProgressModal({
            total: items.length,
            current: index,
            success,
            failed,
            state: '环境预检',
            title: '正在批量解析 PDF',
            currentTitle: `${item.title} · 正在预热 Marker；如果模型缓存缺失，会在这里提前失败。`,
            stage: 'prepare'
        });
        appendParseProgressLog(`(${index + 1}/${items.length}) 环境预检：${item.title}`);
        try {
            paperParseProgress.abortController = new AbortController();
            updateParseProgressModal({
                total: items.length,
                current: index,
                success,
                failed,
                state: 'Marker 解析中',
                title: '正在批量解析 PDF',
                currentTitle: `${item.title} · Marker 正在生成 Markdown。`,
                stage: 'marker'
            });
            appendParseProgressLog(`(${index + 1}/${items.length}) 预检通过，已提交到 Marker：${item.title}`);
            const result = await requestPaperMdParse(item.identityKey, false, paperParseProgress.abortController.signal);
            success += 1;
            updateParseProgressModal({
                total: items.length,
                current: index + 1,
                success,
                failed,
                state: '切块入库',
                currentTitle: item.title,
                stage: 'chunk'
            });
            appendParseProgressLog(`解析成功：${item.title} · ${result.fulltext?.chunk_count || 0} 个片段。`, 'success');
            updateParseProgressModal({
                total: items.length,
                current: index + 1,
                success,
                failed,
                state: index + 1 === items.length ? '整理结果' : '等待下一篇',
                currentTitle: index + 1 === items.length ? '正在汇总批量解析结果...' : '准备提交下一篇文献。',
                stage: index + 1 === items.length ? 'done' : 'prepare'
            });
        } catch (error) {
            if (isParseAbortError(error)) {
                appendParseProgressLog(`已取消：${item.title}`, 'warning');
                addLog('批量解析 MD 已取消。', 'warning');
                break;
            }
            failed += 1;
            updateParseProgressModal({
                total: items.length,
                current: index + 1,
                success,
                failed,
                state: '解析中',
                currentTitle: item.title,
                stage: 'failed',
                stageDetail: error.message
            });
            appendParseProgressLog(`解析失败：${item.title} · ${error.message}`, 'error');
            addLog(`批量解析 MD 失败：${item.identityKey} · ${error.message}`, 'error');
        }
    }
    await refreshPdfLinkedViews();
    const cancelled = paperParseProgress.cancelRequested;
    finishParseProgressModal({ total: items.length, current: success + failed, success, failed, cancelled });
    addLog(cancelled ? `批量解析 MD 已取消：成功 ${success} 篇，失败 ${failed} 篇。` : `批量解析 MD 完成：成功 ${success} 篇，失败 ${failed} 篇。`, cancelled || failed ? 'warning' : 'info');
}

function batchParsePaperMds(selector = '.library-paper-checkbox') {
    runPaperParseBatch(selector);
}

function batchDeletePaperPdfs(selector = '.library-paper-checkbox') {
    runSelectedPaperBatch(selector, '批量删除 PDF', requestPaperPdfDelete, {
        confirmTitle: '批量删除 PDF？',
        confirmMessage: count => `将删除 ${count} 篇文献的本地 PDF，并回退下载状态。`,
        confirmText: '批量删除 PDF',
        confirmMeta: () => [
            { icon: 'fas fa-file-pdf', text: '删除本地 PDF', danger: true },
            { icon: 'fas fa-rotate-left', text: '回退下载状态', warning: true }
        ]
    });
}

function batchDeletePaperMds(selector = '.library-paper-checkbox') {
    runSelectedPaperBatch(selector, '批量删除解析 MD', requestPaperMdDelete, {
        confirmTitle: '批量删除解析 MD？',
        confirmMessage: count => `将删除 ${count} 篇文献的解析 Markdown 缓存，并清空解析状态。`,
        confirmText: '批量删除解析 MD',
        confirmMeta: () => [
            { icon: 'fas fa-file-lines', text: '删除 Markdown 缓存', danger: true },
            { icon: 'fas fa-rotate-left', text: '清空解析状态', warning: true }
        ]
    });
}

function triggerLibraryPdfUpload(identityKey) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf,.pdf';
    input.addEventListener('change', () => {
        const file = input.files && input.files[0];
        if (file) {
            uploadLibraryPdf(identityKey, file);
        }
    });
    input.click();
}

async function uploadLibraryPdf(identityKey, file) {
    if (!identityKey || !file) return;
    const formData = new FormData();
    formData.append('file', file);
    addLog(`开始上传 PDF：${file.name}`);
    try {
        const response = await fetch(`/api/library/papers/${encodeURIComponent(identityKey)}/upload_pdf`, {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'PDF 上传失败');
        }
        addLog('PDF 上传完成。');
    } catch (error) {
        addLog(`PDF 上传失败：${error.message}`, 'error');
    } finally {
        await refreshPdfLinkedViews();
    }
}

function toggleAllLibraryPapers(checkbox) {
    setCheckboxes('.library-paper-checkbox', Boolean(checkbox?.checked));
}

async function deleteLibraryPapers(identityKeys) {
    const keys = Array.isArray(identityKeys) ? identityKeys.filter(Boolean) : [];
    if (keys.length === 0) {
        addLog('请先选择要删除的文献。', 'error');
        return;
    }
    const confirmed = await requestDangerConfirm({
        title: '删除文献数据库记录？',
        message: `将从文献数据库删除 ${keys.length} 篇文献，关联的主题库关系也会随记录移除。`,
        target: `${keys.length} 篇已选文献`,
        confirmText: '确认删除',
        meta: [
            { icon: 'fas fa-database', text: '删除数据库记录', danger: true },
            { icon: 'fas fa-folder-minus', text: '移除主题库关联', warning: true }
        ]
    });
    if (!confirmed) {
        return;
    }
    try {
        const response = await fetch('/api/library/papers/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity_keys: keys })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '删除文献失败');
        }
        addLog(`文献数据库删除完成：${result.deleted || 0} 篇。`);
        await loadLibraryPapers(currentLibraryPage || 1);
        if (currentCollectionId) {
            await loadLibraryCollections(false);
        }
    } catch (error) {
        addLog(`删除文献失败：${error.message}`, 'error');
    }
}

function deleteSelectedLibraryPapers() {
    deleteLibraryPapers(getCheckedValues('.library-paper-checkbox'));
}

function deleteSingleLibraryPaper(identityKey) {
    deleteLibraryPapers([identityKey]);
}

async function addSelectedLibraryPapersToCollection(button = null) {
    const identityKeys = getCheckedValues('.library-paper-checkbox');
    const picker = document.getElementById('bulk-library-collection');
    const collectionId = button?.dataset?.collectionId || (picker ? picker.value : '');
    if (identityKeys.length === 0) {
        addLog('请先选择要加入文献主题库的文献。', 'error');
        return;
    }
    if (!collectionId) {
        addLog('请先选择文献主题库。', 'error');
        return;
    }
    try {
        const response = await fetch(`/api/library/collections/${encodeURIComponent(collectionId)}/papers/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity_keys: identityKeys })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '批量加入文献主题库失败');
        }
        closeCollectionChoosers();
        const collection = currentCollections.find(item => item.collection_id === collectionId);
        addLog(`批量加入文献主题库完成：${collection ? collection.name : collectionId} · 匹配 ${result.matched || 0} 篇。`);
        await loadLibraryCollections(false);
        if (currentCollectionId === collectionId) {
            await loadCollectionDetail(collectionId);
        }
    } catch (error) {
        addLog(`批量加入文献主题库失败：${error.message}`, 'error');
    }
}

function renderLibraryPaperItem(paper, result, index) {
    const itemNumber = ((result.page || 1) - 1) * (result.per_page || 20) + index + 1;
    const query = String(result.q || currentLibraryQuery || '').trim();
    const url = paper.doi ? doiToUrl(paper.doi) : (paper.url || '');
    const title = paper.title || '未命名文献';
    const titleHtml = url
        ? `<a href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">${highlightLibraryText(title, query)}</a>`
        : highlightLibraryText(title, query);
    const journal = paper.venue || '期刊信息缺失';
    const journalHtml = highlightLibraryText(journal, query);
    const citationCount = paper.citationCount !== '' && paper.citationCount !== null ? paper.citationCount : '-';
    const updatedAt = paper.last_seen_at || '-';
    const authorsHtml = highlightLibraryText(paper.authors || '作者信息缺失', query);
    const abstractText = String(paper.abstract || '暂无摘要').replace(/^abstract\s*[:：.]?\s*/i, '');
    const abstractHtml = highlightLibraryText(abstractText, query);
    const doi = paper.doi ? `<span>DOI：${highlightLibraryText(paper.doi, query)}</span>` : '';
    const identityKey = paper.identity_key || '';
    const pdfStatus = paper.download_status || 'not_downloaded';
    const pdfSource = paper.pdf_source || '';
    const pdfStatusClass = getPdfStatusClass(pdfStatus);
    const pdfStatusTitle = paper.download_error ? ` title="${escapeAttribute(paper.download_error)}"` : '';
    const parseStatus = paper.parse_status || 'not_parsed';
    const parseStatusClass = getParseStatusClass(parseStatus);
    const parseStatusTitle = paper.parse_error ? ` title="${escapeAttribute(paper.parse_error)}"` : '';
    const chunkCount = Number(paper.chunk_count || 0);
    const pageCount = Number(paper.page_count || 0);
    const parseEngine = getParseEngineLabel(paper.parse_engine);
    const parseQualityHtml = buildParseQualityHtml(paper);
    const viewPdf = pdfStatus === 'downloaded'
        ? `<a class="pdf-action-link" href="${escapeAttribute(buildPaperPdfUrl(identityKey))}" target="_blank" rel="noopener noreferrer">查看 PDF</a>`
        : '';
    const parseFullText = pdfStatus === 'downloaded'
        ? `<button type="button" class="pdf-action-button" data-identity-key="${escapeAttribute(identityKey)}" onclick="parseLibraryPdf(this.dataset.identityKey, this, ${parseStatus === 'parsed' ? 'true' : 'false'})">${parseStatus === 'parsed' ? '重新解析 MD' : '解析 MD'}</button>`
        : '';
    const uploadPdf = identityKey
        ? `<button type="button" class="pdf-action-button" data-identity-key="${escapeAttribute(identityKey)}" onclick="triggerLibraryPdfUpload(this.dataset.identityKey)">上传 PDF</button>`
        : '';
    const viewFullText = parseStatus === 'parsed'
        ? `<a class="pdf-action-link" href="${escapeAttribute(buildPaperFullTextViewUrl(identityKey))}" target="_blank" rel="noopener noreferrer">查看 MD</a>`
        : '';
    const deleteFullText = parseStatus === 'parsed' || parseStatus === 'failed'
        ? `<button type="button" class="pdf-action-button danger-action" data-identity-key="${escapeAttribute(identityKey)}" onclick="deletePaperMd(this.dataset.identityKey, this)">删除解析 MD</button>`
        : '';
    const collectionPicker = renderCollectionPicker(identityKey);
    const dataset = paper.last_dataset ? `<span>数据集：${highlightLibraryText(paper.last_dataset, query)}</span>` : '';
    const discovered = paper.discovery_count ? `<span>累计发现：${escapeHtml(paper.discovery_count)} 次</span>` : '';

    return `
        <div class="literature-item">
            <div class="literature-row-top">
                <div class="literature-number">
                    <input type="checkbox" name="library_paper_ids" class="library-paper-checkbox" value="${escapeAttribute(identityKey)}" aria-label="选择第 ${escapeAttribute(itemNumber)} 篇">
                    <span>${escapeHtml(itemNumber)}</span>
                </div>
                <div class="literature-title">${titleHtml}</div>
                <div class="literature-journal">${journalHtml}</div>
                <div class="literature-citations">${escapeHtml(citationCount)}</div>
                <div class="literature-date">${escapeHtml(updatedAt)}</div>
            </div>
            <div class="literature-authors">${authorsHtml}</div>
            <div class="literature-abstract collapsed">
                <span class="abstract-label">Abstract</span> ${abstractHtml}
            </div>
            <button type="button" class="toggle-abstract" onclick="toggleAbstract(this)">展开摘要</button>
            <div class="literature-actions">
                ${doi}
                ${discovered}
                <span class="pdf-status pdf-status-${pdfStatusClass}"${pdfStatusTitle}>${getPdfStatusLabel(pdfStatus, pdfSource)}</span>
                <span class="pdf-status pdf-status-${parseStatusClass}"${parseStatusTitle}>${getParseStatusLabel(parseStatus)}</span>
                ${pageCount ? `<span>页数：${escapeHtml(pageCount)}</span>` : ''}
                ${chunkCount ? `<span>片段：${escapeHtml(chunkCount)}</span>` : ''}
                ${parseEngine ? `<span>引擎：${escapeHtml(parseEngine)}</span>` : ''}
                ${parseQualityHtml}
                <span class="pdf-action-group">
                    ${uploadPdf}
                    ${viewPdf}
                    ${parseFullText}
                    ${viewFullText}
                    ${deleteFullText}
                </span>
                ${collectionPicker}
                <button type="button" class="pdf-action-button danger-action" data-identity-key="${escapeAttribute(identityKey)}" onclick="deleteSingleLibraryPaper(this.dataset.identityKey)">删除</button>
                ${dataset}
            </div>
        </div>
    `;
}

function renderLibraryPagination(result) {
    const pagination = document.getElementById('library-pagination');
    if (!pagination) return;
    const total = result.total || 0;
    const totalPages = result.total_pages || 1;
    const page = result.page || 1;
    if (total <= 0) {
        pagination.style.display = 'none';
        pagination.innerHTML = '';
        return;
    }
    pagination.style.display = 'flex';
    pagination.innerHTML = `
        <button type="button" class="btn btn-secondary page-btn" ${page <= 1 ? 'disabled' : ''} onclick="changeLibraryPage(-1)">上一页</button>
        <span class="page-info">第 ${escapeHtml(page)} / ${escapeHtml(totalPages)} 页，共 ${escapeHtml(total)} 篇</span>
        <button type="button" class="btn btn-secondary page-btn" ${page >= totalPages ? 'disabled' : ''} onclick="changeLibraryPage(1)">下一页</button>
    `;
}

function changeLibraryPage(delta) {
    loadLibraryPapers(Math.max(1, currentLibraryPage + delta));
}

function getLiteratureSortIndicator(field) {
    if (literatureSort.field !== field) return '▽';
    return literatureSort.direction === 'asc' ? '▲' : '▼';
}

function getLiteratureSortClass(field) {
    return literatureSort.field === field ? ' active' : '';
}

function setLiteratureSort(field) {
    if (literatureSort.field === field) {
        literatureSort.direction = literatureSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        literatureSort = { field, direction: 'desc' };
    }
    if (currentCsvPath) {
        previewCSV(currentCsvPath, 1);
    }
}

// 预览CSV文件
async function previewCSV(filePath, page = 1, options = {}) {
    try {
        currentCsvPath = filePath;
        currentCsvPage = page;
        addLog(`开始预览CSV文件: ${filePath}`);
        const params = new URLSearchParams({
            path: filePath,
            page: String(page),
            per_page: String(literaturePageSize),
        });
        if (literatureSort.field) {
            params.set('sort_by', literatureSort.field);
            params.set('sort_dir', literatureSort.direction);
        }
        const response = await fetch(`/api/preview?${params.toString()}`);
        const result = await response.json();
        addLog(`收到预览数据: ${JSON.stringify(result).substring(0, 100)}...`);
        
        if (response.ok && result.type === 'csv') {
            addLog(`CSV数据有效，包含 ${result.data ? result.data.length : 0} 条记录`);
            // 更新文献信息
            const literatureInfo = document.getElementById('literature-info');
            if (literatureInfo) {
                literatureInfo.textContent = filePath;
                addLog(`已更新文献信息`);
            } else {
                addLog(`错误：找不到文献信息元素`, 'error');
            }
            
            // 生成文献预览内容
            let html = '';
            if (result.data && result.data.length > 0) {
                html += `
                    <div class="bulk-action-bar">
                        <label class="bulk-select-control">
                            <input type="checkbox" name="select_all_csv_rows" aria-label="选择全部 CSV 文献" onchange="toggleAllCsvRows(this)">
                            <span>选择本页</span>
                        </label>
                        <button type="button" class="btn btn-secondary" onclick="importSelectedCsvRows()">选中入库</button>
                        <button type="button" class="btn btn-primary" onclick="importAllCsvRows()">整份 CSV 入库</button>
                    </div>
                    <div class="literature-table">
                        <div class="literature-table-head">
                            <div>选择</div>
                            <div>题目</div>
                            <div>期刊</div>
                            <div>
                                <button type="button" class="literature-sort-btn${getLiteratureSortClass('citationCount')}" onclick="setLiteratureSort('citationCount')" aria-label="按引用次数排序">
                                    <span>引用次数</span>
                                    <span class="sort-triangle">${getLiteratureSortIndicator('citationCount')}</span>
                                </button>
                            </div>
                            <div>
                                <button type="button" class="literature-sort-btn${getLiteratureSortClass('publicationDate')}" onclick="setLiteratureSort('publicationDate')" aria-label="按发表时间排序">
                                    <span>发表时间</span>
                                    <span class="sort-triangle">${getLiteratureSortIndicator('publicationDate')}</span>
                                </button>
                            </div>
                        </div>
                `;
                result.data.forEach((paper, index) => {
                    const title = paper.title || 'Untitled';
                    const url = paper.doi ? doiToUrl(paper.doi) : (paper.url || '');
                    const titleHtml = url
                        ? `<a href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>`
                        : escapeHtml(title);
                    const itemNumber = ((result.page || 1) - 1) * (result.per_page || literaturePageSize) + index + 1;
                    const journal = paper.venue || paper.journal || '期刊信息缺失';
                    const citationCount = paper.citationCount || paper.citationCount === 0 ? paper.citationCount : '0';
                    const publicationDate = paper.publicationDate || paper.year || '时间缺失';
                    const doi = paper.doi
                        ? `<span>DOI：${escapeHtml(paper.doi)}</span>`
                        : '';
                    const abstractText = String(paper.abstract || '暂无摘要').replace(/^abstract\s*[:：.]?\s*/i, '');
                    const rowIndex = Number.isInteger(Number(paper.__row_index)) ? Number(paper.__row_index) : itemNumber - 1;

                    html += `
                        <div class="literature-item">
                            <div class="literature-row-top">
                                <div class="literature-number">
                                    <input type="checkbox" name="csv_row_ids" class="csv-paper-checkbox" value="${escapeAttribute(rowIndex)}" aria-label="选择第 ${escapeAttribute(itemNumber)} 篇">
                                    <span>${escapeHtml(itemNumber)}</span>
                                </div>
                                <div class="literature-title">${titleHtml}</div>
                                <div class="literature-journal">${escapeHtml(journal)}</div>
                                <div class="literature-citations">${escapeHtml(citationCount)}</div>
                                <div class="literature-date">${escapeHtml(publicationDate)}</div>
                            </div>
                            <div class="literature-authors">${escapeHtml(paper.authors || '作者信息缺失')}</div>
                            <div class="literature-abstract collapsed">
                                <span class="abstract-label">Abstract</span> ${escapeHtml(abstractText)}
                            </div>
                            <button type="button" class="toggle-abstract" onclick="toggleAbstract(this)">展开摘要</button>
                            <div class="literature-actions">
                                ${doi}
                                <button type="button" class="pdf-action-button" onclick="importSingleCsvRow(${escapeAttribute(rowIndex)})">入库</button>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';
            } else {
                html = '<p>该CSV文件中没有文献数据。</p>';
            }
            
            // 更新文献预览内容
            const literatureContent = document.getElementById('literature-content');
            if (literatureContent) {
                literatureContent.innerHTML = html;
                addLog(`已更新文献预览内容`);
                renderLiteraturePagination(result);
            } else {
                addLog(`错误：找不到文献预览内容元素`, 'error');
            }
            
            if (options.activatePreview !== false) {
                showPreviewTab('literature');
            }
            addLog(`CSV文件预览完成`);
        } else {
            addLog(`预览CSV文件失败: ${result.error || '未知错误'}`, 'error');
        }
    } catch (error) {
        addLog(`预览CSV文件请求失败: ${error.message}`, 'error');
    }
}

function renderLiteraturePagination(result) {
    const pagination = document.getElementById('literature-pagination');
    if (!pagination) return;

    const total = result.total || 0;
    const page = result.page || 1;
    const totalPages = result.total_pages || 1;
    if (!currentCsvPath || total <= 0) {
        pagination.style.display = 'none';
        pagination.innerHTML = '';
        return;
    }

    pagination.style.display = 'flex';
    pagination.innerHTML = `
        <button type="button" class="btn btn-secondary page-btn" ${page <= 1 ? 'disabled' : ''} onclick="changeLiteraturePage(-1)">上一页</button>
        <span class="page-info">第 ${escapeHtml(page)} / ${escapeHtml(totalPages)} 页，共 ${escapeHtml(total)} 篇，每页最多 ${literaturePageSize} 篇</span>
        <button type="button" class="btn btn-secondary page-btn" ${page >= totalPages ? 'disabled' : ''} onclick="changeLiteraturePage(1)">下一页</button>
    `;
}

function changeLiteraturePage(delta) {
    if (!currentCsvPath) return;
    const nextPage = Math.max(1, currentCsvPage + delta);
    previewCSV(currentCsvPath, nextPage);
}

function toggleAbstract(button) {
    const abstract = button.previousElementSibling;
    if (!abstract) return;

    const collapsed = abstract.classList.toggle('collapsed');
    button.textContent = collapsed ? '展开摘要' : '收起摘要';
}

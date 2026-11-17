(function () {
    'use strict';

    const API_CHAT = '/v1/chat/completions';
    const API_MODELS = '/v1/models';
    const LS_SETTINGS = 'llm-gateway.chat.settings';
    const LS_CONVERSATIONS = 'llm-gateway.chat.conversations';
    const IDB_NAME = 'llm-gateway-chat';
    const IDB_STORE = 'conversations';
    const MAX_CONTEXT_MESSAGES = 40;
    const MAX_TITLE_LENGTH = 36;
    const MAX_INPUT_HEIGHT = 190;

    const SEND_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></svg>';
    const STOP_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';

    const state = {
        conversations: [],
        currentId: null,
        models: [],
        settings: { apiKey: '', systemPrompt: '' },
        generating: false,
        abortController: null,
        autoScroll: true,
        storeMode: 'local',
        db: null,
        persistTimer: null,
        streamTimer: null,
        streamMsg: null,
        toastTimer: null,
        authRequired: false,
    };

    const els = {};

    function $(selector, root) {
        return (root || document).querySelector(selector);
    }

    function cacheEls() {
        els.app = $('#app');
        els.sidebar = $('#sidebar');
        els.scrim = $('#scrim');
        els.conversationList = $('#conversationList');
        els.newChatBtn = $('#newChatBtn');
        els.settingsBtn = $('#settingsBtn');
        els.importBtn = $('#importBtn');
        els.importInput = $('#importInput');
        els.sidebarToggle = $('#sidebarToggle');
        els.convTitle = $('#convTitle');
        els.convSub = $('#convSub');
        els.modelPickerBtn = $('#modelPickerBtn');
        els.modelPickerValue = $('#modelPickerValue');
        els.modelOptions = $('#modelOptions');
        els.systemPromptBtn = $('#systemPromptBtn');
        els.exportBtn = $('#exportBtn');
        els.messages = $('#messages');
        els.messageInput = $('#messageInput');
        els.sendBtn = $('#sendBtn');
        els.composerHint = $('#composerHint');
        els.thinkingToggle = $('#thinkingToggle');
        els.settingsModal = $('#settingsModal');
        els.settingsApiKey = $('#settingsApiKey');
        els.settingsModel = $('#settingsModel');
        els.settingsPrompt = $('#settingsPrompt');
        els.settingsBase = $('#settingsBase');
        els.settingsSave = $('#settingsSave');
        els.settingsCancel = $('#settingsCancel');
        els.settingsClose = $('#settingsClose');
        els.modelConfigModal = $('#modelConfigModal');
        els.providerCombo = $('#providerCombo');
        els.providerField = $('#providerField');
        els.providerList = $('#providerList');
        els.modelCombo = $('#modelCombo');
        els.modelField = $('#modelField');
        els.modelFieldList = $('#modelFieldList');
        els.modelFieldHint = $('#modelFieldHint');
        els.paramTemperature = $('#paramTemperature');
        els.paramTopP = $('#paramTopP');
        els.paramTopK = $('#paramTopK');
        els.paramMaxTokens = $('#paramMaxTokens');
        els.modelConfigSave = $('#modelConfigSave');
        els.modelConfigCancel = $('#modelConfigCancel');
        els.modelConfigClose = $('#modelConfigClose');
        els.toast = $('#toast');
    }

    // ============ 基础工具 ============

    function now() {
        return Date.now();
    }

    function uid() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }
        return 'c_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
    }

    function withTimeout(promise, ms, label) {
        return Promise.race([
            promise,
            new Promise(function (resolve, reject) {
                setTimeout(function () { reject(new Error(label || 'timeout')); }, ms);
            }),
        ]);
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function makeTitle(text) {
        const flat = String(text || '').replace(/\s+/g, ' ').trim();
        if (!flat) return '新对话';
        return flat.length > MAX_TITLE_LENGTH ? flat.slice(0, MAX_TITLE_LENGTH) + '…' : flat;
    }

    function formatTime(timestamp) {
        const date = new Date(timestamp || now());
        if (Number.isNaN(date.getTime())) return '';
        const today = new Date();
        const sameDay = date.getFullYear() === today.getFullYear()
            && date.getMonth() === today.getMonth()
            && date.getDate() === today.getDate();
        if (sameDay) {
            return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
        }
        if (date.getFullYear() === today.getFullYear()) {
            return (date.getMonth() + 1) + '月' + date.getDate() + '日';
        }
        return date.getFullYear() + '/' + (date.getMonth() + 1) + '/' + date.getDate();
    }

    function formatUsage(usage) {
        if (!usage || typeof usage !== 'object') return '';
        const input = usage.prompt_tokens != null ? usage.prompt_tokens
            : (usage.input_tokens != null ? usage.input_tokens : 0);
        const output = usage.completion_tokens != null ? usage.completion_tokens
            : (usage.output_tokens != null ? usage.output_tokens : 0);
        return '输入 ' + input + ' · 输出 ' + output;
    }

    function currentConversation() {
        return state.conversations.find(function (item) { return item.id === state.currentId; }) || null;
    }

    function previewOf(conv) {
        for (let i = conv.messages.length - 1; i >= 0; i -= 1) {
            const msg = conv.messages[i];
            if (msg.role === 'assistant' && msg.status === 'streaming') return '正在生成…';
            if (msg.content) {
                return String(msg.content).replace(/\s+/g, ' ').trim().slice(0, 72);
            }
        }
        return '还没有消息';
    }

    function showToast(message, ok) {
        if (!els.toast) return;
        const text = String(message || '');
        els.toast.textContent = text;
        els.toast.classList.toggle('error', ok === false);
        els.toast.classList.add('show');
        clearTimeout(state.toastTimer);
        state.toastTimer = setTimeout(function () {
            els.toast.classList.remove('show');
        }, 2800);
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast('已复制');
            return;
        } catch (err) {
            // fall through
        }
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        try {
            document.execCommand('copy');
            showToast('已复制');
        } catch (err) {
            showToast('复制失败，请手动选择文本', false);
        } finally {
            area.remove();
        }
    }

    // ============ 本地存储 ============

    function loadSettings() {
        try {
            const raw = JSON.parse(localStorage.getItem(LS_SETTINGS) || '{}');
            state.settings.apiKey = typeof raw.apiKey === 'string' ? raw.apiKey : '';
            state.settings.systemPrompt = typeof raw.systemPrompt === 'string' ? raw.systemPrompt : '';
        } catch (err) {
            state.settings = { apiKey: '', systemPrompt: '' };
        }
    }

    function saveSettingsToDisk() {
        try {
            localStorage.setItem(LS_SETTINGS, JSON.stringify(state.settings));
        } catch (err) {
            showToast('无法写入本地设置：浏览器存储空间可能已满', false);
        }
    }

    function openDb() {
        return new Promise(function (resolve, reject) {
            if (!('indexedDB' in window)) {
                reject(new Error('indexedDB unavailable'));
                return;
            }
            const request = indexedDB.open(IDB_NAME, 1);
            request.onupgradeneeded = function () {
                const db = request.result;
                if (!db.objectStoreNames.contains(IDB_STORE)) {
                    db.createObjectStore(IDB_STORE, { keyPath: 'id' });
                }
            };
            request.onsuccess = function () { resolve(request.result); };
            request.onerror = function () { reject(request.error || new Error('indexedDB error')); };
        });
    }

    function idbGetAll() {
        return new Promise(function (resolve, reject) {
            const tx = state.db.transaction(IDB_STORE, 'readonly');
            const request = tx.objectStore(IDB_STORE).getAll();
            request.onsuccess = function () { resolve(request.result || []); };
            request.onerror = function () { reject(request.error); };
        });
    }

    function idbPut(conv) {
        return new Promise(function (resolve, reject) {
            const tx = state.db.transaction(IDB_STORE, 'readwrite');
            tx.objectStore(IDB_STORE).put(conv);
            tx.oncomplete = function () { resolve(); };
            tx.onerror = function () { reject(tx.error); };
        });
    }

    function idbDelete(id) {
        return new Promise(function (resolve, reject) {
            const tx = state.db.transaction(IDB_STORE, 'readwrite');
            tx.objectStore(IDB_STORE).delete(id);
            tx.oncomplete = function () { resolve(); };
            tx.onerror = function () { reject(tx.error); };
        });
    }

    function loadLocalConversations() {
        try {
            const raw = JSON.parse(localStorage.getItem(LS_CONVERSATIONS) || '[]');
            return Array.isArray(raw) ? raw : [];
        } catch (err) {
            return [];
        }
    }

    function persistLocalAll() {
        try {
            localStorage.setItem(LS_CONVERSATIONS, JSON.stringify(state.conversations));
        } catch (err) {
            showToast('本地会话保存失败：浏览器存储空间可能已满', false);
        }
    }

    function normalizeMessage(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const role = raw.role === 'user' || raw.role === 'assistant' ? raw.role : '';
        if (!role) return null;
        return {
            id: raw.id || uid(),
            role: role,
            content: typeof raw.content === 'string' ? raw.content : '',
            reasoning: typeof raw.reasoning === 'string' ? raw.reasoning : '',
            createdAt: raw.createdAt || now(),
            status: raw.status || (role === 'assistant' ? 'done' : undefined),
            usage: raw.usage || null,
            error: raw.error || '',
        };
    }

    function optionalNumber(value) {
        if (value === null || value === undefined || value === '') return null;
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    }

    function normalizeParams(raw) {
        const source = raw && typeof raw === 'object' ? raw : {};
        return {
            temperature: optionalNumber(source.temperature),
            topP: optionalNumber(source.topP != null ? source.topP : source.top_p),
            topK: optionalNumber(source.topK != null ? source.topK : source.top_k),
            maxTokens: optionalNumber(source.maxTokens != null ? source.maxTokens : source.max_tokens),
        };
    }

    function normalizeConversation(raw) {
        if (!raw || typeof raw !== 'object') return null;
        return {
            id: raw.id || uid(),
            title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : '新对话',
            createdAt: raw.createdAt || now(),
            updatedAt: raw.updatedAt || raw.createdAt || now(),
            model: typeof raw.model === 'string' ? raw.model : '',
            provider: typeof raw.provider === 'string' ? raw.provider : '',
            asyncType: typeof raw.asyncType === 'string' ? raw.asyncType : '',
            params: normalizeParams(raw.params),
            thinking: raw.thinking === true,
            systemPrompt: typeof raw.systemPrompt === 'string' ? raw.systemPrompt
                : (typeof raw.system_prompt === 'string' ? raw.system_prompt : ''),
            messages: Array.isArray(raw.messages) ? raw.messages.map(normalizeMessage).filter(Boolean) : [],
        };
    }

    async function initStore() {
        try {
            state.db = await withTimeout(openDb(), 1200, 'indexedDB open timeout');
            state.storeMode = 'idb';
        } catch (err) {
            state.db = null;
            state.storeMode = 'local';
        }
    }

    async function loadConversations() {
        let rawList = [];
        if (state.storeMode === 'idb') {
            try {
                rawList = await withTimeout(idbGetAll(), 1200, 'indexedDB read timeout');
            } catch (err) {
                state.storeMode = 'local';
                rawList = loadLocalConversations();
            }
        } else {
            rawList = loadLocalConversations();
        }
        state.conversations = rawList.map(normalizeConversation).filter(Boolean);
        state.conversations.sort(function (a, b) { return b.updatedAt - a.updatedAt; });
    }

    async function persist(conv) {
        if (!conv) return;
        conv.updatedAt = conv.updatedAt || now();
        const index = state.conversations.findIndex(function (item) { return item.id === conv.id; });
        if (index >= 0) state.conversations[index] = conv;
        else state.conversations.unshift(conv);

        if (state.storeMode === 'idb' && state.db) {
            try {
                await withTimeout(idbPut(conv), 1200, 'indexedDB write timeout');
                return;
            } catch (err) {
                state.storeMode = 'local';
            }
        }
        persistLocalAll();
    }

    function schedulePersist(conv, immediate) {
        if (!conv) return;
        if (immediate) {
            clearTimeout(state.persistTimer);
            state.persistTimer = null;
            persist(conv);
            return;
        }
        clearTimeout(state.persistTimer);
        state.persistTimer = setTimeout(function () {
            state.persistTimer = null;
            persist(conv);
        }, 260);
    }

    // ============ 会话与渲染 ============

    function createConversation() {
        const firstModel = state.models[0] || null;
        const conv = {
            id: uid(),
            title: '新对话',
            createdAt: now(),
            updatedAt: now(),
            model: firstModel ? firstModel.id : '',
            provider: firstModel ? (providersOfModel(firstModel)[0] || '') : '',
            asyncType: firstModel ? (firstModel.x_async_type || '') : '',
            params: normalizeParams(null),
            thinking: false,
            systemPrompt: state.settings.systemPrompt || '',
            messages: [],
        };
        state.conversations.unshift(conv);
        state.currentId = conv.id;
        persist(conv);
        return conv;
    }

    function ensureConversation() {
        return currentConversation() || createConversation();
    }

    function selectConversation(id) {
        if (state.generating) {
            showToast('请先停止当前回复', false);
            return;
        }
        const conv = state.conversations.find(function (item) { return item.id === id; });
        if (!conv) return;
        state.currentId = id;
        state.autoScroll = true;
        renderAll();
        closeSidebar();
        els.messageInput.focus();
    }

    function renderAll() {
        renderList();
        renderHeader();
        renderMessages();
        updateComposer();
        updateModelPicker();
        updateThinkingToggle();
    }

    function renderHeader() {
        const conv = currentConversation();
        if (!conv) {
            els.convTitle.textContent = '新对话';
            els.convSub.textContent = '本地保存';
            return;
        }
        els.convTitle.textContent = conv.title || '新对话';
        const userCount = conv.messages.filter(function (msg) { return msg.role === 'user'; }).length;
        const model = conv.model || '未选择模型';
        const provider = conv.provider ? ' · ' + conv.provider : '';
        const cluster = conv.asyncType ? ' · ' + conv.asyncType : '';
        const status = state.generating ? '正在生成' : '本地保存';
        els.convSub.textContent = model + provider + cluster + ' · ' + userCount + ' 条消息 · ' + status;
    }

    function renderList() {
        els.conversationList.innerHTML = '';
        if (!state.conversations.length) {
            const empty = document.createElement('div');
            empty.className = 'conv-empty';
            empty.textContent = '还没有会话，点击上方「新对话」开始。';
            els.conversationList.appendChild(empty);
            return;
        }

        state.conversations.slice().sort(function (a, b) {
            return b.updatedAt - a.updatedAt;
        }).forEach(function (conv) {
            const item = document.createElement('div');
            item.className = 'conv-item' + (conv.id === state.currentId ? ' active' : '');
            item.tabIndex = 0;
            item.setAttribute('role', 'button');
            item.setAttribute('aria-label', '打开会话 ' + conv.title);
            item.addEventListener('click', function () { selectConversation(conv.id); });
            item.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectConversation(conv.id);
                }
            });

            const row = document.createElement('div');
            row.className = 'conv-row';

            const title = document.createElement('div');
            title.className = 'conv-title';
            title.textContent = conv.title || '新对话';

            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'conv-del';
            del.title = '删除会话';
            del.setAttribute('aria-label', '删除会话 ' + conv.title);
            del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>';
            del.addEventListener('click', function (event) {
                event.stopPropagation();
                deleteConversation(conv.id);
            });

            row.appendChild(title);
            row.appendChild(del);

            const preview = document.createElement('div');
            preview.className = 'conv-preview';
            preview.textContent = previewOf(conv);

            const time = document.createElement('div');
            time.className = 'conv-time';
            time.textContent = formatTime(conv.updatedAt);

            item.appendChild(row);
            item.appendChild(preview);
            item.appendChild(time);
            els.conversationList.appendChild(item);
        });
    }

    function renderMessages() {
        const conv = currentConversation();
        els.messages.innerHTML = '';
        if (!conv || !conv.messages.length) {
            els.messages.appendChild(buildEmptyState());
            return;
        }
        conv.messages.forEach(function (msg) {
            els.messages.appendChild(buildMessageEl(msg, conv));
        });
        if (state.autoScroll) {
            requestAnimationFrame(function () { scrollToBottom(true); });
        }
    }

    function buildEmptyState() {
        const wrap = document.createElement('div');
        wrap.className = 'empty-state';

        const mark = document.createElement('div');
        mark.className = 'empty-mark';
        mark.textContent = 'S';

        const title = document.createElement('h1');
        title.textContent = '开始一段对话';

        const desc = document.createElement('p');
        desc.textContent = '消息只保存在当前浏览器。选择一个模型，直接输入即可。切换会话不会上传聊天记录。';

        const grid = document.createElement('div');
        grid.className = 'prompt-grid';

        const prompts = [
            ['解释一段代码', '请逐行解释下面这段代码，并指出潜在问题：\n\n'],
            ['写一封邮件', '帮我写一封简洁、专业的邮件，主题是：\n\n'],
            ['拆解一个需求', '请把下面这个需求拆解成可执行的开发任务，并标注优先级：\n\n'],
            ['总结一段文字', '请用要点总结下面这段内容，并给出三条关键结论：\n\n'],
        ];
        prompts.forEach(function (pair) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'prompt-card';
            button.textContent = pair[0];
            button.addEventListener('click', function () {
                els.messageInput.value = window.I18N ? window.I18N.t(pair[1]) : pair[1];
                autoResize();
                els.messageInput.focus();
                els.messageInput.setSelectionRange(els.messageInput.value.length, els.messageInput.value.length);
            });
            grid.appendChild(button);
        });

        wrap.appendChild(mark);
        wrap.appendChild(title);
        wrap.appendChild(desc);
        wrap.appendChild(grid);

        if (!state.models.length) {
            const hint = document.createElement('div');
            hint.className = 'model-hint';
            hint.textContent = state.authRequired
                ? '未加载到模型：当前网关要求项目 Token，请在「设置」中填写 sk-gw- 密钥。'
                : '未加载到模型：请先在管理台添加并启用模型；如果网关开启了项目 Token 校验，请在「设置」中填写密钥。';
            wrap.appendChild(hint);
        }

        return wrap;
    }

    function buildMessageEl(msg, conv) {
        const row = document.createElement('div');
        row.className = 'msg ' + msg.role;
        row.dataset.id = msg.id;

        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = msg.role === 'user' ? '你' : 'AI';

        const body = document.createElement('div');
        body.className = 'msg-body';

        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        meta.textContent = metaText(msg);

        const content = document.createElement('div');
        content.className = 'msg-content';
        // Message bodies are user/model content: never translate them.
        content.setAttribute('data-no-i18n', '');
        if (msg.role === 'assistant') {
            content.innerHTML = assistantHtml(msg);
        } else {
            content.textContent = msg.content || '';
        }

        const actions = document.createElement('div');
        actions.className = 'msg-actions';

        const copy = document.createElement('button');
        copy.type = 'button';
        copy.className = 'msg-action';
        copy.dataset.action = 'copy';
        copy.dataset.id = msg.id;
        copy.textContent = '复制';
        actions.appendChild(copy);

        const isLastAssistant = msg.role === 'assistant'
            && conv.messages[conv.messages.length - 1]
            && conv.messages[conv.messages.length - 1].id === msg.id;
        if (isLastAssistant) {
            const regen = document.createElement('button');
            regen.type = 'button';
            regen.className = 'msg-action';
            regen.dataset.action = 'regenerate';
            regen.dataset.id = msg.id;
            regen.textContent = '重新生成';
            actions.appendChild(regen);
        }

        body.appendChild(meta);
        body.appendChild(content);
        body.appendChild(actions);
        row.appendChild(avatar);
        row.appendChild(body);
        return row;
    }

    function metaText(msg) {
        const tr = window.I18N ? window.I18N.t : function (s) { return s; };
        const parts = [tr(msg.role === 'user' ? '你' : '助手'), formatTime(msg.createdAt)];
        const usage = formatUsage(msg.usage);
        if (usage) parts.push(tr(usage));
        if (msg.status === 'stopped') parts.push(tr('已停止'));
        if (msg.status === 'error') parts.push(tr('失败'));
        return parts.join(' · ');
    }

    function assistantHtml(msg) {
        const parts = [];
        if (msg.reasoning) {
            parts.push(
                '<details class="reasoning"' + (!msg.content ? ' open' : '') + '>' +
                '<summary>' + (window.I18N ? window.I18N.t('思考过程') : '思考过程') + '</summary><pre>' +
            escapeHtml(msg.reasoning) + '</pre></details>'
            );
        }
        if (msg.content) {
            parts.push(renderMarkdown(msg.content));
        } else if (msg.status === 'streaming') {
            parts.push('<div class="typing"><span></span><span></span><span></span></div>');
        }
        if (msg.status === 'streaming' && msg.content) {
            parts.push('<span class="stream-caret"></span>');
        }
        if (msg.error) {
            parts.push('<div class="msg-error">' + escapeHtml(msg.error) + '</div>');
        }
        if (msg.status === 'stopped' && msg.content) {
            parts.push('<div class="msg-note">已停止生成</div>');
        }
        return parts.join('');
    }

    function updateAssistantEl(msg) {
        const row = els.messages.querySelector('.msg[data-id="' + msg.id + '"]');
        if (!row) {
            renderMessages();
            return;
        }
        const content = row.querySelector('.msg-content');
        if (content) content.innerHTML = assistantHtml(msg);
        const meta = row.querySelector('.msg-meta');
        if (meta) meta.textContent = metaText(msg);
    }

    function scrollToBottom(force) {
        if (!force && !state.autoScroll) return;
        els.messages.scrollTop = els.messages.scrollHeight;
    }

    function updateComposer() {
        els.sendBtn.classList.toggle('stop', state.generating);
        els.sendBtn.innerHTML = state.generating ? STOP_SVG : SEND_SVG;
        els.sendBtn.title = state.generating ? '停止生成' : '发送';
        els.sendBtn.setAttribute('aria-label', state.generating ? '停止生成' : '发送');
        els.composerHint.textContent = state.generating ? '正在生成… 点击方块停止' : '消息仅保存在本机';
    }

    function autoResize() {
        els.messageInput.style.height = 'auto';
        els.messageInput.style.height = Math.min(els.messageInput.scrollHeight, MAX_INPUT_HEIGHT) + 'px';
    }

    // ============ 模型 ============

    function modelLabel(model) {
        const cluster = model.x_async_type ? ' · ' + model.x_async_type : '';
        const owner = model.owned_by ? ' · ' + model.owned_by : '';
        return model.id + cluster + owner;
    }

    function renderModelOptions() {
        els.modelOptions.innerHTML = state.models.map(function (model) {
            return '<option value="' + escapeHtml(model.id) + '" label="' + escapeHtml(modelLabel(model)) + '"></option>';
        }).join('');
    }

    function providersOfModel(model) {
        if (!model) return [];
        if (Array.isArray(model.x_providers) && model.x_providers.length) {
            return model.x_providers.filter(Boolean);
        }
        return model.owned_by ? [model.owned_by] : [];
    }

    function findModel(modelId) {
        return state.models.find(function (model) { return model.id === modelId; }) || null;
    }

    function resolveCluster(modelId) {
        const found = findModel(modelId);
        return found ? (found.x_async_type || '') : '';
    }

    function providerForModel(modelId, preferred) {
        const list = providersOfModel(findModel(modelId));
        if (preferred && list.indexOf(preferred) >= 0) return preferred;
        return list[0] || preferred || '';
    }

    function allProviders(keyword) {
        const term = String(keyword || '').trim().toLowerCase();
        const set = new Set();
        state.models.forEach(function (model) {
            providersOfModel(model).forEach(function (name) { set.add(name); });
        });
        return Array.from(set).filter(function (name) {
            return !term || name.toLowerCase().indexOf(term) >= 0;
        }).sort(function (a, b) { return a.localeCompare(b); });
    }

    function modelsFor(provider, keyword) {
        const term = String(keyword || '').trim().toLowerCase();
        return state.models.filter(function (model) {
            if (provider && providersOfModel(model).indexOf(provider) < 0) return false;
            return !term || model.id.toLowerCase().indexOf(term) >= 0;
        });
    }

    function updateModelPicker() {
        const conv = currentConversation();
        const name = conv && conv.model ? conv.model : '';
        els.modelPickerValue.textContent = name || '选择模型';
        els.modelPickerValue.classList.toggle('is-empty', !name);
        els.modelPickerBtn.title = name ? '模型：' + name : '选择模型与参数';
    }

    function updateThinkingToggle() {
        const conv = currentConversation();
        els.thinkingToggle.checked = !!(conv && conv.thinking);
    }

    async function loadModels() {
        const headers = {};
        if (state.settings.apiKey) headers.Authorization = 'Bearer ' + state.settings.apiKey;
        try {
            const res = await fetch(API_MODELS, { headers: headers, cache: 'no-store' });
            if (!res.ok) {
                state.models = [];
                if (res.status === 401) {
                    state.authRequired = true;
                    if (state.settings.apiKey) showToast('API Key 无效或已过期', false);
                }
                renderModelOptions();
                updateModelPicker();
                return;
            }
            const data = await res.json();
            state.models = Array.isArray(data.data) ? data.data : [];
            state.authRequired = false;
        } catch (err) {
            state.models = [];
        }
        renderModelOptions();

        const conv = currentConversation();
        if (conv && !conv.model && state.models[0]) {
            const first = state.models[0];
            conv.model = first.id;
            conv.provider = providersOfModel(first)[0] || '';
            conv.asyncType = first.x_async_type || '';
            schedulePersist(conv, true);
        }
        updateModelPicker();
    }

    // ---- 模型配置弹窗 ----
    function setComboOpen(combo, listEl, open) {
        combo.classList.toggle('open', open);
        listEl.setAttribute('aria-hidden', open ? 'false' : 'true');
    }

    function renderProviderList(keyword) {
        const providers = allProviders(keyword);
        if (!providers.length) {
            els.providerList.innerHTML = '<div class="combo-empty">暂无可用运营商</div>';
            return;
        }
        els.providerList.innerHTML = providers.map(function (name) {
            const count = modelsFor(name, '').length;
            return '<div class="combo-item" role="option" data-provider="' + escapeHtml(name) + '">'
                + '<strong>' + escapeHtml(name) + '</strong>'
                + '<span class="ci-meta">' + count + ' 个模型</span></div>';
        }).join('');
    }

    function updateModelFieldHint() {
        const provider = els.providerField.value.trim();
        if (!state.models.length) {
            els.modelFieldHint.textContent = '暂无可用模型，请先在管理台启用文本模型';
            return;
        }
        const count = modelsFor(provider, '').length;
        els.modelFieldHint.textContent = provider
            ? '运营商「' + provider + '」下可用 ' + count + ' 个模型，也可直接输入模型名'
            : '未限定运营商，共 ' + state.models.length + ' 个可用模型';
    }

    function renderModelFieldList(keyword) {
        const provider = els.providerField.value.trim();
        const list = modelsFor(provider, keyword);
        if (!list.length) {
            els.modelFieldList.innerHTML = '<div class="combo-empty">'
                + (state.models.length ? '该运营商下没有匹配的模型' : '暂无可用模型') + '</div>';
            updateModelFieldHint();
            return;
        }
        els.modelFieldList.innerHTML = list.map(function (model) {
            const clusters = (model.x_clusters || []).join(' / ');
            return '<div class="combo-item" role="option" data-model="' + escapeHtml(model.id) + '">'
                + '<span>' + escapeHtml(model.id) + '</span>'
                + '<span class="ci-meta">' + escapeHtml(clusters) + '</span></div>';
        }).join('');
        updateModelFieldHint();
    }

    function syncSamplingConflict() {
        const tempEl = els.paramTemperature;
        const topPEl = els.paramTopP;
        tempEl.disabled = false;
        topPEl.disabled = false;
        if (tempEl.value.trim()) {
            topPEl.value = '';
            topPEl.disabled = true;
        } else if (topPEl.value.trim()) {
            tempEl.value = '';
            tempEl.disabled = true;
        }
    }

    function onSamplingInput(source) {
        const tempEl = els.paramTemperature;
        const topPEl = els.paramTopP;
        if (source === 'temperature') {
            if (tempEl.value.trim()) {
                topPEl.value = '';
                topPEl.disabled = true;
            } else {
                topPEl.disabled = false;
            }
        } else if (topPEl.value.trim()) {
            tempEl.value = '';
            tempEl.disabled = true;
        } else {
            tempEl.disabled = false;
        }
    }

    function paramInputValue(el) {
        const raw = el.value.trim();
        return raw ? Number(raw) : null;
    }

    function readParamsFromForm() {
        const temperature = paramInputValue(els.paramTemperature);
        const topP = paramInputValue(els.paramTopP);
        const topK = paramInputValue(els.paramTopK);
        const maxTokens = paramInputValue(els.paramMaxTokens);
        if (temperature !== null && (isNaN(temperature) || temperature < 0 || temperature > 2)) {
            showToast('temperature 需在 0 ~ 2 之间', false);
            return null;
        }
        if (topP !== null && (isNaN(topP) || topP < 0 || topP > 1)) {
            showToast('top_p 需在 0 ~ 1 之间', false);
            return null;
        }
        if (topK !== null && (!Number.isInteger(topK) || topK < 1)) {
            showToast('top_k 需为正整数', false);
            return null;
        }
        if (maxTokens !== null && (!Number.isInteger(maxTokens) || maxTokens < 1)) {
            showToast('max_tokens 需为正整数', false);
            return null;
        }
        if (temperature !== null && topP !== null) {
            showToast('temperature 与 top_p 只能填写一个', false);
            return null;
        }
        return { temperature: temperature, topP: topP, topK: topK, maxTokens: maxTokens };
    }

    function openModelConfig() {
        const conv = ensureConversation();
        const provider = conv.provider || providerForModel(conv.model);
        els.providerField.value = provider;
        els.modelField.value = conv.model || '';
        const params = normalizeParams(conv.params);
        els.paramTemperature.value = params.temperature !== null ? params.temperature : '';
        els.paramTopP.value = params.topP !== null ? params.topP : '';
        els.paramTopK.value = params.topK !== null ? params.topK : '';
        els.paramMaxTokens.value = params.maxTokens !== null ? params.maxTokens : '';
        syncSamplingConflict();
        renderProviderList('');
        renderModelFieldList('');
        setComboOpen(els.providerCombo, els.providerList, false);
        setComboOpen(els.modelCombo, els.modelFieldList, false);
        els.modelConfigModal.classList.add('active');
        setTimeout(function () { els.modelConfigClose.focus(); }, 60);
    }

    function closeModelConfig() {
        const wasActive = els.modelConfigModal.classList.contains('active');
        els.modelConfigModal.classList.remove('active');
        setComboOpen(els.providerCombo, els.providerList, false);
        setComboOpen(els.modelCombo, els.modelFieldList, false);
        if (wasActive) els.modelPickerBtn.focus();
    }

    function applyModelConfig() {
        const conv = ensureConversation();
        const model = els.modelField.value.trim();
        if (!model) {
            showToast('请选择或输入模型', false);
            els.modelField.focus();
            return;
        }
        const params = readParamsFromForm();
        if (!params) return;
        const provider = els.providerField.value.trim();
        conv.model = model;
        conv.provider = providerForModel(model, provider);
        conv.asyncType = resolveCluster(model);
        conv.params = params;
        conv.updatedAt = now();
        schedulePersist(conv, true);
        renderAll();
        closeModelConfig();
        showToast('模型配置已应用');
    }

    // ============ Markdown ============

    function renderInline(raw) {
        let text = escapeHtml(raw);
        const codes = [];
        text = text.replace(/`([^`\n]+)`/g, function (match, code) {
            const index = codes.length;
            codes.push('<code>' + code + '</code>');
            return '%%CODE' + index + '%%';
        });
        text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
        text = text.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
        );
        text = text.replace(/%%CODE(\d+)%%/g, function (match, index) {
            return codes[Number(index)] || '';
        });
        return text;
    }

    function renderMarkdown(source) {
        const lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
        const html = [];
        let index = 0;
        let listType = null;
        let listItems = [];

        function flushList() {
            if (!listType) return;
            html.push('<' + listType + '>' + listItems.join('') + '</' + listType + '>');
            listType = null;
            listItems = [];
        }

        while (index < lines.length) {
            const line = lines[index];

            if (/^\s*```/.test(line)) {
                flushList();
                const lang = line.trim().slice(3).trim().split(/\s+/)[0] || 'code';
                const codeLines = [];
                index += 1;
                while (index < lines.length && !/^\s*```/.test(lines[index])) {
                    codeLines.push(lines[index]);
                    index += 1;
                }
                if (index < lines.length) index += 1;
                html.push(
                    '<div class="code-block"><div class="code-head"><span>' + escapeHtml(lang) +
                    '</span><button type="button" class="code-copy">' +
            (window.I18N ? window.I18N.t('复制') : '复制') + '</button></div>' +
                    '<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre></div>'
                );
                continue;
            }

            if (!line.trim()) {
                flushList();
                index += 1;
                continue;
            }

            const heading = line.match(/^(#{1,6})\s+(.*)$/);
            if (heading) {
                flushList();
                const level = heading[1].length;
                html.push('<h' + level + '>' + renderInline(heading[2]) + '</h' + level + '>');
                index += 1;
                continue;
            }

            const unordered = line.match(/^\s*[-*+]\s+(.*)$/);
            const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
            if (unordered || ordered) {
                const type = unordered ? 'ul' : 'ol';
                if (listType !== type) {
                    flushList();
                    listType = type;
                }
                listItems.push('<li>' + renderInline((unordered || ordered)[1]) + '</li>');
                index += 1;
                continue;
            }

            const quote = line.match(/^\s*>\s?(.*)$/);
            if (quote) {
                flushList();
                html.push('<blockquote>' + renderInline(quote[1]) + '</blockquote>');
                index += 1;
                continue;
            }

            flushList();
            const paragraph = [line];
            index += 1;
            while (index < lines.length && lines[index].trim()
                && !/^\s*```/.test(lines[index])
                && !/^(#{1,6})\s+/.test(lines[index])
                && !/^\s*[-*+]\s+/.test(lines[index])
                && !/^\s*\d+[.)]\s+/.test(lines[index])
                && !/^\s*>\s?/.test(lines[index])) {
                paragraph.push(lines[index]);
                index += 1;
            }
            html.push('<p>' + renderInline(paragraph.join('\n')).replace(/\n/g, '<br>') + '</p>');
        }

        flushList();
        return html.join('');
    }

    // ============ 发送与流式 ============

    function buildMessages(conv) {
        const messages = [];
        const system = String(conv.systemPrompt || '').trim();
        if (system) messages.push({ role: 'system', content: system });
        const history = conv.messages.filter(function (msg) {
            if (msg.role === 'user') return true;
            return msg.role === 'assistant' && msg.content && msg.status !== 'error';
        });
        history.slice(-MAX_CONTEXT_MESSAGES).forEach(function (msg) {
            messages.push({ role: msg.role, content: msg.content });
        });
        return messages;
    }

    async function sendFromComposer() {
        if (state.generating) {
            stopGeneration();
            return;
        }
        const text = els.messageInput.value.trim();
        if (!text) return;

        const conv = ensureConversation();
        const model = (conv.model || '').trim();
        if (!model) {
            showToast('请先选择模型', false);
            openModelConfig();
            return;
        }
        conv.model = model;
        conv.asyncType = resolveCluster(model);

        const userMessage = {
            id: uid(),
            role: 'user',
            content: text,
            createdAt: now(),
        };
        conv.messages.push(userMessage);
        if (!conv.title || conv.title === '新对话') {
            conv.title = makeTitle(text);
        }
        conv.updatedAt = now();

        els.messageInput.value = '';
        autoResize();
        await persist(conv);
        renderAll();
        scrollToBottom(true);
        await runCompletion(conv);
    }

    async function runCompletion(conv) {
        if (state.generating) return;
        const model = (conv.model || '').trim();
        if (!model) {
            showToast('请先选择模型', false);
            openModelConfig();
            return;
        }
        const payloadMessages = buildMessages(conv);
        if (!payloadMessages.some(function (msg) { return msg.role === 'user'; })) return;

        const assistant = {
            id: uid(),
            role: 'assistant',
            content: '',
            reasoning: '',
            createdAt: now(),
            status: 'streaming',
            usage: null,
            error: '',
        };
        conv.messages.push(assistant);
        conv.updatedAt = now();
        state.generating = true;
        state.autoScroll = true;
        state.abortController = new AbortController();
        updateComposer();
        renderAll();
        scrollToBottom(true);

        const headers = { 'Content-Type': 'application/json' };
        if (state.settings.apiKey) headers.Authorization = 'Bearer ' + state.settings.apiKey;
        if (conv.asyncType) headers['X-Async-Type'] = conv.asyncType;
        headers['X-Thinking'] = conv.thinking ? '1' : '0';
        headers['X-User-Id'] = 'local-chat';
        headers['X-Feature-Code'] = 'chat_ui';
        headers['X-Session-Id'] = conv.id;

        const params = normalizeParams(conv.params);
        const payload = {
            model: model,
            messages: payloadMessages,
            stream: true,
        };
        if (params.temperature !== null) payload.temperature = params.temperature;
        if (params.topP !== null) payload.top_p = params.topP;
        if (params.topK !== null) payload.top_k = params.topK;
        if (params.maxTokens !== null) payload.max_tokens = params.maxTokens;

        try {
            const response = await fetch(API_CHAT, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload),
                signal: state.abortController.signal,
            });

            if (!response.ok) {
                if (response.status === 401) openSettings();
                throw new Error(await readError(response));
            }

            const contentType = response.headers.get('content-type') || '';
            if (response.body && contentType.indexOf('text/event-stream') >= 0) {
                await consumeSSE(response, assistant);
            } else {
                const data = await response.json();
                const choice = data && data.choices && data.choices[0];
                if (choice && choice.message) {
                    assistant.content = choice.message.content || '';
                    assistant.reasoning = choice.message.reasoning_content || '';
                } else if (choice && choice.delta) {
                    assistant.content = choice.delta.content || '';
                }
                assistant.usage = data && data.usage ? data.usage : null;
            }

            if (assistant.status !== 'stopped') assistant.status = 'done';
            if (!assistant.content && !assistant.error) {
                assistant.status = 'error';
                assistant.error = '上游返回了空响应';
            }
        } catch (err) {
            if (err && err.name === 'AbortError') {
                assistant.status = 'stopped';
                if (!assistant.content) assistant.content = '（已停止）';
            } else {
                assistant.status = 'error';
                assistant.error = (err && err.message) ? err.message : '请求失败';
                showToast(assistant.error, false);
            }
        } finally {
            clearTimeout(state.streamTimer);
            state.streamTimer = null;
            state.streamMsg = null;
            state.generating = false;
            state.abortController = null;
            if (!assistant.content && !assistant.error && assistant.status !== 'stopped') {
                conv.messages = conv.messages.filter(function (msg) { return msg.id !== assistant.id; });
            }
            conv.updatedAt = now();
            await persist(conv);
            updateComposer();
            renderMessages();
            renderHeader();
            renderList();
            if (state.autoScroll) scrollToBottom(true);
        }
    }

    function stopGeneration() {
        if (state.abortController) state.abortController.abort();
    }

    async function readError(response) {
        try {
            const data = await response.json();
            if (data && data.error) {
                if (typeof data.error === 'string') return data.error;
                if (data.error.message) return data.error.message;
            }
            if (data && data.detail) return String(data.detail);
            if (data && data.message) return String(data.message);
        } catch (err) {
            // fall through
        }
        try {
            const text = await response.text();
            return text ? text.slice(0, 400) : ('HTTP ' + response.status);
        } catch (err) {
            return 'HTTP ' + response.status;
        }
    }

    function applyChunk(obj, assistant) {
        if (obj.error) {
            const error = obj.error;
            throw new Error(typeof error === 'string' ? error : (error.message || '上游返回错误'));
        }
        const choice = obj.choices && obj.choices[0];
        const delta = (choice && choice.delta) || (choice && choice.message) || null;
        if (delta) {
            if (typeof delta.content === 'string') {
                assistant.content += delta.content;
            } else if (Array.isArray(delta.content)) {
                delta.content.forEach(function (part) {
                    if (part && typeof part.text === 'string') assistant.content += part.text;
                });
            }
            if (typeof delta.reasoning_content === 'string') assistant.reasoning += delta.reasoning_content;
            if (typeof delta.reasoning === 'string') assistant.reasoning += delta.reasoning;
            if (typeof delta.thinking === 'string') assistant.reasoning += delta.thinking;
        } else if (typeof obj.content === 'string') {
            assistant.content += obj.content;
        }
        if (obj.usage) assistant.usage = obj.usage;
        scheduleStreamUpdate(assistant);
    }

    function scheduleStreamUpdate(msg) {
        state.streamMsg = msg;
        if (state.streamTimer) return;
        state.streamTimer = setTimeout(function () {
            state.streamTimer = null;
            const target = state.streamMsg;
            if (!target) return;
            updateAssistantEl(target);
            if (state.autoScroll) scrollToBottom();
        }, 40);
    }

    async function consumeSSE(response, assistant) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finished = false;

        function handleBlock(block) {
            const lines = block.split('\n');
            const data = lines.filter(function (line) {
                return line.indexOf('data:') === 0;
            }).map(function (line) {
                return line.slice(5).replace(/^\s/, '');
            }).join('\n');
            if (!data) return false;
            if (data.trim() === '[DONE]') return true;
            let obj;
            try {
                obj = JSON.parse(data);
            } catch (err) {
                return false;
            }
            applyChunk(obj, assistant);
            return false;
        }

        while (!finished) {
            const result = await reader.read();
            if (result.done) break;
            buffer += decoder.decode(result.value, { stream: true });
            buffer = buffer.replace(/\r\n/g, '\n');
            let boundary = buffer.indexOf('\n\n');
            while (boundary >= 0) {
                const block = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                if (handleBlock(block)) {
                    finished = true;
                    break;
                }
                boundary = buffer.indexOf('\n\n');
            }
        }

        if (!finished && buffer.trim()) {
            handleBlock(buffer);
        }
    }

    function regenerate() {
        if (state.generating) return;
        const conv = currentConversation();
        if (!conv) return;
        let lastAssistant = -1;
        for (let i = conv.messages.length - 1; i >= 0; i -= 1) {
            if (conv.messages[i].role === 'assistant') {
                lastAssistant = i;
                break;
            }
        }
        if (lastAssistant < 0) return;
        conv.messages.splice(lastAssistant);
        if (!conv.messages.some(function (msg) { return msg.role === 'user'; })) {
            renderMessages();
            return;
        }
        conv.updatedAt = now();
        persist(conv);
        renderAll();
        runCompletion(conv);
    }

    // ============ 会话操作 ============

    function renameCurrent() {
        const conv = currentConversation();
        if (!conv) return;
        const value = window.prompt(
            window.I18N ? window.I18N.t('重命名会话') : '重命名会话',
            conv.title || (window.I18N ? window.I18N.t('新对话') : '新对话'),
        );
        if (value === null) return;
        const title = value.trim();
        if (!title) return;
        conv.title = title.slice(0, 80);
        conv.updatedAt = now();
        persist(conv);
        renderHeader();
        renderList();
    }

    async function deleteConversation(id) {
        if (state.generating) {
            showToast('请先停止当前回复', false);
            return;
        }
        const conv = state.conversations.find(function (item) { return item.id === id; });
        if (!conv) return;
        const confirmText = window.I18N
            ? window.I18N.t('删除会话「') + (conv.title || window.I18N.t('新对话')) + window.I18N.t('」？此操作只影响本机。')
            : '删除会话「' + (conv.title || '新对话') + '」？此操作只影响本机。';
        if (!window.confirm(confirmText)) return;

        state.conversations = state.conversations.filter(function (item) { return item.id !== id; });
        if (state.storeMode === 'idb' && state.db) {
            try {
                await withTimeout(idbDelete(id), 1200, 'indexedDB delete timeout');
            } catch (err) {
                state.storeMode = 'local';
                persistLocalAll();
            }
        } else {
            persistLocalAll();
        }

        if (state.currentId === id) {
            const next = state.conversations.slice().sort(function (a, b) {
                return b.updatedAt - a.updatedAt;
            })[0];
            if (next) {
                state.currentId = next.id;
                renderAll();
            } else {
                createConversation();
                renderAll();
            }
        } else {
            renderList();
        }
    }

    function exportCurrent() {
        const conv = currentConversation();
        if (!conv) {
            showToast('当前没有可导出的会话', false);
            return;
        }
        const payload = {
            version: 1,
            exportedAt: new Date().toISOString(),
            conversation: conv,
        };
        downloadFile(
            'starggle-api-chat-' + new Date().toISOString().slice(0, 10) + '.json',
            JSON.stringify(payload, null, 2)
        );
        showToast('已导出当前会话');
    }

    function downloadFile(filename, text) {
        const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function handleImport(file) {
        if (!file || state.generating) return;
        const reader = new FileReader();
        reader.onload = async function () {
            let parsed;
            try {
                parsed = JSON.parse(String(reader.result || ''));
            } catch (err) {
                showToast('导入失败：文件不是有效的 JSON', false);
                return;
            }
            let list;
            if (Array.isArray(parsed)) list = parsed;
            else if (parsed && Array.isArray(parsed.conversations)) list = parsed.conversations;
            else if (parsed && parsed.conversation) list = [parsed.conversation];
            else list = [parsed];

            const imported = [];
            list.forEach(function (raw) {
                const conv = normalizeConversation(raw);
                if (!conv) return;
                conv.id = uid();
                conv.title = conv.title || '导入的对话';
                conv.createdAt = conv.createdAt || now();
                conv.updatedAt = now();
                imported.push(conv);
                state.conversations.unshift(conv);
                persist(conv);
            });

            if (!imported.length) {
                showToast('导入失败：没有识别到会话', false);
                return;
            }
            state.currentId = imported[0].id;
            renderAll();
            showToast('已导入 ' + imported.length + ' 个会话');
        };
        reader.readAsText(file);
        els.importInput.value = '';
    }

    // ============ 设置 ============

    function openSettings(focusPrompt) {
        const conv = currentConversation();
        els.settingsApiKey.value = state.settings.apiKey || '';
        els.settingsModel.value = conv ? (conv.model || '') : '';
        els.settingsPrompt.value = conv ? (conv.systemPrompt || '') : (state.settings.systemPrompt || '');
        els.settingsBase.textContent = location.origin;
        els.settingsModal.classList.add('active');
        setTimeout(function () {
            if (focusPrompt) els.settingsPrompt.focus();
            else els.settingsApiKey.focus();
        }, 60);
    }

    function closeSettings() {
        els.settingsModal.classList.remove('active');
    }

    function saveSettingsFromModal() {
        state.settings.apiKey = els.settingsApiKey.value.trim();
        state.settings.systemPrompt = els.settingsPrompt.value.trim();
        saveSettingsToDisk();

        const conv = currentConversation();
        if (conv) {
            conv.systemPrompt = state.settings.systemPrompt;
            const model = els.settingsModel.value.trim();
            if (model) {
                conv.model = model;
                conv.provider = providerForModel(model, conv.provider);
                conv.asyncType = resolveCluster(model);
            }
            conv.updatedAt = now();
            schedulePersist(conv, true);
        }
        closeSettings();
        state.authRequired = false;
        showToast('设置已保存');
        loadModels().then(function () { renderAll(); });
    }

    // ============ 事件绑定 ============

    function bindEvents() {
        els.newChatBtn.addEventListener('click', function () {
            if (state.generating) {
                showToast('请先停止当前回复', false);
                return;
            }
            createConversation();
            state.autoScroll = true;
            renderAll();
            closeSidebar();
            els.messageInput.focus();
        });

        els.settingsBtn.addEventListener('click', function () { openSettings(false); });
        els.systemPromptBtn.addEventListener('click', function () { openSettings(true); });
        els.exportBtn.addEventListener('click', exportCurrent);
        els.importBtn.addEventListener('click', function () { els.importInput.click(); });
        els.importInput.addEventListener('change', function () {
            handleImport(els.importInput.files && els.importInput.files[0]);
        });

        els.sidebarToggle.addEventListener('click', function () {
            els.app.classList.toggle('sidebar-open');
        });
        els.scrim.addEventListener('click', closeSidebar);

        els.sendBtn.addEventListener('click', function () {
            if (state.generating) stopGeneration();
            else sendFromComposer();
        });

        els.messageInput.addEventListener('input', autoResize);
        els.messageInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                sendFromComposer();
            }
        });

        els.modelPickerBtn.addEventListener('click', openModelConfig);
        els.thinkingToggle.addEventListener('change', function () {
            const conv = currentConversation();
            if (!conv) return;
            conv.thinking = els.thinkingToggle.checked;
            conv.updatedAt = now();
            schedulePersist(conv, true);
            updateThinkingToggle();
        });

        // 运营商下拉
        els.providerField.addEventListener('focus', function () {
            renderProviderList('');
            setComboOpen(els.providerCombo, els.providerList, true);
        });
        els.providerField.addEventListener('input', function () {
            renderProviderList(els.providerField.value);
            renderModelFieldList('');
            setComboOpen(els.providerCombo, els.providerList, true);
        });
        els.providerField.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const first = els.providerCombo.classList.contains('open')
                    ? els.providerList.querySelector('.combo-item') : null;
                if (first) first.click();
                else setComboOpen(els.providerCombo, els.providerList, false);
            } else if (event.key === 'Escape'
                && els.providerCombo.classList.contains('open')) {
                event.stopPropagation();
                setComboOpen(els.providerCombo, els.providerList, false);
            }
        });
        els.providerField.addEventListener('blur', function () {
            setTimeout(function () { setComboOpen(els.providerCombo, els.providerList, false); }, 120);
        });
        els.providerList.addEventListener('click', function (event) {
            const item = event.target.closest('.combo-item');
            if (!item) return;
            const provider = item.dataset.provider || '';
            els.providerField.value = provider;
            const currentModel = els.modelField.value.trim();
            const available = modelsFor(provider, '');
            if (currentModel && !available.some(function (model) { return model.id === currentModel; })) {
                els.modelField.value = '';
            }
            renderModelFieldList('');
            setComboOpen(els.providerCombo, els.providerList, false);
            els.modelField.focus();
        });

        // 模型下拉
        els.modelField.addEventListener('focus', function () {
            renderModelFieldList('');
            setComboOpen(els.modelCombo, els.modelFieldList, true);
        });
        els.modelField.addEventListener('input', function () {
            renderModelFieldList(els.modelField.value);
            setComboOpen(els.modelCombo, els.modelFieldList, true);
        });
        els.modelField.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const first = els.modelCombo.classList.contains('open')
                    ? els.modelFieldList.querySelector('.combo-item') : null;
                if (first) first.click();
                else setComboOpen(els.modelCombo, els.modelFieldList, false);
            } else if (event.key === 'Escape'
                && els.modelCombo.classList.contains('open')) {
                event.stopPropagation();
                setComboOpen(els.modelCombo, els.modelFieldList, false);
            }
        });
        els.modelField.addEventListener('blur', function () {
            setTimeout(function () { setComboOpen(els.modelCombo, els.modelFieldList, false); }, 120);
        });
        els.modelFieldList.addEventListener('click', function (event) {
            const item = event.target.closest('.combo-item');
            if (!item) return;
            els.modelField.value = item.dataset.model || '';
            setComboOpen(els.modelCombo, els.modelFieldList, false);
        });

        els.paramTemperature.addEventListener('input', function () { onSamplingInput('temperature'); });
        els.paramTopP.addEventListener('input', function () { onSamplingInput('top_p'); });

        els.modelConfigSave.addEventListener('click', applyModelConfig);
        els.modelConfigCancel.addEventListener('click', closeModelConfig);
        els.modelConfigClose.addEventListener('click', closeModelConfig);
        els.modelConfigModal.addEventListener('click', function (event) {
            if (event.target === els.modelConfigModal) closeModelConfig();
        });

        els.convTitle.addEventListener('click', renameCurrent);

        els.messages.addEventListener('click', function (event) {
            const codeButton = event.target.closest('.code-copy');
            if (codeButton) {
                const block = codeButton.closest('.code-block');
                const code = block && block.querySelector('code');
                if (code) copyText(code.textContent || '');
                return;
            }
            const action = event.target.closest('[data-action]');
            if (!action) return;
            const msgId = action.dataset.id;
            const conv = currentConversation();
            if (!conv) return;
            const msg = conv.messages.find(function (item) { return item.id === msgId; });
            if (!msg) return;
            if (action.dataset.action === 'copy') {
                const text = msg.role === 'assistant' ? msg.content : msg.content;
                copyText(text || '');
            } else if (action.dataset.action === 'regenerate') {
                regenerate();
            }
        });

        els.messages.addEventListener('scroll', function () {
            const gap = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight;
            state.autoScroll = gap < 120;
        });

        els.settingsSave.addEventListener('click', saveSettingsFromModal);
        els.settingsCancel.addEventListener('click', closeSettings);
        els.settingsClose.addEventListener('click', closeSettings);
        els.settingsModal.addEventListener('click', function (event) {
            if (event.target === els.settingsModal) closeSettings();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                closeSettings();
                closeModelConfig();
                closeSidebar();
            }
        });

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden') {
                const conv = currentConversation();
                if (conv) persist(conv);
            }
        });
    }

    function closeSidebar() {
        els.app.classList.remove('sidebar-open');
    }

    async function boot() {
        cacheEls();
        loadSettings();
        bindEvents();
        await initStore();
        await loadConversations();
        if (!state.conversations.length) {
            createConversation();
        } else {
            state.currentId = state.conversations[0].id;
        }
        await loadModels();
        renderAll();
        autoResize();
        setTimeout(function () { els.messageInput.focus(); }, 80);
    }

    document.addEventListener('DOMContentLoaded', boot);
})();
